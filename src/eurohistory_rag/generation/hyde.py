"""Searching with a made-up answer instead of the question.

A question and an encyclopedia section are different kinds of text, and the
embedding model scores what a text is *about* together with how it is written.
"Why did people's money stop being worth anything?" is a spoken question with no
proper nouns in it; `Hyperinflation in the Weimar Republic — Causes` is written
prose full of names and years. They are about the same thing and they do not sit
near each other, which is D-106's finding stated as a cosine: a *different*
question about the same topic scored 0.7548 while the genuine rewording of it
scored 0.5695.

HyDE closes that gap from the query side. A model writes the passage it thinks
would answer the question, and *that* is embedded. The passage is a guess and is
often wrong in its details; it does not need to be right, because it is never
shown to anyone and never cited. It needs only to be the same *kind* of text as
the thing being looked for, so that the comparison stops being question-against-
document and becomes document-against-document.

**What this puts at risk, stated plainly.** Every other stage of this system
moves text that came from Wikipedia or from the reader. This one puts invented
text into the retrieval path. A hypothesis that wanders to the wrong country
retrieves the wrong country confidently, and no metric downstream can see that
the query was fabricated. That is the cost the phase is measuring, and it is why
`GenerationUnavailable` falls back to the reader's own question rather than to
anything cleverer.
"""

import logging
from dataclasses import dataclass
from importlib.resources import files

from eurohistory_rag.generation.client import (
    Completion,
    GenerationUnavailable,
    Generator,
    complete,
)
from eurohistory_rag.generation.messages import Message

logger = logging.getLogger(__name__)

HYDE_PROMPT = (
    files("eurohistory_rag.generation")
    .joinpath("hyde_prompt.md")
    .read_text(encoding="utf-8")
)

# A hypothesis longer than this is not a paragraph. The prompt asks for 60-100
# words; this is roughly double the top of that range, so it rejects the model
# answering at length or explaining itself while leaving an ordinary long
# paragraph alone. The corpus's own chunks run to about 1,000 characters, and a
# query much longer than a chunk is comparing a page against a paragraph.
MAX_HYPOTHESIS_CHARS = 1200

# Too short to be a passage. A one-line hypothesis is the failure mode where the
# model restates the question, which searches for exactly what we already had.
MIN_HYPOTHESIS_CHARS = 120


@dataclass(frozen=True, slots=True)
class Hypothesis:
    """What HyDE produced, and what should be embedded because of it.

    Both fields, and they are not the same string. `text` is what goes to the
    embedder; `passage` is the raw generation, kept so a run can be read
    afterwards to ask whether a bad retrieval came from a bad hypothesis. That
    question cannot be answered from the rank alone, and it is the only way to
    audit a query nobody typed.

    `used` is false when the model was unreachable or its output was rejected,
    in which case `text` is the reader's question unchanged. It exists so a
    metric can separate "HyDE searched and did no better" from "HyDE never ran",
    which Phase 29 learned the hard way costs a phase when it is missing.
    """

    text: str
    passage: str
    used: bool


def build_messages(question: str) -> list[Message]:
    """The hypothesis request: the standing instructions, then the question."""
    return [
        {"role": "system", "content": HYDE_PROMPT},
        {"role": "user", "content": f"Question: {question}"},
    ]


def clean(passage: str) -> str | None:
    """The generation as a passage, or None when it is not one.

    Rejection is on length alone, in both directions, because there is no
    honest check for the thing that actually matters. A hypothesis about the
    wrong country is well-formed prose of the right length, and the only
    instrument that can catch it is recall. Guarding what can be guarded and
    saying so beats a validator that implies more checking than it does.
    """
    text = " ".join(passage.split())
    if not MIN_HYPOTHESIS_CHARS <= len(text) <= MAX_HYPOTHESIS_CHARS:
        return None
    return text


def hypothesise(
    generator: Generator, question: str, keep_question: bool = True
) -> Hypothesis:
    """The text to search with for this question.

    `keep_question` prepends the reader's own words to the hypothesis rather
    than replacing them. The original paper embeds the hypothesis alone, and
    that is the pure form of the idea; keeping the question is a hedge, and it
    is a real trade rather than a free improvement. Alone, a hypothesis that
    wanders takes the search with it. Prepended, the question anchors the
    vector — and dilutes exactly the document-shaped signal that HyDE exists to
    add, because the question is the text we already know retrieves badly.

    It is an argument, so it is a parameter and the sweep decides it. Nothing
    else in this module has an opinion about which wins.

    Falls back to the question on any failure, which keeps a broken hypothesis
    writer at Phase 5's retrieval rather than at no retrieval.
    """
    try:
        completion: Completion = complete(generator, build_messages(question))
    except GenerationUnavailable as failure:
        logger.warning("hyde unavailable for %r: %s", question, failure)
        return Hypothesis(text=question, passage="", used=False)

    passage = clean(completion.text)
    if passage is None:
        logger.warning("hyde rejected for %r: %r", question, completion.text)
        # The rejected text is kept for reading afterwards but is not searched
        # with: a hypothesis that failed the only check there is has not earned
        # the query. The reader's question is the fallback everywhere here.
        return Hypothesis(text=question, passage=completion.text, used=False)

    text = f"{question}\n\n{passage}" if keep_question else passage
    return Hypothesis(text=text, passage=passage, used=True)
