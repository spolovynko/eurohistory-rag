"""What the endpoints need, built once and handed to them by FastAPI.

Separate from `main.py` because the endpoints should say *what* they need, not
*how* it is constructed -- and because tests replace exactly these functions to
run the API against fakes.
"""

from functools import lru_cache

from eurohistory_rag.core.config import get_settings
from eurohistory_rag.generation.client import OpenAIGenerator
from eurohistory_rag.generation.service import GenerationService
from eurohistory_rag.retrieval.embedding import OpenAIEmbedder
from eurohistory_rag.retrieval.rerank import LocalReranker, Reranker
from eurohistory_rag.retrieval.search import SearchService
from eurohistory_rag.retrieval.vectorstore import VectorStore


@lru_cache(maxsize=1)
def get_vector_store() -> VectorStore:
    """The one Qdrant connection for this process.

    Its own function rather than a detail of `get_search_service` because
    /ready needs the store without needing a search: asking "is the database
    up?" should not require an embedder or an OpenAI key.
    """
    settings = get_settings()
    return VectorStore.connect(
        settings.qdrant_url,
        settings.qdrant_collection,
        settings.embedding_dimensions,
    )


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
    return SearchService(
        embedder,
        get_vector_store(),
        reranker=get_reranker(),
        hybrid=settings.hybrid_enabled,
        temporal=settings.temporal_enabled,
        max_per_article=settings.max_per_article,
    )


@lru_cache(maxsize=1)
def get_generation_service() -> GenerationService:
    """The one GenerationService for this process.

    Cached like the others: it holds an OpenAI client and a Qdrant connection
    underneath, and building those per request would be pure waste.
    """
    settings = get_settings()
    generator = OpenAIGenerator(
        api_key=settings.openai_api_key.get_secret_value(),
        model=settings.generation_model,
    )
    return GenerationService(
        get_search_service(),
        generator,
        verifier=get_verifier(),
        rewriter=get_rewriter(),
    )


@lru_cache(maxsize=1)
def get_rewriter() -> OpenAIGenerator | None:
    """The follow-up rewriter's client, or None when conversation is off.

    Its own function for the reason `get_verifier` is: "the feature is off" is
    one value in one place, and a request that carries no history never reaches
    it either way. Phase 24, D-098.
    """
    settings = get_settings()
    if not settings.conversation_enabled:
        return None
    return OpenAIGenerator(
        api_key=settings.openai_api_key.get_secret_value(),
        model=settings.rewrite_model,
    )


@lru_cache(maxsize=1)
def get_verifier() -> OpenAIGenerator | None:
    """The groundedness gate's client, or None when the gate is off.

    Its own function so that "the gate is off" is one value in one place, and
    so a different checking model needs no change here. Phase 13, D-084.
    """
    settings = get_settings()
    if not settings.verify_enabled:
        return None
    return OpenAIGenerator(
        api_key=settings.openai_api_key.get_secret_value(),
        model=settings.verify_model,
    )


def get_reranker() -> Reranker | None:
    """The one reranker for this process, or None when it is switched off.

    Returns None rather than raising when disabled, so the off state is an
    ordinary value the caller passes straight through.

    Delegates to `get_named_reranker` rather than caching its own instance, and
    that is the whole fix for half of Phase 25's cold start. The page sends a
    reranker name on every request, so every request was overridden; FastAPI
    resolved this function *and then* the handler built a configured service
    through `get_named_reranker`. Same model, two caches, two loads of 88 MB --
    2,181 ms and 2,066 ms measured on a cold process, and both copies resident
    for the life of it. One cache, keyed by name, is the only cache needed.
    D-099.
    """
    settings = get_settings()
    if not settings.reranker_enabled:
        return None
    return get_named_reranker(settings.reranker_model)


# --- per-request configuration ----------------------------------------------
#
# Everything above is the process default: one embedder, one store, one
# reranker, one generator, built from `.env` and shared. What follows lets a
# single request run a different configuration without a restart.
#
# The split matters. The expensive things -- the embedder, the Qdrant
# connection, a reranker's weights -- stay cached and shared, keyed by name so
# each is built at most once. `SearchService` and `GenerationService` are thin
# objects holding references to them, so building one per request costs
# effectively nothing. D-092.


@lru_cache(maxsize=4)
def get_named_reranker(model: str) -> Reranker:
    """One reranker per name, built once and kept.

    Cached by name rather than by "the" reranker: switching between two of them
    should load each once, not once per switch. Four is more than the
    allow-list holds, so nothing is ever evicted and re-read from disk.
    """
    return LocalReranker(model)


@lru_cache(maxsize=8)
def get_generator(model: str) -> OpenAIGenerator:
    """One OpenAI client per answering model."""
    settings = get_settings()
    return OpenAIGenerator(
        api_key=settings.openai_api_key.get_secret_value(), model=model
    )


def configured_search_service(*, hybrid: bool, reranker: str | None) -> SearchService:
    """A search configured for one request, over the shared expensive parts."""
    settings = get_settings()
    embedder = OpenAIEmbedder(
        api_key=settings.openai_api_key.get_secret_value(),
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
    )
    return SearchService(
        embedder,
        get_vector_store(),
        reranker=get_named_reranker(reranker) if reranker else None,
        hybrid=hybrid,
        # Not switchable per request, unlike the three above. Phase 19 made the
        # knobs the eval sweeps switchable; this one is a setting until the
        # D-096 verdict says what its default should be.
        temporal=settings.temporal_enabled,
        # Not switchable per request either, and for a stronger reason: D-100
        # measured it twice and did not ship it on, so a dropdown offering it
        # would hand someone a configuration the verdict argues against.
        max_per_article=settings.max_per_article,
    )


def configured_generation_service(
    *, hybrid: bool, reranker: str | None, model: str
) -> GenerationService:
    """An answer path configured for one request."""
    return GenerationService(
        configured_search_service(hybrid=hybrid, reranker=reranker),
        get_generator(model),
        verifier=get_verifier(),
        rewriter=get_rewriter(),
    )
