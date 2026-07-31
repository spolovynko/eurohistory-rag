"""Read-only client for the MediaWiki API on English Wikipedia.

Synchronous and one request at a time: 1,000 articles at 50 per request is 20
requests, so there is nothing to gain from concurrency and a serial client is
far easier to make resumable.

Returns raw wikitext plus provenance and makes no cleaning decisions of its own
-- that is Silver's job. See D-006.
"""

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import httpx
from pydantic import BaseModel, Field

API_URL = "https://en.wikipedia.org/w/api.php"

# The API caps `titles` at 50 per request for clients without the apihighlimits
# right. Over that it silently truncates rather than erroring, so we check.
MAX_TITLES_PER_REQUEST = 50

# Worth retrying: rate limiting, and the transient server-side failures. A 400
# or a 404 is a bug in the request, and retrying it just wastes bandwidth.
RETRY_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


class WikipediaError(RuntimeError):
    """A request failed in a way retrying will not fix, or ran out of retries."""


# --- the wire format -------------------------------------------------------
#
# Private models mirroring the API's JSON. They exist so an unexpected response
# shape becomes a ValidationError naming the field, rather than a KeyError forty
# lines later. Extra keys are ignored by default and that is deliberate: this is
# Wikimedia's format, not ours, and they add fields without asking.


class _Slot(BaseModel):
    content: str


class _WireRevision(BaseModel):
    revid: int
    timestamp: datetime
    slots: dict[str, _Slot] = Field(default_factory=dict)


class _Page(BaseModel):
    title: str
    # Absent for deleted, never-existed and malformed titles alike.
    pageid: int | None = None
    revisions: list[_WireRevision] = Field(default_factory=list)


class _TitleMapping(BaseModel):
    # `from` is a Python keyword, so the field is renamed and aliased back.
    from_: str = Field(alias="from")
    to: str


class _Query(BaseModel):
    pages: list[_Page] = Field(default_factory=list)
    normalized: list[_TitleMapping] = Field(default_factory=list)
    redirects: list[_TitleMapping] = Field(default_factory=list)


class _WireResponse(BaseModel):
    query: _Query = Field(default_factory=_Query)


# --- what callers get ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Revision:
    """One article revision, exactly as fetched.

    `title` is what Wikipedia calls the page now; `requested_title` is what the
    registry asked for. They differ when the registry entry was a redirect or
    was spelled with underscores. Both are kept because only `page_id` is a
    stable identity -- titles get renamed, ids do not.
    """

    page_id: int
    title: str
    requested_title: str
    revision_id: int
    revision_timestamp: datetime
    wikitext: str


@dataclass(frozen=True, slots=True)
class FetchResult:
    """The outcome of one batch request.

    `missing` holds requested titles the API returned no wikitext for: deleted
    pages, never-existed pages, and titles Wikipedia rejects as malformed. All
    three mean the same thing to a caller -- there is nothing to store.
    """

    revisions: tuple[Revision, ...]
    missing: tuple[str, ...]


def _map_final_to_requested(
    requested: Sequence[str],
    normalized: Mapping[str, str],
    redirects: Mapping[str, str],
) -> dict[str, str]:
    """Map each returned page title back to the title that was asked for.

    The API rewrites titles twice and reports both as from/to pairs:
    `normalized` fixes underscores and the leading letter, `redirects` follows
    redirect pages. A redirect can point at another redirect, so each requested
    title is walked forward until it stops moving. `seen` is there because a
    redirect loop on the wiki would otherwise hang this function.

    Known limitation: if two requested titles resolve to the same article, the
    later one wins and the earlier is reported under the wrong name. Bronze
    deduplicates on page_id, which is why page_id is the primary key.
    """
    final_to_requested: dict[str, str] = {}
    for title in requested:
        current = normalized.get(title, title)
        seen = {current}
        while (target := redirects.get(current)) is not None and target not in seen:
            current = target
            seen.add(current)
        final_to_requested[current] = title
    return final_to_requested


def _parse_retry_after(value: str | None) -> float | None:
    """Seconds from a Retry-After header, or None if absent or an HTTP date.

    The header may legally be a date rather than a number. Wikimedia does not
    send that form here, so it falls through to our own backoff instead.
    """
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


class WikipediaClient:
    """Fetches raw wikitext. One method call, one HTTP request.

    Holds an httpx.Client so the TCP and TLS handshake is paid once and the
    connection is reused across batches. Use it as a context manager, or call
    close(), so the socket is released.
    """

    def __init__(
        self,
        user_agent: str,
        *,
        timeout: float = 30.0,
        max_retries: int = 4,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not user_agent.strip():
            raise ValueError("user_agent is required by Wikimedia policy")
        self._max_retries = max_retries
        self._client = httpx.Client(
            headers={"User-Agent": user_agent},
            timeout=timeout,
            transport=transport,
        )

    def __enter__(self) -> "WikipediaClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        """Release the connection pool."""
        self._client.close()

    def fetch_batch(self, titles: Sequence[str]) -> FetchResult:
        """Fetch wikitext for up to MAX_TITLES_PER_REQUEST titles."""
        if not titles:
            return FetchResult(revisions=(), missing=())
        if len(titles) > MAX_TITLES_PER_REQUEST:
            raise ValueError(
                f"{len(titles)} titles exceeds the API limit of "
                f"{MAX_TITLES_PER_REQUEST}; batch before calling"
            )

        payload = self._get(
            {
                "action": "query",
                "prop": "revisions",
                "rvslots": "main",
                "rvprop": "content|ids|timestamp",
                "titles": "|".join(titles),
                # Follow redirects: a registry entry that has since become a
                # redirect should still yield the article it points at.
                "redirects": "1",
                "format": "json",
                # formatversion 2 gives `pages` as a list and real booleans.
                "formatversion": "2",
            }
        )

        final_to_requested = _map_final_to_requested(
            titles,
            {m.from_: m.to for m in payload.query.normalized},
            {m.from_: m.to for m in payload.query.redirects},
        )

        revisions: list[Revision] = []
        missing: list[str] = []

        for page in payload.query.pages:
            requested = final_to_requested.get(page.title, page.title)
            revision = page.revisions[0] if page.revisions else None
            slot = revision.slots.get("main") if revision is not None else None

            if page.pageid is None or revision is None or slot is None:
                missing.append(requested)
            else:
                revisions.append(
                    Revision(
                        page_id=page.pageid,
                        title=page.title,
                        requested_title=requested,
                        revision_id=revision.revid,
                        revision_timestamp=revision.timestamp,
                        wikitext=slot.content,
                    )
                )

        return FetchResult(revisions=tuple(revisions), missing=tuple(missing))

    def _get(self, params: Mapping[str, str]) -> _WireResponse:
        """Issue one GET, retrying transient failures with exponential backoff."""
        retry_after: float | None = None
        last_failure = "no attempt made"

        for attempt in range(self._max_retries + 1):
            if attempt:
                # Honour Retry-After when the server named a delay; otherwise
                # back off 1, 2, 4, 8 seconds.
                time.sleep(
                    retry_after if retry_after is not None else 2.0 ** (attempt - 1)
                )
            retry_after = None

            try:
                response = self._client.get(API_URL, params=dict(params))
            except httpx.TransportError as exc:
                # Connection reset, DNS failure, read timeout: no response to
                # inspect, so there is nothing to distinguish. Retry.
                last_failure = f"{type(exc).__name__}: {exc}"
                continue

            if response.status_code in RETRY_STATUS_CODES:
                last_failure = f"HTTP {response.status_code}"
                retry_after = _parse_retry_after(response.headers.get("Retry-After"))
                continue

            if response.is_error:
                raise WikipediaError(
                    f"HTTP {response.status_code} from the MediaWiki API: "
                    f"{response.text[:200]}"
                )

            return _WireResponse.model_validate(response.json())

        raise WikipediaError(
            f"gave up after {self._max_retries + 1} attempts; "
            f"last failure was {last_failure}"
        )


class RevisionSource(Protocol):
    """The one method ingest needs. Anything with this shape will do."""

    def fetch_batch(self, titles: Sequence[str]) -> FetchResult: ...
