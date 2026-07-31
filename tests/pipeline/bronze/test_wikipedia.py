"""The MediaWiki client, driven by a fake network.

httpx.MockTransport answers requests in-process, so every case here -- including
a 503, which Wikipedia will not produce on request -- runs with no network and
no waiting.
"""

import time
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from eurohistory_rag.pipeline.bronze import wikipedia
from eurohistory_rag.pipeline.bronze.wikipedia import (
    MAX_TITLES_PER_REQUEST,
    WikipediaClient,
    WikipediaError,
)


def page(pageid: int, title: str, content: str = "wikitext") -> dict[str, Any]:
    return {
        "pageid": pageid,
        "ns": 0,
        "title": title,
        "revisions": [
            {
                "revid": pageid * 10,
                "parentid": pageid * 10 - 1,
                "timestamp": "2026-01-02T03:04:05Z",
                "slots": {
                    "main": {
                        "contentmodel": "wikitext",
                        "contentformat": "text/x-wiki",
                        "content": content,
                    }
                },
            }
        ],
    }


def client_returning(*responses: httpx.Response, **kwargs: Any) -> WikipediaClient:
    """A client whose next N requests get these canned responses, in order."""
    remaining = iter(responses)

    def handler(_: httpx.Request) -> httpx.Response:
        return next(remaining)

    return WikipediaClient(
        "test/1.0 (test@example.com)",
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


def ok(query: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json={"batchcomplete": True, "query": query})


# --- construction ----------------------------------------------------------


@pytest.mark.parametrize("agent", ["", "   "])
def test_empty_user_agent_is_rejected(agent: str) -> None:
    """Wikimedia policy requires a contact address; a default would look fine."""
    with pytest.raises(ValueError, match="user_agent"):
        WikipediaClient(agent)


def test_user_agent_is_sent_on_every_request() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["User-Agent"])
        return ok({"pages": [page(1, "Stalinism")]})

    client = WikipediaClient(
        "eurohistory-rag/0.1 (me@example.com)",
        transport=httpx.MockTransport(handler),
    )
    client.fetch_batch(["Stalinism"])

    assert seen == ["eurohistory-rag/0.1 (me@example.com)"]


# --- batching guards -------------------------------------------------------


def test_empty_title_list_makes_no_request() -> None:
    def handler(_: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("should not have been called")

    client = WikipediaClient("test/1.0", transport=httpx.MockTransport(handler))

    assert client.fetch_batch([]) == wikipedia.FetchResult(revisions=(), missing=())


def test_more_than_fifty_titles_is_rejected() -> None:
    """The API truncates silently over 50, which would lose articles unnoticed."""
    client = client_returning()

    with pytest.raises(ValueError, match="exceeds the API limit"):
        client.fetch_batch([f"T{i}" for i in range(MAX_TITLES_PER_REQUEST + 1)])


# --- parsing ---------------------------------------------------------------


def test_a_page_becomes_a_revision() -> None:
    client = client_returning(ok({"pages": [page(28621, "Stalinism", "{{Infobox}}")]}))

    result = client.fetch_batch(["Stalinism"])

    (revision,) = result.revisions
    assert revision.page_id == 28621
    assert revision.title == "Stalinism"
    assert revision.requested_title == "Stalinism"
    assert revision.revision_id == 286210
    assert revision.wikitext == "{{Infobox}}"
    assert revision.revision_timestamp == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def test_a_page_with_no_id_is_reported_missing() -> None:
    client = client_returning(
        ok({"pages": [{"ns": 0, "title": "Nonexistent", "missing": True}]})
    )

    result = client.fetch_batch(["Nonexistent"])

    assert result.revisions == ()
    assert result.missing == ("Nonexistent",)


def test_a_page_with_no_wikitext_slot_is_reported_missing() -> None:
    """Exists, but its main slot holds something other than wikitext."""
    client = client_returning(
        ok({"pages": [{"pageid": 1, "ns": 0, "title": "Odd", "revisions": []}]})
    )

    assert client.fetch_batch(["Odd"]).missing == ("Odd",)


def test_unknown_response_fields_are_ignored() -> None:
    """Wikimedia's format, so a field they add later must not break the client."""
    body = ok({"pages": [page(1, "Stalinism")]}).json()
    body["query"]["pages"][0]["somethingNew"] = {"nested": True}
    body["newTopLevelKey"] = 1

    client = client_returning(httpx.Response(200, json=body))

    assert client.fetch_batch(["Stalinism"]).revisions[0].page_id == 1


# --- title mapping ---------------------------------------------------------


def test_a_redirect_is_mapped_back_to_the_requested_title() -> None:
    client = client_returning(
        ok(
            {
                "redirects": [{"from": "Great War", "to": "World War I"}],
                "pages": [page(4764461, "World War I")],
            }
        )
    )

    (revision,) = client.fetch_batch(["Great War"]).revisions

    assert revision.title == "World War I"
    assert revision.requested_title == "Great War"


def test_normalisation_then_redirect_chains() -> None:
    """MediaWiki capitalises only the first letter, so a redirect fixes the rest."""
    client = client_returning(
        ok(
            {
                "normalized": [{"from": "treaty_of_rome", "to": "Treaty of rome"}],
                "redirects": [{"from": "Treaty of rome", "to": "Treaty of Rome"}],
                "pages": [page(78006, "Treaty of Rome")],
            }
        )
    )

    (revision,) = client.fetch_batch(["treaty_of_rome"]).revisions

    assert revision.requested_title == "treaty_of_rome"


def test_a_redirect_loop_does_not_hang() -> None:
    """Redirect cycles exist on the wiki; without the `seen` set this never ends."""
    client = client_returning(
        ok(
            {
                "redirects": [{"from": "A", "to": "B"}, {"from": "B", "to": "A"}],
                "pages": [page(1, "A")],
            }
        )
    )

    assert client.fetch_batch(["A"]).revisions[0].requested_title == "A"


def test_results_are_matched_by_title_not_position() -> None:
    """The API returns pages in its own order, not the order requested."""
    client = client_returning(
        ok(
            {
                "redirects": [{"from": "Great War", "to": "World War I"}],
                "pages": [
                    {"ns": 0, "title": "Nope", "missing": True},
                    page(2, "Stalinism"),
                    page(1, "World War I"),
                ],
            }
        )
    )

    result = client.fetch_batch(["Great War", "Nope", "Stalinism"])

    by_requested = {r.requested_title: r.title for r in result.revisions}
    assert by_requested == {"Great War": "World War I", "Stalinism": "Stalinism"}
    assert result.missing == ("Nope",)


# --- retries ---------------------------------------------------------------


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Record backoff delays instead of waiting for them."""
    delays: list[float] = []
    monkeypatch.setattr(time, "sleep", delays.append)
    return delays


@pytest.mark.parametrize("status", sorted(wikipedia.RETRY_STATUS_CODES))
def test_transient_statuses_are_retried(no_sleep: list[float], status: int) -> None:
    client = client_returning(
        httpx.Response(status), ok({"pages": [page(1, "Stalinism")]})
    )

    assert client.fetch_batch(["Stalinism"]).revisions[0].page_id == 1
    assert no_sleep == [1.0]


def test_backoff_doubles(no_sleep: list[float]) -> None:
    client = client_returning(
        httpx.Response(503),
        httpx.Response(503),
        httpx.Response(503),
        ok({"pages": [page(1, "Stalinism")]}),
    )

    client.fetch_batch(["Stalinism"])

    assert no_sleep == [1.0, 2.0, 4.0]


def test_retry_after_header_overrides_the_backoff(no_sleep: list[float]) -> None:
    """The server knows its own rate-limit window better than we can guess."""
    client = client_returning(
        httpx.Response(429, headers={"Retry-After": "7"}),
        ok({"pages": [page(1, "Stalinism")]}),
    )

    client.fetch_batch(["Stalinism"])

    assert no_sleep == [7.0]


def test_a_retry_after_date_falls_back_to_our_backoff(no_sleep: list[float]) -> None:
    client = client_returning(
        httpx.Response(429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}),
        ok({"pages": [page(1, "Stalinism")]}),
    )

    client.fetch_batch(["Stalinism"])

    assert no_sleep == [1.0]


def test_running_out_of_retries_raises(no_sleep: list[float]) -> None:
    client = client_returning(*[httpx.Response(503)] * 3, max_retries=2)

    with pytest.raises(WikipediaError, match="gave up after 3 attempts"):
        client.fetch_batch(["Stalinism"])

    assert no_sleep == [1.0, 2.0]


def test_a_client_error_is_not_retried(no_sleep: list[float]) -> None:
    """A 404 will fail identically forever; retrying it just wastes bandwidth."""
    client = client_returning(httpx.Response(404, text="no such module"))

    with pytest.raises(WikipediaError, match="HTTP 404"):
        client.fetch_batch(["Stalinism"])

    assert no_sleep == []


def test_a_dropped_connection_is_retried(no_sleep: list[float]) -> None:
    attempts: list[int] = []

    def handler(_: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) < 3:
            raise httpx.ConnectError("connection reset by peer")
        return ok({"pages": [page(1, "Stalinism")]})

    client = WikipediaClient("test/1.0", transport=httpx.MockTransport(handler))

    assert client.fetch_batch(["Stalinism"]).revisions[0].page_id == 1
    assert no_sleep == [1.0, 2.0]


# --- the Protocol ----------------------------------------------------------


def test_the_client_satisfies_revisionsource() -> None:
    """Structural, not nominal: no inheritance, no registration."""

    def titles_from(source: wikipedia.RevisionSource) -> Sequence[str]:
        return [r.title for r in source.fetch_batch(["Stalinism"]).revisions]

    assert titles_from(client_returning(ok({"pages": [page(1, "Stalinism")]}))) == [
        "Stalinism"
    ]


def test_close_is_idempotent() -> None:
    client = client_returning()

    client.close()
    client.close()
