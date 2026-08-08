"""Tests for the FastAPI application.

No server is started and no port is bound. TestClient calls the app directly
as the ASGI callable it is.

/search is tested against a stub service rather than the real one: what is
being checked here is the HTTP layer -- validation, status codes, the response
shape -- not retrieval, which has its own tests.
"""

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from eurohistory_rag.api.dependencies import (
    get_generation_service,
    get_search_service,
    get_vector_store,
)
from eurohistory_rag.api.main import create_app
from eurohistory_rag.generation.service import GenerationService
from eurohistory_rag.retrieval.search import SearchResult
from eurohistory_rag.retrieval.vectorstore import VectorStoreUnavailable
from tests.fakes import FakeGenerator, UnavailableGenerator

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


class UnavailableSearchService:
    """Stands in for a search whose vector store is down."""

    def search(
        self,
        question: str,
        k: int | None = None,
        min_score: float | None = None,
    ) -> list[SearchResult]:
        raise VectorStoreUnavailable("connection refused")


class StubStore:
    """Stands in for the vector store in readiness checks."""

    def __init__(self, ready: bool) -> None:
        self._ready = ready

    def is_ready(self) -> bool:
        return self._ready


@pytest.fixture
def stub() -> StubSearchService:
    return StubSearchService([result("30030:1:0"), result("30030:1:1")])


def client_with_store(*, ready: bool) -> TestClient:
    """A client whose /ready sees a store in the given state."""
    app = create_app()
    app.dependency_overrides[get_vector_store] = lambda: StubStore(ready)
    return TestClient(app)


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
    assert "/ready" in schema["paths"]
    assert "/search" in schema["paths"]


# --- readiness --------------------------------------------------------------


def test_ready_answers_200_when_the_store_is_reachable() -> None:
    response = client_with_store(ready=True).get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_ready_answers_503_when_the_store_is_not() -> None:
    """503 rather than 500: the process is fine, its dependency is not."""
    assert client_with_store(ready=False).get("/ready").status_code == 503


def test_health_still_answers_ok_when_the_store_is_down() -> None:
    """Not a bug. Liveness and readiness are different questions, and a
    restarter that conflates them keeps restarting a healthy process.
    """
    response = client_with_store(ready=False).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


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


# --- the store being down ---------------------------------------------------


def test_search_answers_503_when_the_store_is_unreachable() -> None:
    """A stack trace tells the caller nothing they can act on."""
    app = create_app()
    app.dependency_overrides[get_search_service] = UnavailableSearchService
    with TestClient(app) as unavailable_client:
        response = unavailable_client.get("/search", params={"q": "aid"})

    assert response.status_code == 503
    assert response.json()["detail"] == "Search is temporarily unavailable."


# --- asking -----------------------------------------------------------------


def asking_client(answer: str) -> TestClient:
    """A client whose /ask is wired to a stub search and a canned answer."""
    app = create_app()
    search = StubSearchService([result("30030:1:0"), result("30030:1:1")])
    generator = FakeGenerator(answer=answer)
    app.dependency_overrides[get_generation_service] = lambda: GenerationService(
        search,  # type: ignore[arg-type]
        generator,
    )
    return TestClient(app)


def test_ask_returns_the_answer_and_the_model_that_wrote_it() -> None:
    response = asking_client("The programme distributed $13.3 billion [1].").post(
        "/ask", json={"question": "how much was the Marshall Plan?"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["question"] == "how much was the Marshall Plan?"
    assert body["answer"] == "The programme distributed $13.3 billion [1]."
    assert body["model"] == "fake-model"


def test_a_source_carries_the_number_the_answer_cites() -> None:
    """`n` is what turns a [1] in the text into a link in a client."""
    body = asking_client("Aid arrived [2].").post("/ask", json={"question": "?"}).json()

    assert [source["n"] for source in body["sources"]] == [2]
    assert body["sources"][0]["url"] == (
        "https://en.wikipedia.org/w/index.php?oldid=30130"
    )


def test_only_cited_sources_are_returned() -> None:
    """Two chunks were retrieved and one was used."""
    body = asking_client("Only one [1].").post("/ask", json={"question": "?"}).json()

    assert len(body["sources"]) == 1


def test_a_refusal_returns_no_sources() -> None:
    """The honest answer to an unanswerable question, and the empty list is
    itself the signal that nothing was used.
    """
    body = (
        asking_client("Not in the sources. The passages cover the Marshall Plan.")
        .post("/ask", json={"question": "how does a transformer work?"})
        .json()
    )

    assert body["answer"].startswith("Not in the sources.")
    assert body["sources"] == []


def test_the_licence_is_stated_on_every_answer() -> None:
    body = asking_client("Aid arrived [1].").post("/ask", json={"question": "?"}).json()

    assert body["license"] == "CC BY-SA 4.0"


def test_a_missing_question_is_rejected_by_ask() -> None:
    assert asking_client("x").post("/ask", json={}).status_code == 422


def test_an_empty_question_is_rejected_by_ask() -> None:
    assert asking_client("x").post("/ask", json={"question": ""}).status_code == 422


def test_a_k_above_the_ceiling_is_rejected_by_ask() -> None:
    response = asking_client("x").post("/ask", json={"question": "a", "k": 999})

    assert response.status_code == 422


def test_ask_answers_503_when_the_model_is_unreachable() -> None:
    """Qdrant down and OpenAI down are the same event to a caller: try later."""
    app = create_app()
    app.dependency_overrides[get_generation_service] = lambda: GenerationService(
        StubSearchService([result("30030:1:0")]),  # type: ignore[arg-type]
        UnavailableGenerator(),
    )
    with TestClient(app) as unavailable_client:
        response = unavailable_client.post("/ask", json={"question": "aid"})

    assert response.status_code == 503
    assert response.json()["detail"] == "Answering is temporarily unavailable."


def test_ask_answers_503_when_the_store_is_unreachable() -> None:
    app = create_app()
    app.dependency_overrides[get_generation_service] = lambda: GenerationService(
        UnavailableSearchService(),  # type: ignore[arg-type]
        FakeGenerator(),
    )
    with TestClient(app) as unavailable_client:
        response = unavailable_client.post("/ask", json={"question": "aid"})

    assert response.status_code == 503


# --- per-request configuration (Phase 19, D-092) -----------------------------


def test_an_answer_states_the_configuration_that_produced_it() -> None:
    """Every answer, not only overridden ones.

    Phase 8 shipped a measurement whose reranker was switched off and nobody
    noticed. An answer that cannot say what produced it is that same failure,
    in front of a person instead of in a run directory.
    """
    body = (
        asking_client("Aid arrived [1].").post("/ask", json={"question": "aid"}).json()
    )

    assert body["configuration"]["model"] == "fake-model"
    assert body["configuration"]["k"] == 5
    assert "hybrid" in body["configuration"]
    assert "reranker" in body["configuration"]


def test_a_request_naming_nothing_uses_the_injected_service() -> None:
    """The property the whole design rests on.

    With no override the endpoint must use the service FastAPI injected, which
    is what `dependency_overrides` replaces -- otherwise every test in this file
    would start calling OpenAI.
    """
    response = asking_client("Aid arrived [1].").post("/ask", json={"question": "aid"})

    assert response.status_code == 200
    assert response.json()["answer"] == "Aid arrived [1]."


def test_an_unknown_model_is_refused_before_anything_is_spent() -> None:
    """The allow-list is the server's, not the page's.

    `model` arrives from a browser. A name passed through unchecked is a way to
    bill this account for whatever someone types.
    """
    response = asking_client("x").post(
        "/ask", json={"question": "aid", "model": "gpt-9-omniscient"}
    )

    assert response.status_code == 422
    assert "gpt-9-omniscient" in response.json()["detail"]


def test_an_unknown_reranker_is_refused() -> None:
    """Same argument: a name reaching HuggingFace unchecked reads 500 MB."""
    response = asking_client("x").post(
        "/ask", json={"question": "aid", "reranker": "evil/model"}
    )

    assert response.status_code == 422


def test_options_reports_the_allow_lists_and_the_defaults() -> None:
    """What the page reads instead of hardcoding a list of models."""
    body = TestClient(create_app()).get("/options").json()

    assert "gpt-4.1-mini" in body["models"]
    assert "BAAI/bge-reranker-base" in body["rerankers"]
    assert body["defaults"]["k"] == 5
    assert body["max_k"] == 50


# --- streaming (Phase 21, D-095) ---------------------------------------------


def events(body: str) -> list[tuple[str, Any]]:
    """A server-sent event stream parsed back into (name, payload) pairs."""
    parsed: list[tuple[str, Any]] = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        parsed.append((lines["event"], json.loads(lines["data"])))
    return parsed


def stream_ask(client: TestClient, question: str = "aid") -> list[tuple[str, Any]]:
    """Ask for the streamed shape of the same endpoint."""
    response = client.post(
        "/ask", json={"question": question}, headers={"Accept": "text/event-stream"}
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    return events(response.text)


def test_the_same_url_still_answers_json_when_nothing_asks_for_a_stream() -> None:
    """The header is the only difference, and the default is unchanged."""
    response = asking_client("Aid arrived [1].").post("/ask", json={"question": "?"})

    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["answer"] == "Aid arrived [1]."


def test_the_sources_are_the_first_event_and_arrive_before_any_text() -> None:
    """They are known when retrieval finishes, which is the whole early win."""
    parsed = stream_ask(asking_client("Aid arrived [1]."))

    assert parsed[0][0] == "sources"
    assert [hit["chunk_id"] for hit in parsed[0][1]] == ["30030:1:0", "30030:1:1"]


def test_the_tokens_join_back_into_exactly_the_json_answer() -> None:
    """The two shapes must not be able to disagree about what was said."""
    answer = "The programme distributed $13.3 billion [1]."
    parsed = stream_ask(asking_client(answer))

    tokens = "".join(str(data) for name, data in parsed if name == "token")
    assert tokens == answer
    assert len([name for name, _ in parsed if name == "token"]) > 1


def test_the_last_event_carries_the_citations_and_the_configuration() -> None:
    """A marker only becomes a citation once the sentence holding it exists."""
    parsed = stream_ask(asking_client("Aid arrived [2]."))

    name, done = parsed[-1]
    assert name == "done"
    assert [source["n"] for source in done["sources"]] == [2]
    assert done["configuration"]["k"] == 5


def test_a_model_that_dies_mid_stream_becomes_an_error_event_not_a_500() -> None:
    """The 200 was sent at byte zero and cannot be taken back.

    So the failure has to travel in-band, and the page is what makes it look
    like a failure. A stream that simply stopped would read as a short answer.
    """
    app = create_app()
    app.dependency_overrides[get_generation_service] = lambda: GenerationService(
        StubSearchService([result("30030:1:0")]),  # type: ignore[arg-type]
        UnavailableGenerator(),
    )
    with TestClient(app) as unavailable_client:
        parsed = stream_ask(unavailable_client)

    assert [name for name, _ in parsed] == ["sources", "error"]


def test_a_dead_store_is_still_a_real_503_even_when_a_stream_was_asked_for() -> None:
    """Retrieval runs before the response begins, so this failure keeps a code."""
    app = create_app()
    app.dependency_overrides[get_generation_service] = lambda: GenerationService(
        UnavailableSearchService(),  # type: ignore[arg-type]
        FakeGenerator(),
    )
    with TestClient(app) as unavailable_client:
        response = unavailable_client.post(
            "/ask",
            json={"question": "aid"},
            headers={"Accept": "text/event-stream"},
        )

    assert response.status_code == 503
