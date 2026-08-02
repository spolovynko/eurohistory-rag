"""Tests for the FastAPI application.

No server is started and no port is bound. TestClient calls the app directly
as the ASGI callable it is.

/search is tested against a stub service rather than the real one: what is
being checked here is the HTTP layer -- validation, status codes, the response
shape -- not retrieval, which has its own tests.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from eurohistory_rag.api.dependencies import get_search_service
from eurohistory_rag.api.main import create_app
from eurohistory_rag.retrieval.search import SearchResult

# --- helpers ----------------------------------------------------------------


def result(
    chunk_id: str, heading: str = "Origins", score: float = 0.58
) -> SearchResult:
    return SearchResult(
        chunk_id=chunk_id,
        doc_id="30030:1",
        page_id=30030,
        title="Marshall Plan",
        heading=heading,
        text="The programme distributed $13.3 billion over four years.",
        score=score,
        revision_id=30130,
    )


class StubSearchService:
    """Answers with a fixed list and records what it was asked."""

    def __init__(self, results: list[SearchResult]) -> None:
        self._results = results
        self.questions: list[tuple[str, int | None]] = []

    def search(
        self,
        question: str,
        k: int | None = None,
        min_score: float | None = None,
    ) -> list[SearchResult]:
        self.questions.append((question, k))
        return self._results[: k or len(self._results)]


@pytest.fixture
def stub() -> StubSearchService:
    return StubSearchService([result("30030:1:0"), result("30030:1:1")])


@pytest.fixture
def searching_client(stub: StubSearchService) -> Iterator[TestClient]:
    """A client whose /search is wired to the stub instead of OpenAI and Qdrant.

    `dependency_overrides` is FastAPI's seam: the endpoint asked for whatever
    `get_search_service` returns, so replacing that function replaces the whole
    retrieval stack for this app only.
    """
    app = create_app()
    app.dependency_overrides[get_search_service] = lambda: stub
    with TestClient(app) as test_client:
        yield test_client


# --- health -----------------------------------------------------------------


def test_health_returns_ok(client: TestClient) -> None:
    """/health answers 200 with the documented body."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_schema_describes_both_routes(client: TestClient) -> None:
    """The schema is generated from the handlers' annotations, not written by hand.

    Guards against a route being renamed or the app metadata drifting away from
    the package version.
    """
    schema = client.get("/openapi.json").json()

    assert schema["info"]["version"] == "0.1.0"
    assert "/health" in schema["paths"]
    assert "/search" in schema["paths"]


# --- searching --------------------------------------------------------------


def test_search_returns_results_with_their_scores(
    searching_client: TestClient,
) -> None:
    response = searching_client.get("/search", params={"q": "Marshall Plan"})

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "Marshall Plan"
    assert body["count"] == 2
    assert body["results"][0]["score"] == 0.58


def test_a_result_carries_its_citation(searching_client: TestClient) -> None:
    """`source` and `url` are sent ready-made so a client never builds them."""
    hit = searching_client.get("/search", params={"q": "aid"}).json()["results"][0]

    assert hit["source"] == "Marshall Plan — Origins"
    assert hit["url"] == "https://en.wikipedia.org/w/index.php?oldid=30130"


def test_the_licence_is_stated_on_every_response(
    searching_client: TestClient,
) -> None:
    """CC BY-SA requires attribution, and it is not stored per point."""
    body = searching_client.get("/search", params={"q": "aid"}).json()

    assert body["license"] == "CC BY-SA 4.0"


def test_k_is_passed_through_to_the_service(
    searching_client: TestClient, stub: StubSearchService
) -> None:
    searching_client.get("/search", params={"q": "aid", "k": 1})

    assert stub.questions == [("aid", 1)]


def test_k_defaults_when_it_is_not_given(
    searching_client: TestClient, stub: StubSearchService
) -> None:
    searching_client.get("/search", params={"q": "aid"})

    assert stub.questions == [("aid", 5)]


def test_count_reports_what_came_back_not_what_was_asked_for(
    searching_client: TestClient,
) -> None:
    """Thinning can return fewer than k, and the response must say so."""
    body = searching_client.get("/search", params={"q": "aid", "k": 5}).json()

    assert body["k"] == 5
    assert body["count"] == 2


# --- rejected input ---------------------------------------------------------


def test_a_missing_question_is_rejected(searching_client: TestClient) -> None:
    assert searching_client.get("/search").status_code == 422


def test_an_empty_question_is_rejected(searching_client: TestClient) -> None:
    assert searching_client.get("/search", params={"q": ""}).status_code == 422


def test_a_k_above_the_ceiling_is_rejected(searching_client: TestClient) -> None:
    """One request must not be able to ask for the whole corpus."""
    assert (
        searching_client.get("/search", params={"q": "a", "k": 999}).status_code == 422
    )


def test_a_k_below_one_is_rejected(searching_client: TestClient) -> None:
    assert searching_client.get("/search", params={"q": "a", "k": 0}).status_code == 422


def test_bad_input_never_reaches_the_service(
    searching_client: TestClient, stub: StubSearchService
) -> None:
    """Validation happens from the annotations, before the handler body runs."""
    searching_client.get("/search", params={"q": "a", "k": 999})

    assert stub.questions == []
