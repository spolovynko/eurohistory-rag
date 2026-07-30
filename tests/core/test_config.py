"""Tests for Settings.

These must not depend on the developer's own .env file. A test that passes on
one machine and fails on a clean checkout is not a test, so every case here
either passes values explicitly or controls the environment with monkeypatch.
"""

from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from eurohistory_rag.core.config import Settings, get_settings


def test_default_applies_when_value_is_absent() -> None:
    """qdrant_url falls through to its default when nothing supplies it."""
    settings = Settings(
        openai_api_key=SecretStr("test-key"),
        wikipedia_user_agent="test-agent",
    )

    assert settings.qdrant_url == "http://localhost:6333"


def test_api_key_is_not_exposed_by_repr() -> None:
    """SecretStr masks the value in every string rendering.

    This is the reason for the type: Pydantic prints field values in
    ValidationError messages and tracebacks, so a plain str would put the key
    in a log file the first time something failed.
    """
    settings = Settings(
        openai_api_key=SecretStr("sk-should-never-be-printed"),
        wikipedia_user_agent="test-agent",
    )

    assert "sk-should-never-be-printed" not in repr(settings)
    assert settings.openai_api_key.get_secret_value() == "sk-should-never-be-printed"


def test_missing_required_field_fails_at_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A required field with no source raises rather than defaulting.

    chdir into an empty directory because env_file=".env" is resolved relative
    to the current working directory -- moving away from the repo root is what
    makes the real .env invisible to this test.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("WIKIPEDIA_USER_AGENT", raising=False)

    with pytest.raises(ValidationError) as error:
        Settings()  # type: ignore[call-arg]

    assert "openai_api_key" in str(error.value)


def test_environment_variable_beats_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real environment variables sit above field defaults in the source order."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("WIKIPEDIA_USER_AGENT", "test-agent")
    monkeypatch.setenv("QDRANT_URL", "http://qdrant.example:6333")

    settings = Settings()  # type: ignore[call-arg]

    assert settings.qdrant_url == "http://qdrant.example:6333"


def test_get_settings_returns_one_instance_per_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """lru_cache means the second call is a lookup, not a second .env read."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("WIKIPEDIA_USER_AGENT", "test-agent")
    get_settings.cache_clear()

    try:
        assert get_settings() is get_settings()
    finally:
        get_settings.cache_clear()
