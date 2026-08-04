"""Turns a question and its chunks into the messages the model receives.

The standing rules live next door in prompt.md, as text rather than as a
Python string: the prompt is edited far more often than this code is, and a
markdown file diffs and renders better than a triple-quoted constant.
"""

from collections.abc import Sequence
from importlib.resources import files
from typing import Literal, TypedDict

from eurohistory_rag.retrieval.search import SearchResult

SYSTEM_PROMPT = (
    files("eurohistory_rag.generation")
    .joinpath("prompt.md")
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


def build_messages(question: str, results: Sequence[SearchResult]) -> list[Message]:
    """The two messages that make up one question.

    Sources first and the question last: a model reads the end of a long
    message hardest, and five chunks is long. Sources stay in plain rank order
    so that reordering them stays a Phase 8 experiment with a clean before.
    """
    blocks = [format_source(n, r) for n, r in enumerate(results, start=1)]
    sources = "\n\n".join(blocks) if blocks else "No sources were found."
    user = f"{sources}\n\n# QUESTION\n\n{question}"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
