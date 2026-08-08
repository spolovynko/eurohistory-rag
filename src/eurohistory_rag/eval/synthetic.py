"""Turning chunks into questions, so the eval is bigger than thirty.

The golden set in `questions.toml` is thirty hand-written questions, twenty-four
of them answerable. One question is worth 4.2 points, which is why Phase 9
needed a twelve-configuration sweep to establish that a 4.2-point move was a
curve and not noise. This module buys sample size: a model reads a chunk and
writes a question that chunk answers, so the answer key comes free -- it is the
section the chunk was cut from.

**These questions are easier than real ones and the number they produce is not
comparable to the golden set's.** A question written from a passage borrows the
passage's vocabulary, so it is closer to Phase 7's "easy" kind than to its
"paraphrase" kind, and its answer key names one section where a hand-written
question names two or three. Read a synthetic score as a regression alarm --
"did this change break something in the long tail" -- never as a quality
verdict. The golden set stays the quality verdict, and stays hand-written.
"""

import logging
import random
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from eurohistory_rag.eval.questions import Question, load_questions
from eurohistory_rag.generation.client import (
    GenerationUnavailable,
    Generator,
    complete,
)
from eurohistory_rag.generation.messages import Message

logger = logging.getLogger(__name__)

# How many questions to ask for. Enough that one question is worth 0.7 points
# rather than 4.2, and small enough that a full run is a few minutes and a few
# cents rather than an afternoon.
DEFAULT_COUNT = 150

# Chunks shorter than this hold a heading and a sentence. A question written
# from one has almost nothing to be about.
MIN_CHUNK_CHARS = 400

# Fixed, so the same corpus yields the same sample. Regenerating the set with a
# different sample would make two runs incomparable for a reason that has
# nothing to do with the system.
SAMPLE_SEED = 20261005

# The word the model writes when a passage holds no fact worth asking about.
# This is the filter for the 389 list-shaped chunks Phase 4 counted and left
# alone -- twin towns, book titles, film credits. They are still in the corpus;
# they just should not become test questions.
SKIP = "SKIP"

INSTRUCTIONS = """\
You write evaluation questions for a search system over Wikipedia articles \
about 20th and 21st century European history.

You will be given one passage. Write ONE question that this passage answers.

Rules:
- The question must be answerable from the passage alone.
- The question must stand on its own. Name the treaty, person, country or \
event explicitly -- a reader who has never seen the passage must know what is \
being asked about.
- Never refer to "the passage", "the text", "this article" or "the source".
- Do not copy a sentence from the passage and add a question mark. Ask about \
what the passage says, in your own words.
- One sentence, ending in a question mark. No preamble, no quotation marks.
- If the passage is a list, a set of credits, a table of names, or holds no \
factual claim worth asking about, reply with exactly: SKIP

Reply with the question and nothing else.\
"""

# Phrases that give away a question written *about a passage* rather than about
# the world. A question containing one of these cannot be asked by a user, so
# it cannot measure anything a user would experience.
BANNED = (
    "the passage",
    "this passage",
    "the text",
    "this text",
    "the article",
    "this article",
    "the excerpt",
    "the source",
    "the document",
    "mentioned above",
    "described above",
)

# Shortest and longest a usable question can be.
MIN_QUESTION_CHARS = 25
MAX_QUESTION_CHARS = 220

# A question sharing this many consecutive words with its chunk was copied
# rather than written. Six is long enough that ordinary phrases ("the Treaty of
# Versailles was signed") do not trip it.
COPY_WINDOW = 6

_WORD = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True, slots=True)
class SourceChunk:
    """One Gold chunk, reduced to what question-writing needs."""

    chunk_id: str
    doc_id: str
    title: str
    heading: str
    text: str

    @property
    def source(self) -> str:
        """Human-readable location, the same form SearchResult uses."""
        return f"{self.title} — {self.heading}" if self.heading else self.title


def sample_chunks(
    frame: pl.DataFrame,
    count: int = DEFAULT_COUNT,
    seed: int = SAMPLE_SEED,
    min_chars: int = MIN_CHUNK_CHARS,
) -> list[SourceChunk]:
    """Pick `count` chunks, at most one per article, deterministically.

    One per article is the whole sampling rule and it is a deliberate bias.
    Long articles hold fifty chunks and short ones hold three, so sampling
    chunks uniformly would ask most of the questions about Berlin and Moscow
    and none about the treaties. Spreading across articles tests the corpus
    rather than its longest members.
    """
    usable = frame.filter(pl.col("text").str.len_chars() >= min_chars)
    rows = usable.select("chunk_id", "doc_id", "page_id", "title", "heading", "text")

    by_article: dict[int, list[dict[str, object]]] = {}
    for row in rows.iter_rows(named=True):
        by_article.setdefault(int(row["page_id"]), []).append(row)

    rng = random.Random(seed)
    picked = [rng.choice(chunks) for _, chunks in sorted(by_article.items())]
    rng.shuffle(picked)

    return [
        SourceChunk(
            chunk_id=str(row["chunk_id"]),
            doc_id=str(row["doc_id"]),
            title=str(row["title"]),
            heading=str(row["heading"]),
            text=str(row["text"]),
        )
        for row in picked[:count]
    ]


def build_messages(chunk: SourceChunk) -> list[Message]:
    """The two messages that ask for one question."""
    passage = f"# {chunk.source}\n\n{chunk.text}"
    return [
        {"role": "system", "content": INSTRUCTIONS},
        {"role": "user", "content": passage},
    ]


def _words(text: str) -> list[str]:
    """Lowercased word-ish tokens, for the copy check."""
    return _WORD.findall(text.lower())


def copies_source(question: str, chunk_text: str, window: int = COPY_WINDOW) -> bool:
    """Does the question lift `window` consecutive words straight out of the chunk?

    A copied sentence with a question mark on the end tests string matching,
    not retrieval: every search method finds it, so the question separates
    nothing.
    """
    asked = _words(question)
    if len(asked) < window:
        return False
    source = " ".join(_words(chunk_text))
    return any(
        " ".join(asked[i : i + window]) in source
        for i in range(len(asked) - window + 1)
    )


def usable(question: str, chunk: SourceChunk) -> bool:
    """Is this a question a person could have asked?

    Four cheap deterministic checks, run before anything is written to disk.
    They cost no model call and they are the reason the generation prompt can
    stay short: a rule the code can enforce does not need to be argued for in
    English as well.
    """
    text = question.strip()
    lowered = text.lower()
    return (
        text.endswith("?")
        and MIN_QUESTION_CHARS <= len(text) <= MAX_QUESTION_CHARS
        and not any(phrase in lowered for phrase in BANNED)
        and not copies_source(text, chunk.text)
    )


def question_id(chunk: SourceChunk) -> str:
    """A stable id that names the chunk it came from, e.g. "syn-30030-1-4"."""
    return "syn-" + chunk.chunk_id.replace(":", "-")


def to_question(text: str, chunk: SourceChunk) -> Question:
    """One accepted question, with the chunk's section as its answer key.

    The answer key is a single section where a hand-written question lists two
    or three, so coverage@5 means something different here and recall@5 is a
    stricter test. Recorded in `note` so a reader of the file knows where the
    ground truth came from without asking.
    """
    return Question(
        id=question_id(chunk),
        kind="synthetic",
        text=text.strip(),
        expected=(chunk.doc_id,),
        note=f"generated from {chunk.chunk_id} ({chunk.source})",
    )


@dataclass(frozen=True, slots=True)
class GenerationReport:
    """What one generation pass produced, and what it threw away."""

    questions: tuple[Question, ...]
    skipped: int
    rejected: int
    failed: int


def generate(chunks: Sequence[SourceChunk], generator: Generator) -> GenerationReport:
    """Write one question per chunk, dropping the ones that fail the rules.

    A model failure is counted rather than raised, for the same reason the eval
    runner records one: one unreachable call should not throw away the hundred
    and forty questions already written.
    """
    accepted: list[Question] = []
    skipped = failed = rejected = 0

    for position, chunk in enumerate(chunks, start=1):
        try:
            completion = complete(generator, build_messages(chunk))
        except GenerationUnavailable as error:
            logger.warning("%s: generation failed: %s", chunk.chunk_id, error)
            failed += 1
            continue

        text = completion.text.strip()
        if text.upper().startswith(SKIP):
            skipped += 1
        elif not usable(text, chunk):
            logger.info("%s: rejected %r", chunk.chunk_id, text)
            rejected += 1
        else:
            accepted.append(to_question(text, chunk))

        if position % 25 == 0:
            logger.info("[%d/%d] %d accepted", position, len(chunks), len(accepted))

    return GenerationReport(
        questions=tuple(accepted),
        skipped=skipped,
        rejected=rejected,
        failed=failed,
    )


def _quote(value: str) -> str:
    """A TOML basic string, with the two characters that can break one escaped."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render(questions: Iterable[Question], model: str) -> str:
    """The question set as TOML, in the same shape as the golden set.

    Same shape on purpose: `load_questions` validates both, `evaluate --questions`
    runs either, and the two files can never drift into different formats.
    """
    lines = [
        "# Generated questions -- NOT the golden set.",
        "#",
        "# Written by " + model + " from single Gold chunks, one question per",
        "# chunk, at most one chunk per article. `expected` is the section the",
        "# chunk was cut from, so the answer key is free and also narrower than a",
        "# hand-written one.",
        "#",
        "# These are systematically easier than the thirty in questions.toml: a",
        "# question written from a passage borrows the passage's words. Use them",
        "# to notice a regression, never to judge quality. Regenerating this file",
        "# invalidates comparisons against runs made with the old one.",
        "",
    ]
    for question in questions:
        lines += [
            "[[question]]",
            f"id = {_quote(question.id)}",
            f"kind = {_quote(question.kind)}",
            f"text = {_quote(question.text)}",
            "expected = [" + ", ".join(_quote(e) for e in question.expected) + "]",
            f"note = {_quote(question.note)}",
            "",
        ]
    return "\n".join(lines)


def write(path: Path, questions: Sequence[Question], model: str) -> Path:
    """Write the set, then read it back through the validator.

    The read-back is the point. Writing TOML by hand is one quoting mistake
    away from a file that loads as something subtly different, and the failure
    would surface as an unexplained recall drop halfway through a run rather
    than here.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(questions, model), encoding="utf-8")
    load_questions(path)
    return path
