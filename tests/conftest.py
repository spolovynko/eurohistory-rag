"""Fixtures shared by every test module.

pytest imports this file automatically -- it is never imported by name. Any
fixture defined here is available to tests in this directory and below.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient


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
