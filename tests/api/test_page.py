"""Tests for the front end: one HTML shell, one stylesheet, four script modules.

A static page cannot be tested the way a handler can -- nothing here runs the
JavaScript, so these do not check that the page *works*. They check what is a
property of the files rather than of the browser: that each is served with the
right type, that the shell asks only for files the package ships, and that the
scripts talk to `/ask` and to nothing else.

That last one is D-090's third decision written as an assertion. A page that
grew its own endpoint would still look right on screen, and the eval would
stop describing the thing people use.
"""

import re

from fastapi.testclient import TestClient

from eurohistory_rag.api.main import PAGE, STATIC, create_app

# The front end is four files now, so an assertion has to name the one it is
# about. SCRIPTS is every module concatenated: the claims about behaviour --
# which endpoints are called, that nothing is written as markup -- are true of
# the front end as a whole, and splitting them per file would just mean editing
# a test every time a function moved between modules.
SCRIPTS = "".join(body for name, (body, _) in STATIC.items() if name.endswith(".js"))

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


def test_the_stylesheet_and_scripts_are_served_with_their_own_types() -> None:
    """A browser refuses a module served as text/plain, and says nothing useful."""
    client = TestClient(create_app())

    assert client.get("/static/app.css").headers["content-type"].startswith("text/css")
    assert (
        client.get("/static/main.js")
        .headers["content-type"]
        .startswith("text/javascript")
    )


def test_an_unknown_static_name_is_a_404_and_touches_no_filesystem() -> None:
    """`name` arrives in a URL, so it is a dictionary key and nothing else."""
    client = TestClient(create_app())

    assert client.get("/static/nope.js").status_code == 404
    assert client.get("/static/..%2F..%2Fmain.py").status_code == 404


def test_the_page_asks_for_exactly_what_is_shipped() -> None:
    """Every file the HTML references is one the package actually holds.

    The failure this catches is a renamed module: the page still loads, the
    stylesheet or the script silently 404s, and the first sign is a screen
    with no styling.
    """
    referenced = set(re.findall(r"/static/([\w.]+)", PAGE))

    assert referenced <= set(STATIC)
    assert "app.css" in referenced
    assert "main.js" in referenced


def test_the_page_is_packaged_with_the_app() -> None:
    """The served bytes are the files on disk.

    Guards the packaging rather than the content: these are data inside the
    installed package, and a build that dropped them would fail here rather
    than in a browser.
    """
    assert PAGE.strip().endswith("</html>")
    assert TestClient(create_app()).get("/").text == PAGE
    assert len(STATIC) == 6


def test_the_only_answering_call_is_ask() -> None:
    """`/ask` is the sole path from a question to an answer.

    Relaxed from "the page calls /ask and nothing else" when the evaluation
    view arrived: it reads saved runs from `/runs`, which is not an answering
    path at all. The rule D-090 wrote down was that nothing may *answer a
    question* except `/ask`, and that is what is asserted here. Everything
    reached by this page is either `/ask` or a read-only `/runs` lookup.
    """
    called = FETCH.findall(SCRIPTS)
    reads = ("/runs", "/options")

    assert "/ask" in called
    assert [url for url in called if not url.startswith(reads)] == ["/ask"]


def test_the_page_cannot_start_an_evaluation() -> None:
    """No POST, PUT or DELETE goes anywhere except /ask.

    An eval run costs ~$0.08 and four minutes. A page that could trigger one
    would put that behind a click, and a run nobody predicted the result of is
    a run that teaches nothing (obligation 9).
    """
    assert SCRIPTS.count('method: "POST"') == 1
    assert '"/ask"' in SCRIPTS


def test_the_page_never_writes_server_text_as_html() -> None:
    """Nothing from the corpus is assigned as markup.

    The answer and the chunks are other people's text. `innerHTML` anywhere in
    this file would turn a Wikipedia passage into something the browser runs;
    `textContent` and `append` cannot.
    """
    assert "innerHTML" not in SCRIPTS
    assert "insertAdjacentHTML" not in SCRIPTS


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
    assert "BAAI/bge-reranker-base" in SCRIPTS
    assert "measured broken" in SCRIPTS


def test_the_page_reads_its_choices_from_the_server() -> None:
    """No model list is hardcoded in the page.

    The allow-list lives in `Settings`, and the endpoint refuses anything off
    it. A page carrying its own copy would offer options the server rejects the
    first time either side is edited alone.
    """
    called = FETCH.findall(SCRIPTS)

    assert "/options" in called
    assert "gpt-4.1-nano" not in SCRIPTS


def test_the_openapi_schema_lists_the_page() -> None:
    schema = TestClient(create_app()).get("/openapi.json").json()

    assert "/" in schema["paths"]
