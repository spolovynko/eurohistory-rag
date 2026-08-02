"""What the endpoints need, built once and handed to them by FastAPI.

Separate from `main.py` because the endpoints should say *what* they need, not
*how* it is constructed -- and because tests replace exactly these functions to
run the API against fakes.
"""

from functools import lru_cache

from eurohistory_rag.core.config import get_settings
from eurohistory_rag.retrieval.embedding import OpenAIEmbedder
from eurohistory_rag.retrieval.search import SearchService
from eurohistory_rag.retrieval.vectorstore import VectorStore


@lru_cache(maxsize=1)
def get_search_service() -> SearchService:
    """The one SearchService for this process.

    Cached for the same reason `get_settings` is: an OpenAI client and a Qdrant
    connection are expensive to build and safe to share, so a request should
    reuse them rather than open its own. Built lazily on first request, so
    importing the app never requires Qdrant to be running.
    """
    settings = get_settings()
    embedder = OpenAIEmbedder(
        api_key=settings.openai_api_key.get_secret_value(),
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
    )
    store = VectorStore.connect(
        settings.qdrant_url,
        settings.qdrant_collection,
        settings.embedding_dimensions,
    )
    return SearchService(embedder, store)
