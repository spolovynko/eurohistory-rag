"""The question set and its ground truth.

Hand-written data, not code, for the same reason corpus/seeds.toml is: it is
edited by a person between runs, and it has to be reviewable in a diff. The
answer key lives beside each question rather than in a second file, because a
question and the sections that should answer it are one decision.
"""

import logging
import tomllib
from collections.abc import Collection
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

logger = logging.getLogger(__name__)

# The committed question set. Rewriting it invalidates every earlier run, so
# runs record the git sha that produced them.
QUESTIONS_PATH = Path("eval/questions.toml")

# The four kinds Phase 7 requires, and how many of each it asks for. Not
# enforced -- a set of 29 should still run -- but reported, so a set that has
# drifted away from the plan says so out loud.
#
# "synthetic" is Phase 10's fifth kind and belongs to a different file. It is a
# kind rather than a separate model so that one loader, one validator and one
# runner serve both sets -- but a synthetic question is easier than any of the
# four above and its score is not comparable to theirs, which is why it has its
# own name in every table it appears in. See eval/synthetic.py.
Kind = Literal["easy", "multi", "paraphrase", "unanswerable", "synthetic"]
TARGET_COUNTS: dict[Kind, int] = {
    "easy": 8,
    "multi": 8,
    "paraphrase": 8,
    "unanswerable": 6,
}

# Which batch a question was written in. "golden" is Phase 7's original thirty,
# about a corpus that ran 1914-1945; "extended" is Phase 15's thirty, written
# after the corpus grew to 1914-2024; "temporal" is Phase 22's eighteen, every
# one of which names a period the corpus covers in several places at once.
#
# This exists so one run can be scored twice: the golden thirty alone, which
# reproduces every earlier baseline, and the whole set. Phase 14 grew the corpus
# 81% and no number moved, because the questions all described the old third of
# it -- and that was only visible per question, never in the total. Splitting
# the table is what makes it visible in the total. D-087.
#
# The default is "golden" so the original thirty stay byte-identical: only the
# new questions carry the line. A synthetic set names itself, because its kind
# already decides the answer and a file nobody hand-edits should not have to
# repeat it.
Suite = Literal[
    "golden", "extended", "temporal", "factual", "conversation", "synthetic"
]

# The shape each hand-written suite is meant to have. Phase 7's 8/8/8/6 applies
# to the two suites written to that plan; the temporal eighteen were written to
# a different one and say so here rather than tripping a warning on every run.
# A suite absent from this table is not checked at all -- a synthetic set is 150
# questions of one kind by design.
SUITE_TARGETS: dict[Suite, dict[Kind, int]] = {
    "golden": TARGET_COUNTS,
    "extended": TARGET_COUNTS,
    # No paraphrase row: rewording is what the extended suite tests, and a
    # temporal question already is a paraphrase of the heading it must find.
    # 7 multi and 1 unanswerable rather than 6 and 2: t-pandemic-2020 was
    # written as unanswerable, the corpus answers it perfectly well, and it was
    # reclassified after the D-096 comparison closed. The count records the
    # correction rather than hiding it.
    "temporal": {"easy": 10, "multi": 7, "paraphrase": 0, "unanswerable": 1},
    # All fourteen are single-article lookups of one stated value, so they are
    # all "easy" by Phase 7's definition. The split that matters here is not the
    # kind but whether the fact is in the prose (5) or only in the infobox (9),
    # and that is `expected_answer` plus the note, not a column. D-097.
    "factual": {"easy": 14, "multi": 0, "paraphrase": 0, "unanswerable": 0},
    # Ten referential follow-ups, three controls whose text is copied verbatim
    # from a question already in the file, and one whose answer the corpus does
    # not hold. The kinds describe the *resolved* question -- "how did the
    # Soviets respond" is an easy single-article lookup once you know what it
    # refers to, and the whole phase is about that "once you know". D-098.
    "conversation": {"easy": 8, "multi": 4, "paraphrase": 1, "unanswerable": 1},
}

# Silver builds doc_ids as "{page_id}:{position}". Checking the shape on load
# catches a mistyped key without this module having to open the corpus.
DocId = Annotated[str, Field(pattern=r"^\d+:\d+$")]


class Turn(BaseModel):
    """One completed exchange that happened before the question being scored.

    Both halves, because a follow-up can point at either: "how did the Soviets
    respond?" refers to what was asked, and "what happened to him?" refers to a
    name that appears only in what was answered.

    The assistant text in eval/questions.toml is a real answer this system gave,
    captured from the running system rather than written by hand. An invented
    answer would be an easier thing to resolve a pronoun against than the one a
    reader actually sees, and the eval would flatter the feature it is testing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    user: str = Field(min_length=1)
    assistant: str = Field(min_length=1)


class Question(BaseModel):
    """One evaluation question and the sections that should answer it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Stable across edits: run directories are keyed on it, so renumbering
    # would break every comparison against an earlier run.
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    kind: Kind
    text: str = Field(min_length=1)
    expected: tuple[DocId, ...] = Field(default=())
    # The written forms that count as stating the fact this question asks for.
    # Empty for every question that asks for an explanation rather than a value
    # -- recall and coverage already say whether those found the right section.
    # A question that asks "how large was West Germany" is not answered by
    # retrieving the right article, only by the answer containing 248,717, and
    # no rank-based metric can see the difference. D-097.
    expected_answer: tuple[str, ...] = Field(default=())
    # The exchange that came before, oldest first. Empty for all 92 questions
    # written before Phase 24, which is what keeps them single-turn and
    # byte-identical: a question with no history is asked exactly as it always
    # was, by every caller, with or without the rewriter. D-098.
    history: tuple[Turn, ...] = Field(default=())
    suite: Suite = "golden"
    note: str = ""

    @model_validator(mode="before")
    @classmethod
    def _synthetic_names_its_own_suite(cls, data: Any) -> Any:
        """A generated question belongs to the generated set, always.

        Decided here rather than in the generated file so that a set written
        before this field existed still labels itself correctly on load.
        """
        if isinstance(data, dict) and data.get("kind") == "synthetic":
            return {**data, "suite": "synthetic"}
        return data

    @model_validator(mode="after")
    def _ground_truth_matches_kind(self) -> "Question":
        """An answerable question without an answer key measures nothing.

        And an unanswerable one with a key is a contradiction: the whole point
        of those six is that nothing in the corpus should come back.
        """
        if self.kind == "unanswerable":
            if self.expected:
                raise ValueError(f"{self.id}: unanswerable question has expected ids")
        elif not self.expected:
            raise ValueError(f"{self.id}: answerable question has no expected ids")
        return self

    @model_validator(mode="after")
    def _history_matches_suite(self) -> "Question":
        """A conversation question has an exchange before it; nothing else does.

        Both halves matter. A conversation case without history is a single-turn
        question hiding in the suite that measures follow-ups, and a history
        attached to any other suite would silently move a question the golden,
        extended, temporal and factual tables are the control for.
        """
        if self.suite == "conversation" and not self.history:
            raise ValueError(f"{self.id}: conversation question has no history")
        if self.suite != "conversation" and self.history:
            raise ValueError(f"{self.id}: history outside the conversation suite")
        return self


class _QuestionFile(BaseModel):
    """The file as a whole, so the top-level shape is validated too."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    question: tuple[Question, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _ids_are_unique(self) -> "_QuestionFile":
        """Two questions sharing an id would overwrite each other's record."""
        ids = [q.id for q in self.question]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate question ids: {', '.join(duplicates)}")
        return self


def load_questions(path: Path = QUESTIONS_PATH) -> tuple[Question, ...]:
    """Parse eval/questions.toml, in file order.

    Validation happens here and only here, so a Question built anywhere else
    -- in a test, in a scratch script -- cannot skip the ground-truth rules.
    """
    with path.open("rb") as f:
        raw = tomllib.load(f)
    questions = _QuestionFile.model_validate(raw).question
    logger.info("questions: %s, %d loaded", path, len(questions))
    return questions


def counts(questions: Collection[Question]) -> dict[str, int]:
    """How many of each kind, for reporting the set against TARGET_COUNTS."""
    return {kind: sum(1 for q in questions if q.kind == kind) for kind in TARGET_COUNTS}


def unknown_doc_ids(
    questions: Collection[Question], known: Collection[str]
) -> dict[str, list[str]]:
    """Expected ids that are not in the corpus, per question id.

    The failure this exists for is silent: a mistyped doc_id can never be
    retrieved, so recall for that question is zero forever and the number looks
    like a retrieval problem. The caller supplies `known` because this module
    has no business knowing where the corpus is stored.
    """
    available = set(known)
    missing = {
        q.id: [doc_id for doc_id in q.expected if doc_id not in available]
        for q in questions
    }
    return {qid: ids for qid, ids in missing.items() if ids}
