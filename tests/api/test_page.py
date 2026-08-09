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
    assert len(STATIC) == 8


def test_the_only_answering_call_is_ask() -> None:
    """`/ask` is the sole path from a typed question to an answer.

    Relaxed twice now, and both relaxations are recorded. Phase 18 added
    `/runs`, which reads saved runs and answers nothing. Phase 20 added
    `/eval/*`, which starts the recorded evaluation -- that asks sixty
    questions, but through the runner that has always called the services
    in-process, not through a second answering endpoint of the page's own.

    The rule D-090 wrote down was that nothing may answer *the question in the
    box* except `/ask`, and that is what is asserted here.
    """
    called = FETCH.findall(SCRIPTS)
    reads = ("/runs", "/options", "/eval/")

    assert "/ask" in called
    assert [url for url in called if not url.startswith(reads)] == ["/ask"]


def test_the_page_cannot_start_an_evaluation_without_a_prediction() -> None:
    """The run button carries obligation 9 rather than bypassing it.

    D-090 asserted that this page could not start an evaluation at all, and the
    reason recorded there was not the $0.08 -- it was that "a run produced by
    clicking is a run nobody wrote a prediction for". D-094 reverses the
    conclusion and keeps the reason: the button exists, and it cannot be pressed
    until a prediction has been typed.

    So what is asserted is no longer "there is no such call" but "the call
    cannot be made empty-handed": the confirm control ships disabled, and every
    path that re-enables it goes through the prediction box.
    """
    assert 'id="run-start" type="button" disabled' in PAGE
    assert '"/eval/run"' in SCRIPTS
    assert "prediction.value.trim().length >= MIN_PREDICTION" in SCRIPTS
    # The only writes this page makes: one answer, one run start, one cancel.
    assert SCRIPTS.count('method: "POST"') == 2
    assert SCRIPTS.count('method: "DELETE"') == 1


def test_the_page_never_writes_server_text_as_html() -> None:
    """Nothing from the corpus is assigned as markup.

    The answer and the chunks are other people's text. `innerHTML` anywhere in
    this file would turn a Wikipedia passage into something the browser runs;
    `textContent` and `append` cannot.
    """
    assert "innerHTML" not in SCRIPTS
    assert "insertAdjacentHTML" not in SCRIPTS


def test_every_control_on_the_page_is_accounted_for() -> None:
    """Four buttons and three inputs, each one named here.

    The count is asserted rather than removed because it is the line that makes
    growing the page a decision somebody takes on purpose. Phase 20 was exactly
    that decision: Ask, Start and Cancel, and a second hybrid switch because the
    evaluation view carries its own copy of the settings row. Phase 24 adds the
    fourth -- "Start again", which is the only way to end a conversation, and
    without it the history grows for as long as the tab is open. D-098.
    """
    assert PAGE.count("<button") == 4
    assert PAGE.count("<input") == 3
    assert 'type="checkbox" id="hybrid-toggle"' in PAGE
    assert 'type="checkbox" id="run-hybrid"' in PAGE
    assert PAGE.count("<textarea") == 1


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


def test_the_page_sends_the_conversation_back_with_every_question() -> None:
    """The conversation lives in the tab, not on the server.

    Asserted here because it is a design decision with a consequence: a reload
    loses the thread, and nothing on the server has to know whose thread it was.
    D-098.
    """
    assert "history: history.slice(-HISTORY_SENT)" in SCRIPTS


def test_the_page_shows_what_was_actually_searched_for() -> None:
    """A rewrite nobody can see is Phase 8's dead switch with better manners."""
    assert '"understood as: " + data.standalone' in SCRIPTS
