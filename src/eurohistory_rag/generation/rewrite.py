"""Turning a follow-up back into a question.

The second turn of a conversation is not a question. "When did it come down?"
has no subject, so the vector built from it is a vector of nothing in
particular, and the corpus answers with whatever else in Europe came down. This
module puts the subject back before anything is embedded.

Query rewriting rather than embedding the whole history, and the reason is what
an embedding is: one vector for the whole input, so a paragraph about the Berlin
Wall plus five words about its fall averages out to a vector mostly about the
Berlin Wall being built. Rewriting keeps the search pointed at the thing
actually being asked. It also keeps every downstream stage -- retrieval, the
answer prompt, citations, every metric -- receiving exactly one self-contained
question, which is what makes this change measurable at all.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.resources import files

from eurohistory_rag.generation.client import (
    GenerationUnavailable,
    Generator,
    complete,
)
from eurohistory_rag.generation.messages import Message

logger = logging.getLogger(__name__)

REWRITE_PROMPT = (
    files("eurohistory_rag.generation")
    .joinpath("rewrite_prompt.md")
    .read_text(encoding="utf-8")
)

# How many previous exchanges the rewriter is shown. Two, because a pronoun
# almost always points at the turn immediately above it, and every turn past
# that is another chance to resolve "it" to the wrong thing. This is the context
# window decision, and it is made by dropping the oldest turns rather than by
# summarising them: a summary is a second model call whose errors would be
# invisible, where a dropped turn fails in the open as an unresolved pronoun.
HISTORY_TURNS = 2

# An assistant answer runs to a couple of thousand characters and only its
# nouns matter here. Truncating keeps the rewrite prompt small and cheap; the
# names a follow-up points at are near the front, because that is where an
# answer states its subject.
ANSWER_CHARS = 600

# A rewritten question longer than this is not a rewrite. The failure to guard
# against is the model answering the question or explaining itself, and both are
# long; the longest question in eval/questions.toml is 118 characters.
MAX_QUESTION_CHARS = 300


@dataclass(frozen=True, slots=True)
class Turn:
    """One completed exchange, as everything below the question file sees it.

    Both halves, because a follow-up can point at either: "how did the Soviets
    respond?" refers to what was asked, and "what happened to him?" refers to a
    name that appears only in what was answered.
    """

    user: str
    assistant: str


def build_messages(question: str, history: Sequence[Turn]) -> list[Message]:
    """The rewrite request: the recent conversation, then the message to rewrite.

    The last message is labelled and comes last, so the model cannot mistake it
    for another turn to be summarised -- position is the strongest instruction
    there is, which is the same reason the answer prompt puts its question at
    the end rather than at the top.
    """
    lines = []
    for turn in history[-HISTORY_TURNS:]:
        lines.append(f"user: {turn.user}")
        lines.append(f"assistant: {turn.assistant[:ANSWER_CHARS]}")
    lines.append(f"last message: {question}")
    return [
        {"role": "system", "content": REWRITE_PROMPT},
        {"role": "user", "content": "\n".join(lines)},
    ]


def clean(rewritten: str, question: str) -> str:
    """The model's output as a question, or the original when it is not one.

    Every rejection here falls back to the question the reader actually typed.
    That is the safe direction: an unresolved follow-up retrieves badly, which
    is the failure this phase started from, while a rewrite nobody checked can
    retrieve confidently for a question nobody asked.
    """
    text = rewritten.strip().strip('"').strip()
    if not text or len(text) > MAX_QUESTION_CHARS or "\n" in text:
        logger.warning("rewrite rejected for %r: %r", question, rewritten)
        return question
    return text


def rewrite(generator: Generator, question: str, history: Sequence[Turn]) -> str:
    """The follow-up as a question that stands on its own.

    Returns the question unchanged if the model cannot be reached. A
    conversation that degrades to single-turn retrieval is worse than one that
    works; a conversation that returns 503 because the *rewriter* was down,
    while the corpus and the answering model were both fine, is worse than
    either.
    """
    if not history:
        return question
    try:
        completion = complete(generator, build_messages(question, history))
    except GenerationUnavailable as failure:
        logger.warning("rewrite unavailable for %r: %s", question, failure)
        return question

    standalone = clean(completion.text, question)
    if standalone != question:
        logger.info("rewrote %r -> %r", question, standalone)
    return standalone
