"""Tests for the one HTML page.

A static page cannot be tested the way a handler can -- nothing here runs the
JavaScript, so these do not check that the page *works*. They check the two
things that are properties of the file rather than of the browser: that it is
actually served, and that it talks to `/ask` and to nothing else.

The second one is D-090's third decision written as an assertion. A page that
grew its own endpoint would still look right on screen, and the eval would
stop describing the thing people use.
"""

import re

from fastapi.testclient import TestClient

from eurohistory_rag.api.main import PAGE, create_app

# Every network call the page makes. One capture group: the URL.
#
# Both spellings, and that matters: the page calls `/ask` through `fetch`
# directly and everything else through its own `getJSON` helper. A pattern
# matching only `fetch(` reported one call and passed -- which made the
# "nothing but /ask" assertion below true for the wrong reason.
FETCH = re.compile(r"(?:fetch|getJSON)\(\s*\"([^\"]+)\"")


def test_the_root_route_serves_html() -> None:
    """A browser pointed at the server gets a page, not a JSON error."""
    response = TestClient(create_app()).get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.text.startswith("<!doctype html>")


def test_the_page_is_packaged_with_the_app() -> None:
    """The served bytes are the file on disk.

    Guards the packaging rather than the content: page.html is data inside the
    installed package, and a build that dropped it would fail here rather than
    in a browser.
    """
    assert PAGE.strip().endswith("</html>")
    assert TestClient(create_app()).get("/").text == PAGE


def test_the_only_answering_call_is_ask() -> None:
    """`/ask` is the sole path from a question to an answer.

    Relaxed from "the page calls /ask and nothing else" when the evaluation
    view arrived: it reads saved runs from `/runs`, which is not an answering
    path at all. The rule D-090 wrote down was that nothing may *answer a
    question* except `/ask`, and that is what is asserted here. Everything
    reached by this page is either `/ask` or a read-only `/runs` lookup.
    """
    called = FETCH.findall(PAGE)
    reads = ("/runs", "/options")

    assert "/ask" in called
    assert [url for url in called if not url.startswith(reads)] == ["/ask"]


def test_the_page_cannot_start_an_evaluation() -> None:
    """No POST, PUT or DELETE goes anywhere except /ask.

    An eval run costs ~$0.08 and four minutes. A page that could trigger one
    would put that behind a click, and a run nobody predicted the result of is
    a run that teaches nothing (obligation 9).
    """
    assert PAGE.count('method: "POST"') == 1
    assert '"/ask"' in PAGE


def test_the_page_never_writes_server_text_as_html() -> None:
    """Nothing from the corpus is assigned as markup.

    The answer and the chunks are other people's text. `innerHTML` anywhere in
    this file would turn a Wikipedia passage into something the browser runs;
    `textContent` and `append` cannot.
    """
    assert "innerHTML" not in PAGE
    assert "insertAdjacentHTML" not in PAGE


def test_the_page_offers_no_second_button() -> None:
    """Still one button, and every input is accounted for.

    Phase 19 added the settings row, so `<input>` is no longer one: the second
    is the hybrid switch, which is a real checkbox underneath its pill so that
    it is keyboard operable and announces itself. The count is asserted rather
    than removed -- it is the line that makes growing the page a decision
    somebody has to take on purpose.
    """
    assert PAGE.count("<button") == 1
    assert PAGE.count("<input") == 2
    assert 'type="checkbox" id="hybrid-toggle"' in PAGE


def test_the_broken_reranker_is_named_as_broken() -> None:
    """Phase 8's bad model is on the menu, and cannot be picked unwarned.

    It stays selectable because it is the value in `config.py`, so hiding it
    would make the documented default unreproducible from the page. What it may
    not do is look like an ordinary choice.
    """
    assert "BAAI/bge-reranker-base" in PAGE
    assert "measured broken" in PAGE


def test_the_page_reads_its_choices_from_the_server() -> None:
    """No model list is hardcoded in the page.

    The allow-list lives in `Settings`, and the endpoint refuses anything off
    it. A page carrying its own copy would offer options the server rejects the
    first time either side is edited alone.
    """
    called = FETCH.findall(PAGE)

    assert "/options" in called
    assert "gpt-4.1-nano" not in PAGE


def test_the_openapi_schema_lists_the_page() -> None:
    schema = TestClient(create_app()).get("/openapi.json").json()

    assert "/" in schema["paths"]
