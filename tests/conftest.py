"""Fixtures shared by every test module.

pytest imports this file automatically -- it is never imported by name. Any
fixture defined here is available to tests in this directory and below.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from eurohistory_rag.core.config import get_settings


@pytest.fixture(autouse=True)
def stub_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Give every test the two required settings, from nowhere real.

    `Settings` requires an API key and a user agent, and `.env` is the only
    place a developer's machine has them. Twelve tests reached `get_settings()`
    through an endpoint and therefore passed by reading the real key off disk --
    so they failed on CI, which has no `.env`, and they were reading a live
    secret on the machines where they passed. Both halves are fixed here.

    The cache is cleared on the way in and out because it is process-wide: one
    test that built Settings from its own environment would otherwise hand that
    instance to every test after it.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    monkeypatch.setenv("WIKIPEDIA_USER_AGENT", "eurohistory-rag-tests")
    # Phase 25 loads the reranker in the app's lifespan, and `TestClient` runs
    # the lifespan. Left on, every test using the `client` fixture would read 88
    # MB off disk on this machine -- and download it on one that has never run
    # the reranker. The suite must pass with Docker stopped and nothing
    # fetched, so the warm-up is off here and tested explicitly instead. D-099.
    monkeypatch.setenv("WARM_START", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A client wired to a freshly built app, with no server running.

    create_app() rather than the module-level `app`, so each test gets its own
    application object and nothing leaks between tests.

    The `with` block matters: entering it runs the app's ASGI lifespan startup
    and leaving it runs shutdown. Without it, code registered on startup never
    runs and the test diverges from production.
    """
    from eurohistory_rag.api.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client
