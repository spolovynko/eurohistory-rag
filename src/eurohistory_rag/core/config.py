"""Typed application configuration, loaded from the environment and .env."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


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
