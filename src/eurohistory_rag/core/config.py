"""Typed application configuration, loaded from the environment and .env."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Wikipedia's licence, not a choice. Stated once here rather than stored on
# 30,362 identical payloads; the API repeats it with every response.
CORPUS_LICENSE = "CC BY-SA 4.0"


class Settings(BaseSettings):
    """Application configuration, validated at construction.

    Sources, highest priority first: constructor arguments, real environment
    variables, the .env file, field defaults. A required field that reaches the
    end of that list raises ValidationError immediately, so a missing key fails
    at startup rather than halfway through a run.

    Extra keys in .env are rejected (pydantic-settings defaults to
    extra='forbid'), so .env.example and these fields must be kept in step.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Required: no safe default exists for either.
    openai_api_key: SecretStr
    wikipedia_user_agent: str

    # Defaulted: correct locally, overridden by the environment in deployment.
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "chunks"

    # The embedding model and its output size must move together: the Qdrant
    # collection is created with this size, and a mismatch is only caught when
    # the first vector is written.
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536

    # D-052 chose gpt-4.1-mini and reversed gpt-5-mini. The default has to match
    # the decision: a machine without this key in .env runs the rejected model.
    generation_model: str = "gpt-4.1-mini"

    # The reranker runs locally, so there is no key to hold. Named here rather
    # than in code because swapping it is an experiment, not a code change --
    # and it is a per-machine concern: a laptop may want the smaller model.
    reranker_model: str = "BAAI/bge-reranker-base"

    # Off by default so the system's behaviour does not change until the eval
    # says it should. Phase 8 turns it on in .env, measures, and then decides.
    reranker_enabled: bool = False

    # Hybrid search: BM25 keyword results fused with the dense ones. Off by
    # default for the same reason as the reranker -- with it off the system
    # behaves exactly as the Phase 8 run did, so a forgotten flag cannot
    # quietly contaminate the comparison. Phase 9, D-074.
    hybrid_enabled: bool = False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the one Settings instance for this process.

    Cached, so .env is read and validated once rather than on every call.
    Constructed lazily on first call, so importing this module never requires
    a valid environment.
    """
    # Values come from the environment; mypy sees only the synthesised
    # dataclass-style __init__ and cannot know that.
    return Settings()  # type: ignore[call-arg]
