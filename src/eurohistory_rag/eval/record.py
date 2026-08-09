"""What one evaluation run writes down.

Frozen deliberately early, before a single question exists. Phase 8 compares
two runs field by field, and a shape that changes between them turns that
comparison into guesswork -- so every number the eval might ever want has a
slot here, even the ones nothing fills in yet.
"""

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Where runs land. One directory per run, so the records, the readable dump and
# the summary of a single run never get separated from each other.
RUNS_DIR = Path("eval/runs")


@dataclass(frozen=True, slots=True)
class RunMeta:
    """The conditions a run happened under.

    Every knob that changes what comes back, captured at run time. Without this
    two runs are two lists of answers with no way to tell which change caused
    the difference -- which is the one thing Phase 8 exists to establish.
    """

    run_id: str
    started_at: str
    git_sha: str
    embedding_model: str
    generation_model: str
    collection: str
    points: int
    k: int
    max_per_document: int
    overfetch: int
    # The reranker model, or "" when reranking was off. Phase 8's whole
    # before/after rests on being able to tell the two runs apart later, and a
    # run directory outlives anyone's memory of which flag was set that day.
    reranker: str = ""
    # How the candidates were generated, or "" when hybrid search was off. A
    # description rather than a flag because the RRF constant is part of what
    # was measured -- "hybrid was on" does not identify a run, "bm25+rrf(k=60)"
    # does. Phase 8's A/A accident is why this field exists at all: the run
    # that measured nothing was only detectable because meta.json said so.
    hybrid: str = ""
    # The model that checked each answer against its sources, or "" when the
    # groundedness gate was off. Phase 8 ran a whole eval with the reranker flag
    # still false and only caught it because meta.json recorded the model name;
    # this field exists so Phase 13 cannot repeat that. D-084.
    verifier: str = ""
    # How the period arm was run, or "" when it was off. Same reasoning as
    # `hybrid` above: it is a description rather than a flag, and it defaults to
    # empty so every run already on disk reads back as a run without it, which
    # is what makes those runs valid "before" halves. Phase 22, D-096.
    temporal: str = ""
    note: str = ""


@dataclass(frozen=True, slots=True)
class Retrieved:
    """One chunk that came back, with everything needed to judge it.

    `doc_id` is what ground truth is written against -- a section has a name a
    human can recognise, where a chunk is an arbitrary slice of one.
    """

    rank: int
    chunk_id: str
    doc_id: str
    page_id: int
    source: str
    score: float
    # Filled in only for the chunks the model was actually shown. Checking
    # whether a sentence is supported means reading the claim against its
    # source, and looking each one up by hand is the step that gets skipped.
    # The ranks below the cut-off keep names only -- recall needs no text.
    text: str = ""
    # None when reranking was off. Kept next to `score` rather than replacing
    # it: `score` is the cosine number the Phase 7 baseline measured, and
    # overwriting it would make the two runs' score columns incomparable.
    rerank_score: float | None = None
    # BM25's score, or None when the keyword search did not return this chunk.
    # With `score` it says which search found a result: both numbers present
    # means the two agreed, `score = 0.0` means keyword alone put it here.
    # That is the question worth asking of any chunk that moved this phase.
    sparse_score: float | None = None


@dataclass(frozen=True, slots=True)
class CitationRef:
    """A marker in the answer, resolved back to the chunk it points at."""

    number: int
    doc_id: str
    source: str


@dataclass(frozen=True, slots=True)
class EvalRecord:
    """One question, everything the system did with it, and what it cost.

    Deliberately holds no verdict. Whether an answer is good is a judgement,
    it is made by hand, and it lives in its own file -- so re-running the eval
    can never overwrite work that took an hour of reading.
    """

    question_id: str
    question: str
    kind: str
    expected_doc_ids: list[str]

    retrieved: list[Retrieved]

    answer: str
    generation_model: str
    sources_sent: int
    markers_found: list[int]
    citations: list[CitationRef]

    search_ms: float
    generate_ms: float
    total_ms: float

    # Whether the groundedness gate changed this answer, and what it replaced.
    # `draft` is empty unless `revised` is true. At a firing rate of a few
    # percent no aggregate metric can see this gate, so the pair -- draft next
    # to revision -- is the measurement rather than a debugging aid. D-084.
    revised: bool = False
    draft: str = ""

    # When the first piece of the answer became available, measured from the
    # start of the question and so including the search. `None` means the run
    # predates streaming, and the metric reads that as "at the end" rather than
    # as zero -- on the old path the first character of the answer arrived at
    # the same instant the last one did. Phase 21, D-095.
    first_token_ms: float | None = None

    # Which batch the question was written in -- "golden", "extended" or
    # "synthetic". Carried into the record rather than looked up from
    # questions.toml at scoring time, because `rescore` reads a run off disk
    # months later and the file it was written from may have grown since. D-087.
    suite: str = "golden"

    # The written forms that would count as stating the fact asked for, copied
    # from the question. Carried into the record for the same reason `suite` is:
    # `rescore` reads a run off disk long after questions.toml has moved on, and
    # a metric that looked the key up live would score an old run against a new
    # answer. Empty on every run made before Phase 23. D-097.
    expected_answers: list[str] = field(default_factory=list)

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def new_run_id(now: datetime | None = None) -> str:
    """A sortable name for a run, e.g. "2026-08-04T1530Z".

    Time rather than a counter: runs happen on branches and on other machines,
    and two people numbering runs 03 independently is a collision waiting to
    happen.
    """
    stamp = now or datetime.now(UTC)
    return stamp.strftime("%Y-%m-%dT%H%MZ")


def write_run(
    meta: RunMeta, records: list[EvalRecord], runs_dir: Path = RUNS_DIR
) -> Path:
    """Write one run to eval/runs/<run_id>/ and return the directory.

    JSON Lines for the records -- one self-contained object per line -- because
    a run can then be diffed, filtered with any tool, and appended to while it
    is still going, none of which a single JSON array allows.
    """
    directory = runs_dir / meta.run_id
    directory.mkdir(parents=True, exist_ok=True)

    (directory / "meta.json").write_text(
        json.dumps(asdict(meta), indent=2) + "\n", encoding="utf-8"
    )
    lines = (json.dumps(asdict(record), ensure_ascii=False) for record in records)
    (directory / "records.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return directory


def read_records(directory: Path) -> list[EvalRecord]:
    """Load a run's records back, for comparing it against another run."""
    path = directory / "records.jsonl"
    records: list[EvalRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        raw["retrieved"] = [Retrieved(**item) for item in raw["retrieved"]]
        raw["citations"] = [CitationRef(**item) for item in raw["citations"]]
        records.append(EvalRecord(**raw))
    return records
