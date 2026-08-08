"""FastAPI application factory and the module-level app uvicorn imports."""

import json
import logging
from collections.abc import Iterator
from importlib.resources import files
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from eurohistory_rag import __version__
from eurohistory_rag.api.dependencies import (
    configured_generation_service,
    get_generation_service,
    get_search_service,
    get_vector_store,
)
from eurohistory_rag.api.experiment import (
    Precondition,
    check_preconditions,
    make_work,
    write_prediction,
)
from eurohistory_rag.api.jobs import EvalJob, JobStatus, get_job
from eurohistory_rag.core.config import CORPUS_LICENSE, Settings, get_settings
from eurohistory_rag.eval.browse import RunListing, RunView, list_runs, load_run
from eurohistory_rag.eval.cost import estimate
from eurohistory_rag.eval.execute import RunConfig
from eurohistory_rag.eval.questions import QUESTIONS_PATH, load_questions
from eurohistory_rag.eval.record import RUNS_DIR, new_run_id
from eurohistory_rag.generation.client import GenerationUnavailable
from eurohistory_rag.generation.service import Citation, GenerationService
from eurohistory_rag.retrieval.search import DEFAULT_K, SearchResult, SearchService
from eurohistory_rag.retrieval.vectorstore import VectorStore, VectorStoreUnavailable

# A ceiling on k, so one request cannot ask for the whole corpus.
MAX_K = 50

# The front end, read once at import. It lives beside this module as ordinary
# files rather than inside a template engine, for the reason system_prompt.md
# sits beside messages.py: it is edited far more often than the code serving
# it, and nothing in it needs rendering -- the browser fills it in from /ask.
#
# One file per job. `app.css` is 651 lines and `main.js` is 20; keeping them in
# one document meant every styling tweak and every behaviour change landed in
# the same diff, and an editor could not tell the browser what language it was
# looking at.
STATIC_TYPES = {".html": "text/html", ".css": "text/css", ".js": "text/javascript"}

# Name -> (contents, media type), for exactly the files shipped in the package.
# A dict rather than a mounted directory: the name arrives in a URL, and a
# lookup that can only ever hit a key cannot be talked into leaving the folder.
STATIC = {
    item.name: (item.read_text(encoding="utf-8"), STATIC_TYPES[Path(item.name).suffix])
    for item in files("eurohistory_rag.api.static").iterdir()
    if Path(item.name).suffix in STATIC_TYPES
}

PAGE = STATIC["index.html"][0]

logger = logging.getLogger(__name__)


class SearchHit(BaseModel):
    """One matching chunk, as the API presents it.

    A separate type from `SearchResult` on purpose: this one is the public
    contract. `source` and `url` are computed inside the service and sent as
    plain fields, so a client never has to know how a citation is built.
    """

    chunk_id: str
    doc_id: str
    page_id: int
    title: str
    heading: str
    source: str
    text: str
    score: float
    url: str

    @classmethod
    def from_result(cls, result: SearchResult) -> "SearchHit":
        """Convert one internal result into its public form."""
        return cls(
            chunk_id=result.chunk_id,
            doc_id=result.doc_id,
            page_id=result.page_id,
            title=result.title,
            heading=result.heading,
            source=result.source,
            text=result.text,
            score=result.score,
            url=result.url,
        )


class SearchResponse(BaseModel):
    """A search and what it found.

    `count` is separate from `k` because thinning can return fewer than asked
    for: five slots holding three distinct sections beats five holding one page
    three times.
    """

    query: str
    k: int
    count: int
    license: str
    results: list[SearchHit]


class AskRequest(BaseModel):
    """A question, how widely to search for it, and how to answer it.

    The three optional fields are per-request overrides of what `.env` sets.
    `None` means "use this process's default", which is what the eval runner
    uses -- so a request that names nothing behaves exactly as it did before
    these existed. D-092.
    """

    question: str = Field(min_length=1, max_length=500)
    k: int = Field(default=DEFAULT_K, ge=1, le=MAX_K)
    hybrid: bool | None = None
    reranker: str | None = None
    model: str | None = None


class Configuration(BaseModel):
    """The settings an answer was actually produced under.

    Returned with every answer, not only when something was overridden. Phase 8
    shipped a measurement whose reranker was switched off and nobody noticed;
    an answer that cannot say what produced it is that failure waiting to
    happen in front of a person instead of in a run directory.
    """

    model: str
    reranker: str | None
    hybrid: bool
    k: int


class OptionsResponse(BaseModel):
    """What this server will accept, and what it does when asked for nothing.

    The page reads this rather than hardcoding a list of models: a name that is
    not on the allow-list is refused, so the page and the server would disagree
    the moment either was edited alone.
    """

    models: list[str]
    rerankers: list[str]
    defaults: Configuration
    max_k: int


# The hosts a run may be started from. There is no authentication anywhere in
# this system and a run costs about eight cents, so the only thing between those
# two facts is this list. It is a guard against the deployment mistake -- binding
# uvicorn to 0.0.0.0 and walking away -- not against an attacker, and it is
# written in code rather than in a comment so that mistake fails closed.
LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})


class ExperimentPlan(BaseModel):
    """What a run would cost and whether it could succeed, before one is started.

    Everything a person needs to answer "should I press this?" in one request:
    the price, where the price came from, and each precondition separately so a
    refusal names the thing to fix rather than saying no.
    """

    questions: int
    dollars: float
    basis: str
    preconditions: list[Precondition]
    ready: bool
    defaults: Configuration


class StartRequest(BaseModel):
    """A request to spend money, and the prediction that entitles it to.

    `prediction` has a minimum length rather than being optional, so obligation
    9 is enforced by the schema: a client that omits it gets a 422 and no run.
    `questions` is the count the caller was quoted; the server checks it still
    matches, so nobody confirms one price and pays another.
    """

    prediction: str = Field(min_length=10, max_length=4000)
    questions: int = Field(ge=1)
    baseline: str | None = None
    note: str = ""
    k: int = Field(default=DEFAULT_K, ge=1, le=MAX_K)
    hybrid: bool | None = None
    reranker: str | None = None
    model: str | None = None


class AnswerSource(BaseModel):
    """One source the answer actually cited.

    `n` is the number that appears in the answer text as [n], which is what
    lets a client turn a marker into a link.
    """

    n: int
    chunk_id: str
    title: str
    heading: str
    source: str
    url: str
    score: float
    text: str

    @classmethod
    def from_citation(cls, citation: Citation) -> "AnswerSource":
        """Convert one internal citation into its public form."""
        result = citation.result
        return cls(
            n=citation.number,
            chunk_id=result.chunk_id,
            title=result.title,
            heading=result.heading,
            source=result.source,
            url=result.url,
            score=result.score,
            text=result.text,
        )


class AskResponse(BaseModel):
    """A grounded answer, only the sources it used, and what produced it."""

    question: str
    answer: str
    model: str
    license: str
    sources: list[AnswerSource]
    configuration: Configuration


# What a client sends in `Accept` to be given the answer as it is written. HTTP
# already has a way to say "which shape of this resource do you want", so the
# streaming choice is made there rather than in a second URL -- D-090's third
# decision says there is one path from a question to an answer, and this keeps
# that literally true. D-095.
SSE_TYPE = "text/event-stream"


def _sse(event: str, payload: object) -> str:
    """One server-sent event: a named kind, and one line of JSON.

    The wire format is two labelled lines and a blank one. It is this small on
    purpose -- the alternative was a websocket, which is a second protocol, a
    second failure mode and a connection to keep alive for a four-second job.
    """
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


def _answer_events(
    service: GenerationService,
    question: str,
    results: list[SearchResult],
    used: Configuration,
) -> Iterator[str]:
    """The answer as a stream of events: sources, then text, then the rest.

    The sources go first because they are already known -- retrieval finished
    before this generator was ever iterated -- and they are the thing a reader
    can start on while the model writes. The citations cannot go with them: a
    marker only becomes a citation once the sentence holding it exists.

    A failure here arrives *after* the 200 was sent, so it cannot become a
    status code. It becomes an `error` event instead, and the page is
    responsible for making that look like a failure rather than an answer.
    """
    yield _sse(
        "sources",
        [SearchHit.from_result(result).model_dump() for result in results],
    )
    try:
        for piece in service.stream_from(question, results):
            if isinstance(piece, str):
                yield _sse("token", piece)
            else:
                yield _sse(
                    "done",
                    AskResponse(
                        question=piece.question,
                        answer=piece.text,
                        model=piece.model,
                        license=CORPUS_LICENSE,
                        sources=[
                            AnswerSource.from_citation(citation)
                            for citation in piece.citations
                        ],
                        configuration=used.model_copy(update={"model": piece.model}),
                    ).model_dump(),
                )
    except (VectorStoreUnavailable, GenerationUnavailable) as error:
        logger.warning("stream failed after the response began: %s", error)
        yield _sse("error", "Answering is temporarily unavailable.")


def _overridden(request: AskRequest) -> bool:
    """Whether this request asked for anything other than the process default.

    The test that keeps the fakes working: with nothing named, the endpoint uses
    the service FastAPI injected, which is what `dependency_overrides` replaces.
    """
    return any(
        value is not None for value in (request.hybrid, request.reranker, request.model)
    )


def _chosen_reranker(requested: str | None, settings: Settings) -> str | None:
    """Which reranker this request wants, or None for no reranking.

    An empty string is how a client says "switch it off", because a JSON null
    already means "leave it alone" -- the two are different requests and a
    single field has to carry both. Takes the field rather than the request so
    that /ask and the run button resolve it through the same three lines.
    """
    if requested is None:
        return settings.reranker_model if settings.reranker_enabled else None
    return requested or None


def create_app() -> FastAPI:
    """Build and return a new FastAPI application.

    A factory rather than a module-level object so that each caller gets an
    independent app. Tests can build one per test, and from Phase 5 onward can
    build one wired to fakes, without touching the app uvicorn serves.
    """
    app = FastAPI(title="Eurohistory RAG API", version=__version__)

    @app.get("/", summary="The one page", response_class=HTMLResponse)
    def page() -> str:
        """Serve the question page.

        The only route in this app that returns something for a person rather
        than for a program. It holds no state and calls nothing: everything on
        it arrives from /ask, so the page and the eval runner ask the identical
        question of the identical code.
        """
        return PAGE

    @app.get("/static/{name}", summary="One stylesheet or script")
    def static(name: str) -> Response:
        """Serve one of the files shipped beside this module.

        `name` comes from a URL, so it is looked up in a dictionary built at
        import rather than joined onto a path -- the same rule the run browser
        follows. A name that is not a key is a 404 and touches no filesystem.
        """
        if name not in STATIC:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"No file {name!r}."
            )
        body, media_type = STATIC[name]
        return Response(content=body, media_type=media_type)

    @app.get("/health", summary="Health check endpoint")
    async def health() -> dict[str, str]:
        """Report that the process is alive.

        Liveness only: it checks nothing downstream. When Qdrant and OpenAI
        arrive, a readiness endpoint is the place for those, not this one.
        """
        return {"status": "ok"}

    @app.get("/ready", summary="Readiness check — is the vector store reachable?")
    def ready(
        store: Annotated[VectorStore, Depends(get_vector_store)],
    ) -> dict[str, str]:
        """Report whether this process can actually serve a search.

        The other half of /health, and a deliberately separate endpoint. /health
        answering "ok" while Qdrant is down is not a bug in /health -- liveness
        and readiness are different questions, and a restarter that conflates
        them will keep restarting a healthy process because a database is down.
        """
        if not store.is_ready():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Vector store unreachable or collection missing.",
            )
        return {"status": "ready"}

    @app.get("/search", summary="Find the chunks that best match a question")
    def search(
        service: Annotated[SearchService, Depends(get_search_service)],
        q: Annotated[str, Query(min_length=1, max_length=500)],
        k: Annotated[int, Query(ge=1, le=MAX_K)] = DEFAULT_K,
    ) -> SearchResponse:
        """Search the corpus.

        Deliberately `def` and not `async def`: this handler calls OpenAI and
        Qdrant with blocking clients, and a blocking call inside an async
        handler stalls the whole event loop for every other request. Declared
        sync, FastAPI runs it in a thread pool instead.
        """
        try:
            results = service.search(q, k=k)
        except VectorStoreUnavailable as error:
            # A stack trace tells the caller nothing they can act on, and a 500
            # says "we are broken" when the honest answer is "come back later".
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Search is temporarily unavailable.",
            ) from error
        return SearchResponse(
            query=q,
            k=k,
            count=len(results),
            license=CORPUS_LICENSE,
            results=[SearchHit.from_result(result) for result in results],
        )

    @app.get("/options", summary="What this server will accept on /ask")
    def options() -> OptionsResponse:
        """The allow-lists and the defaults, so a client need not guess either."""
        settings = get_settings()
        return OptionsResponse(
            models=list(settings.selectable_models),
            rerankers=list(settings.selectable_rerankers),
            defaults=Configuration(
                model=settings.generation_model,
                reranker=settings.reranker_model if settings.reranker_enabled else None,
                hybrid=settings.hybrid_enabled,
                k=DEFAULT_K,
            ),
            max_k=MAX_K,
        )

    @app.post(
        "/ask",
        summary="Answer a question from the corpus, with citations",
        response_model=AskResponse,
    )
    def ask(
        service: Annotated[GenerationService, Depends(get_generation_service)],
        request: AskRequest,
        http: Request,
    ) -> AskResponse | Response:
        """Answer a question using only the indexed corpus.

        POST rather than GET because a question is input the server acts on,
        it can be long, and it has no business sitting in a URL that ends up
        in access logs and browser history.

        Still the only path from a question to an answer, overrides or not --
        D-090's third decision. A request naming nothing uses the injected
        service, which is what keeps the tests' fakes in play and what the eval
        runner's equivalent does.

        One question, two shapes. `Accept: text/event-stream` gets the answer as
        it is written; anything else gets the same answer as one JSON object,
        assembled from the identical call. `response_model` is declared on the
        decorator rather than inferred, so /docs still describes the JSON.
        """
        settings = get_settings()
        used = Configuration(
            model=request.model or settings.generation_model,
            reranker=_chosen_reranker(request.reranker, settings),
            hybrid=(
                settings.hybrid_enabled if request.hybrid is None else request.hybrid
            ),
            k=request.k,
        )
        if request.model and request.model not in settings.selectable_models:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Unknown model {request.model!r}.",
            )
        if request.reranker and request.reranker not in settings.selectable_rerankers:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Unknown reranker {request.reranker!r}.",
            )

        if _overridden(request):
            service = configured_generation_service(
                hybrid=used.hybrid, reranker=used.reranker, model=used.model
            )

        streaming = SSE_TYPE in http.headers.get("accept", "")
        try:
            # Retrieval runs here in both shapes, and that is the point: it is
            # the half that can fail before a single byte has left, so a dead
            # Qdrant is still an honest 503 rather than an apology inside a
            # response that already claimed success.
            results = service.search(request.question, k=request.k)
            if streaming:
                return StreamingResponse(
                    _answer_events(service, request.question, results, used),
                    media_type=SSE_TYPE,
                    # Buffering proxies are the one thing that can undo this
                    # phase: an intermediary holding the response back until it
                    # is complete restores exactly the blank screen we removed.
                    headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
                )
            answer = service.answer_from(request.question, results)
        except (VectorStoreUnavailable, GenerationUnavailable) as error:
            # Two different failures, one message: the caller can do nothing
            # differently about a dead Qdrant than about a dead OpenAI.
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Answering is temporarily unavailable.",
            ) from error
        return AskResponse(
            question=answer.question,
            answer=answer.text,
            model=answer.model,
            license=CORPUS_LICENSE,
            sources=[
                AnswerSource.from_citation(citation) for citation in answer.citations
            ],
            # `answer.model` is what the generator reports; `used.model` is what
            # was asked for. They agree, and reporting the requested one would
            # hide the day they stop agreeing.
            configuration=used.model_copy(update={"model": answer.model}),
        )

    @app.get("/runs", summary="Every evaluation run saved on disk")
    def runs() -> list[RunListing]:
        """List the saved runs, newest first.

        Read-only, and deliberately so: there is no endpoint that *starts* an
        evaluation. That would put a $0.08 four-minute job behind a button, and
        a run produced by clicking is a run nobody predicted the result of --
        which is the one thing obligation 9 exists to prevent.
        """
        return list_runs()

    @app.get("/runs/{run_id}", summary="One evaluation run, scored")
    def run(run_id: str) -> RunView:
        """Score one saved run the three ways this project reports it.

        The dataclasses from `eval/browse.py` are the response contract rather
        than a hand-written copy of them. Unlike /search, where the internal
        result carries fields the public shape should not, these types were
        written to be reported -- a second declaration would be nineteen
        duplicated field names and one more place to forget a metric.
        """
        view = load_run(run_id)
        if view is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No run named {run_id!r}.",
            )
        return view

    @app.get("/eval/plan", summary="What a run would cost, and whether it could work")
    def plan(model: str | None = None) -> ExperimentPlan:
        """Price the run and check the preconditions. Spends nothing.

        Its own request rather than a field on the start request, because the
        answer has to be on screen *before* the control that spends is live.
        D-083 says state the cost before spending it; this is that sentence,
        computed rather than remembered.
        """
        settings = get_settings()
        questions = load_questions(QUESTIONS_PATH)
        chosen = model or settings.generation_model
        quote = estimate(chosen, len(questions))
        checks = check_preconditions(settings)
        return ExperimentPlan(
            questions=len(questions),
            dollars=quote.dollars,
            basis=quote.basis,
            preconditions=checks,
            ready=all(check.ok for check in checks),
            defaults=Configuration(
                model=chosen,
                reranker=settings.reranker_model if settings.reranker_enabled else None,
                hybrid=settings.hybrid_enabled,
                k=DEFAULT_K,
            ),
        )

    @app.get("/eval/run", summary="What the running evaluation is doing")
    def evaluation(job: Annotated[EvalJob, Depends(get_job)]) -> JobStatus:
        """The state of the one run this process can have.

        Polled rather than pushed. The state lives in the server, so a reload,
        a second tab or a different browser all see the same run -- and closing
        the page that started it does not stop it.
        """
        return job.status()

    @app.post("/eval/run", summary="Start an evaluation — this spends money")
    def start_evaluation(
        request: Request,
        body: StartRequest,
        job: Annotated[EvalJob, Depends(get_job)],
    ) -> JobStatus:
        """Run every question and gate the result, in the background.

        The order in this function is the phase. The prediction is written to
        disk before the thread exists, so there is no path in which a question
        is asked and no prediction is on file -- which is obligation 9 enforced
        by the interface instead of by whoever is at the keyboard.
        """
        client = request.client.host if request.client else ""
        if client not in LOOPBACK:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Evaluations may only be started from this machine.",
            )

        settings = get_settings()
        if body.model and body.model not in settings.selectable_models:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Unknown model {body.model!r}.",
            )
        if body.reranker and body.reranker not in settings.selectable_rerankers:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Unknown reranker {body.reranker!r}.",
            )

        questions = load_questions(QUESTIONS_PATH)
        if len(questions) != body.questions:
            # The quote and the question file disagree, which means the price
            # shown is not the price about to be paid.
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    f"Quoted {body.questions} questions, the set now holds "
                    f"{len(questions)}. Reload and confirm the new cost."
                ),
            )

        failing = [check for check in check_preconditions(settings) if not check.ok]
        if failing:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="; ".join(check.detail for check in failing),
            )

        baseline = RUNS_DIR / body.baseline if body.baseline else None
        if baseline is not None and not (baseline / "meta.json").exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No run named {body.baseline!r} to compare against.",
            )

        config = RunConfig(
            k=body.k,
            model=body.model or settings.generation_model,
            reranker=_chosen_reranker(body.reranker, settings) or "",
            hybrid=(settings.hybrid_enabled if body.hybrid is None else body.hybrid),
        )

        run_id = new_run_id()
        # Before the thread exists, and therefore before any question can be
        # asked. This one line is the phase.
        write_prediction(run_id, body.prediction, RUNS_DIR)
        started = job.start(
            run_id,
            len(questions),
            make_work(
                questions,
                settings,
                config,
                run_id=run_id,
                note=body.note or "started from the page",
                baseline=baseline,
                runs_dir=RUNS_DIR,
            ),
        )
        if started is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Run {job.status().run_id} is already going.",
            )
        return started

    @app.delete("/eval/run", summary="Stop the running evaluation")
    def cancel_evaluation(job: Annotated[EvalJob, Depends(get_job)]) -> JobStatus:
        """Ask the run to stop after the question it is on.

        Not mid-question: that call is already paid for, and abandoning it would
        leave a record nobody could interpret. A cancelled run writes no
        `records.jsonl`, so it never appears as a run -- only its prediction
        survives, which is the right way round.
        """
        if not job.cancel():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Nothing is running."
            )
        return job.status()

    return app


# uvicorn imports an object, not a function: `main:app`. Tests call
# create_app() directly and ignore this.
app = create_app()
