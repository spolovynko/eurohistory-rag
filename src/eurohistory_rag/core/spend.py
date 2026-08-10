"""What a call costs, what today has cost already, and when to say no.

A confirmation dialog is not a limit. Since Phase 20 the page has shown a price
and asked someone to agree to it, and that is a convention: it depends on a
person reading the number, and it does nothing at all about the second, third
and four-hundredth request. This module is the part that does not depend on
anyone reading anything.

**Why this lives in `core/` and not in `generation/` or `eval/`.** Both spend.
`eval/cost.py` imports `eval/record.py`, which imports `generation/rewrite.py`,
so anything `generation/` needs cannot live under `eval/` without a cycle. The
price list came here from `eval/cost.py` for exactly that reason and is still
written once -- `cost.py` imports it back, so the estimate before a run and the
figure charged during one cannot disagree. D-104.

**The ledger is the first thing under `data/` that is not rebuildable.** Bronze
can rebuild Silver, Gold and Qdrant; nothing can rebuild a record of money
already spent. Deleting `data/spend/` starts the day over, which is a real
weakness and is written here rather than discovered later. It stays gitignored
because what one machine spent is not a fact about this project.
"""

import json
import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Dollars per million tokens, (prompt, cached prompt, completion). A hardcoded
# price list is a thing that goes stale, and this one will: it is here rather
# than in `Settings` because it is not a per-machine setting, and it is small
# enough to correct in one line when OpenAI moves a price.
#
# The middle column arrived in Phase 29 and barely changes anything: a prompt
# token the provider has already seen costs a quarter of a fresh one, and the
# system prompt is ~62% of every prompt this system sends -- but it is only
# ~1,600 tokens, and gpt-4.1-mini needs a shared prefix over ~2,048 before it
# caches at all. Measured: 1 of 106 answering calls cached anything. D-103.
PRICES: dict[str, tuple[float, float, float]] = {
    "gpt-4.1-mini": (0.40, 0.10, 1.60),
    "gpt-4.1-nano": (0.10, 0.025, 0.40),
    "gpt-4.1": (2.00, 0.50, 8.00),
    "gpt-4o-mini": (0.15, 0.075, 0.60),
}

# One file per UTC day, appended to and never rewritten. Under `data/` because
# it is machine-local and gitignored; a day per file because that makes "what
# has today cost" a read of one small file rather than a scan of a growing one,
# and makes forgetting the past a matter of deleting old files.
LEDGER_DIR = Path("data/spend")


class CeilingExceeded(RuntimeError):
    """The spend this would cause is over a limit, so it was not attempted.

    Raised *before* the call, always. A ceiling checked after the money has
    left is a receipt, not a limit, and the whole done-when of Phase 30 is that
    a run which would exceed the ceiling is refused before the first question
    is asked. D-104.
    """


def dollars(
    prompt_tokens: int, cached_tokens: int, completion_tokens: int, model: str
) -> float:
    """What a set of token counts actually cost, in dollars.

    The one place the price list is applied, so the estimate before a run, the
    figure printed after it and the running total that enforces a ceiling
    cannot disagree -- which they would within a phase of each other if the
    arithmetic were written three times. `cached_tokens` is a subset of
    `prompt_tokens`, not an addition to it: the rest are billed at full rate.
    """
    full_price, cached_price, completion_price = PRICES.get(
        model, PRICES["gpt-4.1-mini"]
    )
    fresh = max(prompt_tokens - cached_tokens, 0)
    return (
        fresh * full_price
        + cached_tokens * cached_price
        + completion_tokens * completion_price
    ) / 1_000_000


def _today() -> str:
    """The UTC date the ledger is filed under.

    UTC rather than local time so the day a ceiling covers is the same day the
    run directories are named after -- `2026-08-10T1413Z` and
    `2026-08-10.jsonl` are the same Tuesday, on any machine.
    """
    return datetime.now(UTC).strftime("%Y-%m-%d")


@dataclass(frozen=True, slots=True)
class DayTotal:
    """What today has cost so far, and how many calls it took.

    The call count is not decoration. A day that reached $0.90 over four
    evaluations is a busy day; a day that reached it over nine thousand calls
    is the loop this phase exists to notice, and the number is the only thing
    that tells those apart.
    """

    dollars: float
    calls: int


class Ledger:
    """The running total of what this machine has spent today.

    A class rather than module functions because the directory has to be
    swappable: a test that wrote to the real `data/spend/` would either pollute
    a real total or, worse, be silently refused by a real ceiling somebody else
    had already reached.
    """

    def __init__(self, directory: Path = LEDGER_DIR) -> None:
        self._directory = directory
        # Two requests finishing at once both append, and a line interleaved
        # halfway through another is a line neither can read back. The same
        # argument as `EvalJob`'s lock, and the same limitation: one process.
        # Two uvicorn workers get two ledgers over one file, and the append is
        # still atomic enough for the total to be right, but the read-then-
        # refuse decision is no longer indivisible. Written down rather than
        # discovered later.
        self._lock = threading.Lock()

    def _path(self, day: str) -> Path:
        return self._directory / f"{day}.jsonl"

    def record(self, amount: float, what: str) -> None:
        """Write down that `amount` dollars were just spent on `what`.

        Called after the money is gone, because the exact figure is not known
        until the provider reports its token counts. That ordering is why the
        day ceiling is checked against what is *already* recorded rather than
        against a projection: this is a stop, not a forecast.

        A failure to write is logged and swallowed. An unwritable ledger is a
        real problem, but taking down every answer in the system because a disk
        is full would be a worse one -- and the failure is loud in the log.
        """
        line = json.dumps(
            {
                "at": datetime.now(UTC).isoformat(timespec="seconds"),
                "dollars": round(amount, 6),
                "what": what,
            }
        )
        try:
            with self._lock:
                self._directory.mkdir(parents=True, exist_ok=True)
                with self._path(_today()).open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
        except OSError as error:
            logger.warning("could not write the spend ledger: %s", error)

    def today(self) -> DayTotal:
        """What has been spent so far today, in dollars and in calls.

        A missing file means a day on which nothing has been spent, which is
        the ordinary state at midnight and not an error. A line that will not
        parse is skipped rather than fatal: a half-written line from a killed
        process must not make the ceiling unenforceable, and the alternative --
        refusing everything until someone edits a file by hand -- is worse than
        under-counting by one call.
        """
        path = self._path(_today())
        if not path.is_file():
            return DayTotal(dollars=0.0, calls=0)
        total = 0.0
        calls = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                total += float(json.loads(line)["dollars"])
            except (ValueError, KeyError, TypeError):
                logger.warning("unreadable line in the spend ledger, skipped")
                continue
            calls += 1
        return DayTotal(dollars=round(total, 6), calls=calls)

    def check_day(self, ceiling: float) -> None:
        """Raise if today has already reached the ceiling.

        Against what is recorded, not against what is recorded plus a guess at
        this call. Overshooting by one call is the price of not needing to
        predict the size of an answer nobody has written yet, and one call of
        gpt-4.1-mini is four hundredths of a cent.

        A ceiling of zero or less means no limit, so that a machine which wants
        none says so in `.env` rather than by editing code.
        """
        if ceiling <= 0:
            return
        spent = self.today()
        if spent.dollars >= ceiling:
            raise CeilingExceeded(
                f"Today has spent ${spent.dollars:.4f} over {spent.calls} calls, "
                f"which is at or over the ${ceiling:.2f} daily ceiling. "
                f"Raise MAX_DAY_DOLLARS or wait for tomorrow (UTC)."
            )


def check_run(quoted: float, ceiling: float) -> None:
    """Raise if a quoted run costs more than one run is allowed to.

    Takes the quote rather than working it out, because the quote is already
    computed by `eval/cost.py` and shown next to the button -- so the number
    that refuses the run is the same number the person was shown, and a
    disagreement between them is impossible rather than merely unlikely.
    """
    if ceiling <= 0:
        return
    if quoted > ceiling:
        raise CeilingExceeded(
            f"This run is quoted at ${quoted:.4f}, over the ${ceiling:.2f} "
            f"per-run ceiling. Raise MAX_RUN_DOLLARS or ask fewer questions."
        )


@dataclass(frozen=True, slots=True)
class Meter:
    """A ledger and the ceiling it is judged against, handed to a caller as one.

    Exists so that the code which spends needs no opinion about where limits
    come from. `OpenAIGenerator` asks a meter "may I?" and tells it "that cost
    this much"; it never reads `Settings`, never knows a UTC day exists, and a
    test hands it a meter over a temporary directory with no ceremony. That is
    the dependency-inversion rule in this repo's terms: the thing that spends
    depends on two small methods, not on a configuration system.

    `None` in place of a meter means unmetered, which is what every existing
    call site got before this phase and what the pipeline still gets.
    """

    ledger: Ledger
    day_ceiling: float

    def check(self) -> None:
        """Raise `CeilingExceeded` if today is already at its limit."""
        self.ledger.check_day(self.day_ceiling)

    def record_tokens(
        self,
        prompt_tokens: int | None,
        cached_tokens: int | None,
        completion_tokens: int | None,
        model: str,
        what: str,
    ) -> None:
        """Price a finished call and add it to today's total.

        A call that reported no token counts is recorded as nothing rather than
        as a guess. That under-counts, and the alternative is worse: a ceiling
        enforced partly on measurements and partly on invention is a number
        nobody can act on, and the same argument already keeps `cached_tokens`
        as `None` rather than `0` on the 27 runs that never read it. D-103.
        """
        if prompt_tokens is None or completion_tokens is None:
            logger.debug("call reported no token counts; not metered")
            return
        self.ledger.record(
            dollars(prompt_tokens, cached_tokens or 0, completion_tokens, model),
            what,
        )


# The one ledger for this process, for the same reason `JOB` is a module-level
# instance: two requests asking "what has today cost" must not get two answers.
LEDGER = Ledger()


def get_ledger() -> Ledger:
    """This process's spend ledger, replaceable by tests."""
    return LEDGER
