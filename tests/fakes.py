"""Test doubles used across the suite.

`FakeEmbedder`, `FakeGenerator` and `FakeReranker` are the second
implementations of `Embedder`, `Generator` and `Reranker` that justify those
Protocols existing at all: they make every test that touches a model run with
no network, no API key, no downloaded weights and no cost.
"""

from collections.abc import Sequence

from eurohistory_rag.generation.client import Completion, GenerationUnavailable
from eurohistory_rag.generation.messages import Message
from eurohistory_rag.retrieval.rerank import RerankUnavailable

# A tiny fixed vocabulary. Real embeddings come from a trained model; these come
# from counting words, which is enough to give texts sharing words a similar
# direction and texts sharing none an unrelated one.
VOCABULARY = (
    "marshall",
    "plan",
    "berlin",
    "blockade",
    "treaty",
    "rome",
    "wall",
    "cold",
)


class FakeEmbedder:
    """An Embedder backed by word counts instead of a model."""

    def __init__(self, vocabulary: Sequence[str] = VOCABULARY) -> None:
        self._vocabulary = tuple(vocabulary)
        self.calls: list[list[str]] = []

    @property
    def dimensions(self) -> int:
        """One slot per vocabulary word, plus the constant tail."""
        return len(self._vocabulary) + 1

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one vector per text, recording the call so tests can inspect it."""
        self.calls.append(list(texts))
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        """Word counts, with a constant 1.0 on the end.

        The constant keeps the vector non-zero: cosine distance is undefined for
        an all-zero vector, and a test text using none of the vocabulary would
        otherwise produce one.
        """
        words = text.lower().split()
        return [*(float(words.count(term)) for term in self._vocabulary), 1.0]


class FakeGenerator:
    """A Generator that returns a canned answer instead of calling a model.

    Every test of the answer path runs against this: the interesting behaviour
    in generation is what we do with the model's text, not what the model
    writes, and a real call would be slow, paid and different every time.
    """

    def __init__(
        self,
        answer: str = "The wall went up in 1961 [1].",
        model: str = "fake-model",
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
    ) -> None:
        self._answer = answer
        self._model = model
        # Off unless a test asks. The default stays None because a fake cannot
        # know a real cost, and inventing one would let a test pass against a
        # number this code never measured. Phase 13 opts in, because the answer
        # path now makes two calls and the totalling is ours to get wrong.
        self._prompt_tokens = prompt_tokens
        self._completion_tokens = completion_tokens
        self.calls: list[list[Message]] = []

    @property
    def model(self) -> str:
        """The model name recorded on every answer."""
        return self._model

    def generate(self, messages: Sequence[Message]) -> Completion:
        """Return the canned answer, recording the messages it was given."""
        self.calls.append(list(messages))
        return Completion(
            text=self._answer,
            prompt_tokens=self._prompt_tokens,
            completion_tokens=self._completion_tokens,
        )


class ScriptedGenerator:
    """A Generator that returns a different canned answer on each call.

    Phase 10 needs it: writing a question set and judging an answer are both
    loops of one call per item, and a fake with a single fixed reply cannot
    tell a loop that ran three times from one that ran once and repeated
    itself.
    """

    def __init__(self, replies: Sequence[str], model: str = "fake-judge") -> None:
        self._replies = list(replies)
        self._model = model
        self.calls: list[list[Message]] = []

    @property
    def model(self) -> str:
        """The model name recorded on every answer."""
        return self._model

    def generate(self, messages: Sequence[Message]) -> Completion:
        """Return the next scripted reply, failing loudly when they run out.

        Running out is a test bug worth an exception rather than a repeat: a
        silent wrap-around would let a test assert a count the code never
        produced.
        """
        self.calls.append(list(messages))
        if len(self.calls) > len(self._replies):
            raise AssertionError(
                f"ScriptedGenerator: call {len(self.calls)} of {len(self._replies)}"
            )
        return Completion(text=self._replies[len(self.calls) - 1])


class FakeReranker:
    """A Reranker that scores by counting a term instead of running a model.

    Its opinion is deliberately unrelated to FakeEmbedder's: a reranking test is
    only meaningful when the two disagree, because agreement cannot distinguish
    "the reranker reordered the list" from "the reranker was never called".
    """

    def __init__(self, term: str = "wall") -> None:
        self._term = term
        self.calls: list[tuple[str, list[str]]] = []

    def rerank(self, query: str, documents: Sequence[str]) -> list[tuple[int, float]]:
        """Rank by how often `term` appears, recording what it was given."""
        self.calls.append((query, list(documents)))
        scored = [
            (index, float(document.lower().split().count(self._term)))
            for index, document in enumerate(documents)
        ]
        # Stable, so documents scoring equally keep the order the store gave
        # them -- the same tie-breaking a real reranker's caller relies on.
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored


class UnavailableReranker:
    """Stands in for a reranker whose model could not be loaded."""

    def rerank(self, query: str, documents: Sequence[str]) -> list[tuple[int, float]]:
        """Always fail, the way a missing model file does."""
        raise RerankUnavailable("model not loaded")


class UnavailableGenerator:
    """Stands in for a model that cannot be reached."""

    @property
    def model(self) -> str:
        """Named anyway: a failing generator still knows what it would call."""
        return "fake-model"

    def generate(self, messages: Sequence[Message]) -> Completion:
        """Always fail, the way an exhausted retry does."""
        raise GenerationUnavailable("connection refused")
