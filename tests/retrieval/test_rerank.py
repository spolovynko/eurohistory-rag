"""Tests for the reranker's one behaviour that does not need the model.

Nothing here loads a cross-encoder. Every other test in this suite reaches the
reranker through a fake, which is why 839 of them pass with no model on disk --
and it is also why the import that pulls 4.7 GB of torch, CUDA and triton into
the process went eight phases without anything noticing. Phase 33.
"""

import sys
from typing import Any

import pytest

from eurohistory_rag.retrieval.rerank import LocalReranker, RerankUnavailable


def test_a_missing_sentence_transformers_is_a_rerank_failure_not_a_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Asking for a reranker the image does not carry must fail like a reranker.

    The default image drops `sentence-transformers`, so `RERANKER_ENABLED=true`
    in a container built without the `reranker` extra is a configuration a real
    user can reach. It has to arrive as `RerankUnavailable`, which /ready and
    the request path already know how to report, rather than as an ImportError
    escaping from the middle of a search.

    `sys.modules[...] = None` is the documented way to make an import fail: the
    import machinery treats a None entry as a negative cache hit and raises.
    Set here rather than relying on the package being absent, so this test says
    the same thing on a machine that has the extra installed.
    """
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)

    with pytest.raises(RerankUnavailable, match="reranker"):
        LocalReranker("BAAI/bge-reranker-base")


def test_no_documents_is_answered_without_touching_the_model() -> None:
    """An empty candidate list returns an empty ordering and calls nothing.

    Worth its own test because the short-circuit is what makes the reranker
    safe to leave wired into a path that sometimes retrieves nothing.
    """

    class _Unusable:
        def predict(self, *args: Any, **kwargs: Any) -> None:
            raise AssertionError("the model was called with no documents")

    reranker = LocalReranker.__new__(LocalReranker)
    reranker._model = _Unusable()

    assert reranker.rerank("anything", []) == []
