"""FastAPI application factory and the module-level app uvicorn imports."""

from typing import Annotated

from fastapi import Depends, FastAPI, Query
from pydantic import BaseModel

from eurohistory_rag import __version__
from eurohistory_rag.api.dependencies import get_search_service
from eurohistory_rag.core.config import CORPUS_LICENSE
from eurohistory_rag.retrieval.search import DEFAULT_K, SearchResult, SearchService

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
        results = service.search(q, k=k)
        return SearchResponse(
            query=q,
            k=k,
            count=len(results),
            license=CORPUS_LICENSE,
            results=[SearchHit.from_result(result) for result in results],
        )

    return app


# uvicorn imports an object, not a function: `main:app`. Tests call
# create_app() directly and ignore this.
app = create_app()
