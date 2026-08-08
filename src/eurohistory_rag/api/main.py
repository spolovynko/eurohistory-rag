"""FastAPI application factory and the module-level app uvicorn imports."""

from importlib.resources import files
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from eurohistory_rag import __version__
from eurohistory_rag.api.dependencies import (
    configured_generation_service,
    get_generation_service,
    get_search_service,
    get_vector_store,
)
from eurohistory_rag.core.config import CORPUS_LICENSE, Settings, get_settings
from eurohistory_rag.eval.browse import RunListing, RunView, list_runs, load_run
from eurohistory_rag.generation.client import GenerationUnavailable
from eurohistory_rag.generation.service import Citation, GenerationService
from eurohistory_rag.retrieval.search import DEFAULT_K, SearchResult, SearchService
from eurohistory_rag.retrieval.vectorstore import VectorStore, VectorStoreUnavailable

# A ceiling on k, so one request cannot ask for the whole corpus.
MAX_K = 50

# The one page, read once at import. It sits next to this module as .html
# rather than inside a template engine for the reason system_prompt.md sits
# next to messages.py: it is edited far more often than the code serving it,
# and nothing in it needs rendering -- the browser fills it in from /ask.
PAGE = files("eurohistory_rag.api").joinpath("page.html").read_text(encoding="utf-8")


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


def _overridden(request: AskRequest) -> bool:
    """Whether this request asked for anything other than the process default.

    The test that keeps the fakes working: with nothing named, the endpoint uses
    the service FastAPI injected, which is what `dependency_overrides` replaces.
    """
    return any(
        value is not None for value in (request.hybrid, request.reranker, request.model)
    )


def _chosen_reranker(request: AskRequest, settings: Settings) -> str | None:
    """Which reranker this request wants, or None for no reranking.

    An empty string is how a client says "switch it off", because a JSON null
    already means "leave it alone" -- the two are different requests and a
    single field has to carry both.
    """
    if request.reranker is None:
        return settings.reranker_model if settings.reranker_enabled else None
    return request.reranker or None


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

    @app.post("/ask", summary="Answer a question from the corpus, with citations")
    def ask(
        service: Annotated[GenerationService, Depends(get_generation_service)],
        request: AskRequest,
    ) -> AskResponse:
        """Answer a question using only the indexed corpus.

        POST rather than GET because a question is input the server acts on,
        it can be long, and it has no business sitting in a URL that ends up
        in access logs and browser history.

        Still the only path from a question to an answer, overrides or not --
        D-090's third decision. A request naming nothing uses the injected
        service, which is what keeps the tests' fakes in play and what the eval
        runner's equivalent does.
        """
        settings = get_settings()
        used = Configuration(
            model=request.model or settings.generation_model,
            reranker=_chosen_reranker(request, settings),
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

        try:
            answer = service.ask(request.question, k=request.k)
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

    return app


# uvicorn imports an object, not a function: `main:app`. Tests call
# create_app() directly and ignore this.
app = create_app()
