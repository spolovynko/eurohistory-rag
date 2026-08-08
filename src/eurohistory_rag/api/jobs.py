"""The one long job this API can be asked to do, and the state it lives in.

Every other endpoint in this system finishes inside its own request. An
evaluation does not: sixty questions take about four minutes, and the browser
that started it may be closed, reloaded or replaced before it ends. So the run
has to live somewhere that is not a request and not a browser, and this module
is that somewhere.

**Why a lock and not just a variable.** "Is one running?" and "start one" have
to be a single indivisible decision. Two clicks a millisecond apart both read
`state == "idle"`, both start a run, and the account is billed twice for a
comparison nobody can interpret. A plain module-level variable cannot prevent
that; a lock held across both steps can.

**What this design assumes.** One process. Run uvicorn with two workers and each
gets its own idle-looking job, and the guarantee is silently gone. That is the
point at which this state has to move out of memory -- written down here rather
than discovered later.
"""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

# The states a run can be in. "idle" is also the state after one finishes and
# is read -- there is no queue and no history here, because the run directory
# on disk is the history and it is better than anything held in memory.
IDLE = "idle"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class JobStatus:
    """Everything a page needs to draw the state of a run it did not start.

    Frozen and copied rather than mutated, so a reader always sees one
    self-consistent picture. A status read halfway through a field-by-field
    update would show a question count from one moment and a state from another,
    which is the sort of bug that only appears under the load nobody tests with.
    """

    state: str = IDLE
    run_id: str = ""
    total: int = 0
    completed: int = 0
    current: str = ""
    started_at: str = ""
    finished_at: str = ""
    directory: str = ""
    error: str = ""
    # Filled in by the caller once the run is written and gated. Kept on the job
    # rather than only on disk because the page asks one question -- "what
    # happened?" -- and a verdict living somewhere else would mean two.
    baseline: str = ""
    gate_report: str = ""
    gate_passed: bool | None = None
    extra: dict[str, str] = field(default_factory=dict)


class EvalJob:
    """One evaluation at a time, with progress and a way to stop it."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._status = JobStatus()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def status(self) -> JobStatus:
        """What the run is doing right now.

        Cheap and safe to call from anywhere, which is what makes polling the
        right shape for the page: the browser holds no state of its own, so a
        reload or a second tab picks the run up exactly where it is.
        """
        with self._lock:
            return self._status

    @property
    def stopping(self) -> bool:
        """Whether someone has asked this run to stop."""
        return self._stop.is_set()

    def start(
        self, run_id: str, total: int, work: Callable[["EvalJob"], str]
    ) -> JobStatus | None:
        """Begin a run, or return None if one is already going.

        The claim and the check happen under one lock, which is the whole
        reason this class exists rather than a pair of module-level variables.
        `work` is handed the job so it can report progress and see a cancel; it
        returns the run directory it wrote.
        """
        with self._lock:
            if self._status.state == RUNNING:
                return None
            self._stop.clear()
            self._status = JobStatus(
                state=RUNNING,
                run_id=run_id,
                total=total,
                started_at=datetime.now(UTC).isoformat(timespec="seconds"),
            )
        # Started outside the lock: spawning a thread is fast, but holding a
        # lock across anything that can block is how a status endpoint ends up
        # hanging behind the job it is describing.
        self._thread = threading.Thread(
            target=self._run, args=(work,), name=f"eval-{run_id}", daemon=True
        )
        self._thread.start()
        return self.status()

    def progress(self, completed: int, current: str) -> None:
        """Record that the run has reached a question.

        Called before the question is asked rather than after, so the number on
        screen is what is happening now. A bar that only moves on completion
        sits still for the eight seconds a slow question takes, which reads as
        a hang -- and this bar exists to say "not stuck", not to be precise.
        """
        with self._lock:
            self._status = replace(self._status, completed=completed, current=current)

    def annotate(self, **fields: object) -> None:
        """Attach the run's outcome -- directory, gate verdict -- to the status."""
        with self._lock:
            self._status = replace(self._status, **fields)  # type: ignore[arg-type]

    def cancel(self) -> bool:
        """Ask the run to stop after the question it is on. False if none is."""
        with self._lock:
            if self._status.state != RUNNING:
                return False
        self._stop.set()
        return True

    def _finish(self, state: str, **fields: object) -> None:
        """Move out of RUNNING exactly once, from the worker thread."""
        with self._lock:
            self._status = replace(
                self._status,
                state=state,
                finished_at=datetime.now(UTC).isoformat(timespec="seconds"),
                **fields,  # type: ignore[arg-type]
            )

    def _run(self, work: Callable[["EvalJob"], str]) -> None:
        """The worker thread's body: run the work, and end in a final state.

        Every exception is caught and recorded. A background thread that raises
        prints a traceback nobody is reading and leaves the job stuck on
        "running" forever, which would make the next click a 409 for the rest
        of the process's life.
        """
        from eurohistory_rag.eval.run import Cancelled

        try:
            directory = work(self)
        except Cancelled as stopped:
            logger.info("evaluation cancelled: %s", stopped)
            self._finish(CANCELLED, error=str(stopped))
        except Exception as failure:  # noqa: BLE001 -- see docstring
            logger.exception("evaluation failed")
            self._finish(FAILED, error=f"{type(failure).__name__}: {failure}")
        else:
            self._finish(DONE, directory=directory)


# The one job for this process. A module-level instance rather than a FastAPI
# dependency because it is deliberately *not* per-request state: two requests
# asking about the run must see the same run.
JOB = EvalJob()


def get_job() -> EvalJob:
    """The process's evaluation job.

    A function rather than the bare name so tests can replace it through
    `dependency_overrides` and get a job of their own, the same way every other
    expensive thing in this API is swapped.
    """
    return JOB
