"""Re-ordering candidates with a cross-encoder.

The embedder scores a chunk without ever seeing the question -- every vector in
the store was computed at index time, months before anyone asked anything. This
is the one place the question and a chunk are read together. That is why it is
accurate, and why it only ever runs over a short candidate list.
"""

from collections.abc import Sequence
from typing import Protocol

# bge-reranker-base accepts 512 tokens for the query and document together.
# Chunks are ~1,000 characters, so nothing is truncated in practice; the
# constant is here so a larger chunk size fails visibly rather than silently.
MAX_LENGTH = 512


class RerankUnavailable(RuntimeError):
    """The reranker could not be loaded, or refused the request."""


class Reranker(Protocol):
    """Query plus candidates in, an ordering out."""

    def rerank(self, query: str, documents: Sequence[str]) -> list[tuple[int, float]]:
        """Return (index, score) pairs, most relevant first.

        Indices point back into `documents`, so the caller reorders its own
        objects and nothing here ever learns what a SearchResult is.
        """
        ...


class LocalReranker:
    """Reranker backed by a cross-encoder running in this process."""

    def __init__(self, model: str) -> None:
        """Load the model once. First run downloads ~280 MB and needs network.

        Loading here rather than per call because it takes seconds; the caller
        is expected to build this once and keep it, as dependencies.py does.
        """
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            raise RerankUnavailable(
                "sentence-transformers is not installed; "
                "install the 'reranker' extra to use a local reranker"
            ) from exc

        try:
            self._model = CrossEncoder(model, max_length=MAX_LENGTH)
        except OSError as exc:
            raise RerankUnavailable(f"could not load {model}: {exc}") from exc

    def rerank(self, query: str, documents: Sequence[str]) -> list[tuple[int, float]]:
        """Score every document against the query, best first."""
        if not documents:
            return []

        scores = self._model.predict(
            [(query, document) for document in documents],
            show_progress_bar=False,
        )
        scored = [(index, float(score)) for index, score in enumerate(scores)]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored
