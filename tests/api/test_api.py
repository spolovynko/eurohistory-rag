"""Tests for the FastAPI application.

No server is started and no port is bound. TestClient calls the app directly
as the ASGI callable it is.
"""

from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient) -> None:
    """/health answers 200 with the documented body."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_schema_describes_health(client: TestClient) -> None:
    """The schema is generated from the handler's annotations, not written by hand.

    Guards against the route being renamed or the app metadata drifting away
    from the package version.
    """
    schema = client.get("/openapi.json").json()

    assert schema["info"]["version"] == "0.1.0"
    assert "/health" in schema["paths"]
