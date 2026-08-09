"""Tests for the one endpoint in this system that can spend money.

Nothing here starts a real evaluation. What is being checked is the order of
events and the refusals around them -- that the prediction is on disk before
any work begins, that a second click cannot start a second run, and that a
request from off this machine is turned away. The evaluation itself is tested
where it lives.
"""

import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from eurohistory_rag.api import experiment as experiment_module
from eurohistory_rag.api import main as main_module
from eurohistory_rag.api.jobs import EvalJob, get_job
from eurohistory_rag.api.main import create_app
from eurohistory_rag.eval.execute import PREDICTION_FILE, RunConfig
from eurohistory_rag.eval.questions import (
    QUESTIONS_PATH,
    Question,
    load_questions,
)
from eurohistory_rag.eval.record import RUNS_DIR
from eurohistory_rag.eval.run import Cancelled

PREDICTION = "recall@5 will not move at all; anything above 70% is impossible."

# The size of the real committed set. Read rather than typed: the count grows
# whenever a suite is added -- Phase 22 took it from 60 to 78 -- and a literal
# here turns that into three unrelated test failures.
COMMITTED = len(load_questions(QUESTIONS_PATH))


@pytest.fixture
def runs_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Send every run directory this module creates into a temporary folder.

    `write_prediction` defaults to the real `eval/runs/`, and a test that wrote
    there would leave a directory in the repository that looks like a failed
    run.
    """
    root = tmp_path / "runs"
    root.mkdir()
    monkeypatch.setattr(experiment_module, "RUNS_DIR", root)
    monkeypatch.setattr(main_module, "RUNS_DIR", root)
    return root


@pytest.fixture
def app_with_job(
    runs_root: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, EvalJob, list[Path]]]:
    """A client whose preconditions pass and whose "run" writes a marker file.

    The stub work is what makes the ordering testable: it records the run
    directory it was given, and the assertion is about what was already in that
    directory when it was called.
    """
    job = EvalJob()
    seen: list[Path] = []

    monkeypatch.setattr(
        main_module,
        "check_preconditions",
        lambda settings: [
            experiment_module.Precondition(name="all", ok=True, detail="fine")
        ],
    )
    monkeypatch.setattr(
        main_module,
        "load_questions",
        lambda path: [
            Question(id=f"q{n}", text="why?", kind="easy", expected=("1:0",))
            for n in range(3)
        ],
    )

    def fake_make_work(*args: object, **kwargs: object) -> object:
        run_id = str(kwargs["run_id"])

        def work(_: EvalJob) -> str:
            directory = runs_root / run_id
            seen.append(directory / PREDICTION_FILE)
            return str(directory)

        return work

    monkeypatch.setattr(main_module, "make_work", fake_make_work)

    app = create_app()
    app.dependency_overrides[get_job] = lambda: job
    with TestClient(app, client=("127.0.0.1", 5000)) as client:
        yield client, job, seen


def wait_for(job: EvalJob, state: str, seconds: float = 5.0) -> None:
    """Block until the worker thread reaches a state, or give up."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if job.status().state == state:
            return
        time.sleep(0.01)
    raise AssertionError(f"job stayed in {job.status().state!r}, wanted {state!r}")


# --- the prediction ---------------------------------------------------------


def test_a_run_cannot_be_started_without_a_prediction(
    app_with_job: tuple[TestClient, EvalJob, list[Path]],
) -> None:
    """Obligation 9 in the schema: no prediction, no run, no spend."""
    client, job, seen = app_with_job

    response = client.post("/eval/run", json={"questions": 3})

    assert response.status_code == 422
    assert job.status().state == "idle"
    assert seen == []


def test_a_one_word_prediction_is_refused(
    app_with_job: tuple[TestClient, EvalJob, list[Path]],
) -> None:
    """ "yes" satisfies "not empty" and predicts nothing."""
    client, _, _ = app_with_job

    response = client.post("/eval/run", json={"prediction": "yes", "questions": 3})

    assert response.status_code == 422


def test_the_prediction_is_on_disk_before_the_first_question(
    app_with_job: tuple[TestClient, EvalJob, list[Path]], runs_root: Path
) -> None:
    """The whole phase, as one assertion.

    The stub work runs in the worker thread, in place of the evaluation. What
    it checks is that by the time anything could have been asked, the prediction
    file already existed -- which is what makes it uneditable once numbers
    arrive.
    """
    client, job, seen = app_with_job

    response = client.post("/eval/run", json={"prediction": PREDICTION, "questions": 3})
    assert response.status_code == 200
    wait_for(job, "done")

    assert len(seen) == 1
    assert seen[0].exists()
    assert seen[0].read_text(encoding="utf-8").strip() == PREDICTION


def test_a_run_that_dies_leaves_its_prediction_and_no_records(
    runs_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A half-finished run is inert, not half a run.

    `browse._is_run` requires both meta.json and records.jsonl, and a cancelled
    run writes neither -- so the directory left behind cannot be listed, gated
    or mistaken for a result. The prediction survives, which is the right way
    round.
    """
    from eurohistory_rag.eval.browse import _is_run

    experiment_module.write_prediction("2026-01-01T0000Z", PREDICTION, runs_root)
    directory = runs_root / "2026-01-01T0000Z"

    assert (directory / PREDICTION_FILE).exists()
    assert not (directory / "records.jsonl").exists()
    assert not _is_run(directory)


# --- spending money ---------------------------------------------------------


def test_a_request_from_another_machine_is_refused(
    runs_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """There is no authentication in this system, so this is the whole control.

    It guards against the deployment mistake -- uvicorn bound to 0.0.0.0 and
    left running -- rather than against an attacker. Everything else on the
    page is a read; this is the one call that costs eight cents.
    """
    monkeypatch.setattr(
        main_module,
        "check_preconditions",
        lambda settings: [],
    )
    with TestClient(create_app(), client=("10.0.0.7", 5000)) as client:
        response = client.post(
            "/eval/run", json={"prediction": PREDICTION, "questions": COMMITTED}
        )

    assert response.status_code == 403
    assert "this machine" in response.json()["detail"]


def test_a_quote_for_a_different_number_of_questions_is_refused(
    app_with_job: tuple[TestClient, EvalJob, list[Path]],
) -> None:
    """The price shown must be the price paid.

    The question file can grow between the dialog opening and the button being
    pressed. Sixty questions quoted and ninety run is not a rounding error --
    it is half as much again, spent without being agreed to.
    """
    client, job, _ = app_with_job

    response = client.post(
        "/eval/run", json={"prediction": PREDICTION, "questions": COMMITTED}
    )

    assert response.status_code == 422
    assert "Reload" in response.json()["detail"]
    assert job.status().state == "idle"


def test_a_failing_precondition_refuses_before_anything_is_spent(
    runs_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Four minutes in is the wrong moment to find out Qdrant is down."""
    monkeypatch.setattr(
        main_module,
        "check_preconditions",
        lambda settings: [
            experiment_module.Precondition(
                name="vector store", ok=False, detail="localhost:6333 is unreachable"
            )
        ],
    )
    with TestClient(create_app(), client=("127.0.0.1", 5000)) as client:
        response = client.post(
            "/eval/run", json={"prediction": PREDICTION, "questions": COMMITTED}
        )

    assert response.status_code == 503
    assert "unreachable" in response.json()["detail"]


def test_an_unknown_model_is_refused_before_a_directory_is_made(
    app_with_job: tuple[TestClient, EvalJob, list[Path]], runs_root: Path
) -> None:
    """The allow-list applies to the expensive path too, not only to /ask."""
    client, _, _ = app_with_job

    response = client.post(
        "/eval/run",
        json={"prediction": PREDICTION, "questions": 3, "model": "gpt-9-ultra"},
    )

    assert response.status_code == 422
    assert list(runs_root.iterdir()) == []


# --- one at a time ----------------------------------------------------------


def test_a_second_start_while_one_is_running_is_refused() -> None:
    """Two clicks a millisecond apart must not become two runs.

    Tested on the job rather than through HTTP, because what is being checked
    is the lock: the second caller has to be refused even when it arrives
    before the first has done anything at all.
    """
    job = EvalJob()
    release = threading.Event()

    def slow(_: EvalJob) -> str:
        release.wait(timeout=5)
        return "first"

    assert job.start("run-a", 3, slow) is not None
    assert job.start("run-b", 3, slow) is None
    assert job.status().run_id == "run-a"

    release.set()
    wait_for(job, "done")


def test_the_second_click_gets_a_409_naming_the_run_it_lost_to(
    app_with_job: tuple[TestClient, EvalJob, list[Path]],
) -> None:
    """A refusal that says what is already going, not just "no"."""
    client, job, _ = app_with_job
    release = threading.Event()
    job.start("2026-01-01T0000Z", 3, lambda _: (release.wait(timeout=5), "x")[1])

    try:
        response = client.post(
            "/eval/run", json={"prediction": PREDICTION, "questions": 3}
        )
        assert response.status_code == 409
        assert "2026-01-01T0000Z" in response.json()["detail"]
    finally:
        release.set()
        wait_for(job, "done")


def test_a_reload_reconnects_to_the_run_in_progress(
    app_with_job: tuple[TestClient, EvalJob, list[Path]],
) -> None:
    """The state is in the server, so the browser is only a viewer.

    A second client is what a reload, a second tab or a different browser all
    look like from here: the run is not theirs, and they see it anyway.
    """
    client, job, _ = app_with_job
    release = threading.Event()
    job.start("2026-01-01T0000Z", 60, lambda _: (release.wait(timeout=5), "x")[1])
    job.progress(17, "berlin-wall-why")

    try:
        status = client.get("/eval/run").json()
        assert status["state"] == "running"
        assert status["completed"] == 17
        assert status["current"] == "berlin-wall-why"
        assert status["total"] == 60
    finally:
        release.set()
        wait_for(job, "done")


# --- stopping ---------------------------------------------------------------


def test_cancelling_nothing_is_a_409(
    app_with_job: tuple[TestClient, EvalJob, list[Path]],
) -> None:
    client, _, _ = app_with_job

    assert client.delete("/eval/run").status_code == 409


def test_a_cancelled_run_ends_in_cancelled_and_frees_the_job() -> None:
    """A stopped run must not wedge the process into a permanent 409."""
    job = EvalJob()
    started = threading.Event()

    def work(inner: EvalJob) -> str:
        started.set()
        while not inner.stopping:
            time.sleep(0.01)
        raise Cancelled("stopped before question 4")

    job.start("run-a", 60, work)
    assert started.wait(timeout=5)
    assert job.cancel() is True
    wait_for(job, "cancelled")

    assert job.status().error.startswith("stopped")
    assert job.start("run-b", 60, lambda _: "second") is not None


def test_a_run_that_raises_ends_in_failed_rather_than_running_forever() -> None:
    """A background thread that throws must not leave the job claimed.

    Nobody is reading the traceback of a daemon thread. If the state stayed
    "running", every later click would be a 409 for the life of the process.
    """
    job = EvalJob()

    job.start("run-a", 3, lambda _: (_ for _ in ()).throw(RuntimeError("qdrant died")))
    wait_for(job, "failed")

    assert job.status().error == "RuntimeError: qdrant died"
    assert job.start("run-b", 3, lambda _: "second") is not None


# --- the automatic declaration ----------------------------------------------


def test_the_changed_knobs_are_derived_from_the_baseline(tmp_path: Path) -> None:
    """The gate's `--changed` argument, worked out rather than remembered.

    The gate refuses a comparison whose declared change did not happen, which
    is Phase 8's dead switch turned into a check. Deriving the declaration is
    what makes that check run every time instead of when somebody remembers.
    """
    baseline = tmp_path / "2026-08-06T1832Z"
    baseline.mkdir()
    (baseline / "meta.json").write_text(
        '{"run_id": "b", "started_at": "", "git_sha": "", '
        '"embedding_model": "text-embedding-3-small", '
        '"generation_model": "gpt-4.1-mini", "collection": "chunks", '
        '"points": 1, "k": 5, "max_per_document": 2, "overfetch": 4, '
        '"reranker": "cross-encoder/ms-marco-MiniLM-L6-v2", "hybrid": ""}',
        encoding="utf-8",
    )
    same = RunConfig(
        k=5,
        model="gpt-4.1-mini",
        reranker="cross-encoder/ms-marco-MiniLM-L6-v2",
        hybrid=False,
        temporal=False,
        conversation=False,
    )

    assert experiment_module.changed_fields(baseline, same) == frozenset()
    assert experiment_module.changed_fields(
        baseline,
        RunConfig(
            k=10,
            model="gpt-4.1-nano",
            reranker="",
            hybrid=True,
            temporal=False,
            conversation=False,
        ),
    ) == frozenset({"k", "generation_model", "reranker", "hybrid"})


def test_a_missing_baseline_declares_nothing_rather_than_raising(
    tmp_path: Path,
) -> None:
    """A directory that is not a run is not a comparison, and not a crash."""
    config = RunConfig(
        k=5,
        model="gpt-4.1-mini",
        reranker="",
        hybrid=False,
        temporal=False,
        conversation=False,
    )

    assert experiment_module.changed_fields(tmp_path / "nope", config) == frozenset()


def test_the_real_runs_directory_is_untouched_by_these_tests() -> None:
    """A guard on the fixture, not on the code.

    `write_prediction` defaults to the repository's own eval/runs/, and a test
    that leaked into it leaves a directory that looks like a failed run.

    This is written against the *text* rather than against a fixed run id, and
    the first draft was not: it looked for "2026-01-01T0000Z" and passed while
    a real leak sat in eval/runs/ under a genuine timestamp, because the
    endpoint mints its own id. Found by reading `git status`, not by the test
    that existed to find it.
    """
    if not RUNS_DIR.is_dir():
        return
    leaked = [
        path
        for path in RUNS_DIR.glob("*/" + PREDICTION_FILE)
        if PREDICTION in path.read_text(encoding="utf-8")
    ]

    assert leaked == []
