"""FastAPI application factory and the module-level app uvicorn imports."""

from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, status
from pydantic import BaseModel, Field

from eurohistory_rag import __version__
from eurohistory_rag.api.dependencies import (
    get_generation_service,
    get_search_service,
    get_vector_store,
)
from eurohistory_rag.core.config import CORPUS_LICENSE
from eurohistory_rag.generation.client import GenerationUnavailable
from eurohistory_rag.generation.service import Citation, GenerationService
from eurohistory_rag.retrieval.search import DEFAULT_K, SearchResult, SearchService
from eurohistory_rag.retrieval.vectorstore import VectorStore, VectorStoreUnavailable

# A ceiling on k, so one request cannot ask for the whole corpus.
MAX_K = 50


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
    """A question, and how widely to search for it."""

    question: str = Field(min_length=1, max_length=500)
    k: int = Field(default=DEFAULT_K, ge=1, le=MAX_K)


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
    """A grounded answer and only the sources it used."""

    question: str
    answer: str
    model: str
    license: str
    sources: list[AnswerSource]


def create_app() -> FastAPI:
    """Build and return a new FastAPI application.

    A factory rather than a module-level object so that each caller gets an
    independent app. Tests can build one per test, and from Phase 5 onward can
    build one wired to fakes, without touching the app uvicorn serves.
    """
    app = FastAPI(title="Eurohistory RAG API", version=__version__)

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

    @app.post("/ask", summary="Answer a question from the corpus, with citations")
    def ask(
        service: Annotated[GenerationService, Depends(get_generation_service)],
        request: AskRequest,
    ) -> AskResponse:
        """Answer a question using only the indexed corpus.

        POST rather than GET because a question is input the server acts on,
        it can be long, and it has no business sitting in a URL that ends up
        in access logs and browser history.
        """
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
        )

    return app


# uvicorn imports an object, not a function: `main:app`. Tests call
# create_app() directly and ignore this.
app = create_app()
