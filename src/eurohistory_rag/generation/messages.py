"""Turns a question and its chunks into the messages the model receives.

The standing rules live next door in system_prompt.md, as text rather than
Python string: the prompt is edited far more often than this code is, and a
markdown file diffs and renders better than a triple-quoted constant.
"""

from collections.abc import Sequence
from importlib.resources import files
from typing import Literal, TypedDict

from eurohistory_rag.retrieval.search import SearchResult

SYSTEM_PROMPT = (
    files("eurohistory_rag.generation")
    .joinpath("system_prompt.md")
    .read_text(encoding="utf-8")
)


class Message(TypedDict):
    """One turn of the conversation sent to the model."""

    role: Literal["system", "user"]
    content: str


def format_source(number: int, result: SearchResult) -> str:
    """One chunk as a source block the model can cite by number.

    The label is a small number rather than the real chunk id because short
    labels are mistyped far less often -- the caller keeps the mapping back.
    """
    title = result.source.replace('"', "'")
    return f'<source id="{number}" title="{title}">\n{result.text}\n</source>'


def format_sources(results: Sequence[SearchResult]) -> str:
    """Every chunk as one numbered block, or the line that says there were none.

    Shared with the verification pass, which must show the checker exactly what
    the writer saw. Two copies of this would drift, and a checker grading an
    answer against different evidence is not checking anything.
    """
    blocks = [format_source(n, r) for n, r in enumerate(results, start=1)]
    return "\n\n".join(blocks) if blocks else "No sources were found."


def build_messages(question: str, results: Sequence[SearchResult]) -> list[Message]:
    """The two messages that make up one question.

    Sources first and the question last: a model reads the end of a long
    message hardest, and five chunks is long. Sources stay in plain rank order
    so that reordering them stays a Phase 8 experiment with a clean before.
    """
    user = f"{format_sources(results)}\n\n# QUESTION\n\n{question}"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
