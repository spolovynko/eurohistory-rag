"""FastAPI application factory and the module-level app uvicorn imports."""

from fastapi import FastAPI

from eurohistory_rag import __version__


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

    return app


# uvicorn imports an object, not a function: `main:app`. Tests call
# create_app() directly and ignore this.
app = create_app()
