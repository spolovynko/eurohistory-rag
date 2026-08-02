"""The Qdrant wrapper, against an in-process Qdrant.

`QdrantClient(":memory:")` runs the real thing inside the test process, so these
exercise actual Qdrant behaviour with no Docker and no network. The property
most of them are circling is idempotency: running `index` twice must leave the
collection exactly as one run would.
"""

from typing import Any

from eurohistory_rag.retrieval.vectorstore import VectorStore, point_id

DIMENSIONS = 3

# --- helpers ----------------------------------------------------------------


def store() -> VectorStore:
    """A fresh, empty collection for one test."""
    created = VectorStore.in_memory("chunks", DIMENSIONS)
    created.ensure_collection(recreate=True)
    return created


def payload(chunk_id: str, title: str = "Marshall Plan") -> dict[str, Any]:
    return {"chunk_id": chunk_id, "title": title}


# --- point ids --------------------------------------------------------------


def test_the_same_chunk_id_always_gives_the_same_point_id() -> None:
    """The whole basis of a safe re-run: a chunk lands on the same point twice."""
    assert point_id("30030:1:4") == point_id("30030:1:4")


def test_different_chunks_get_different_point_ids() -> None:
    assert point_id("30030:1:4") != point_id("30030:1:5")


# --- the collection ---------------------------------------------------------


def test_ensure_collection_is_safe_to_call_twice() -> None:
    created = VectorStore.in_memory("chunks", DIMENSIONS)
    created.ensure_collection()
    created.ensure_collection()
    assert created.count() == 0


def test_ensure_collection_without_recreate_keeps_what_is_stored() -> None:
    kept = store()
    kept.upsert(["a"], [[1.0, 0.0, 0.0]], [payload("a")])
    kept.ensure_collection()
    assert kept.count() == 1


def test_recreate_empties_the_collection() -> None:
    """Why `index` recreates by default: chunk ids move, so old points must go."""
    emptied = store()
    emptied.upsert(["a"], [[1.0, 0.0, 0.0]], [payload("a")])
    emptied.ensure_collection(recreate=True)
    assert emptied.count() == 0


# --- writing ----------------------------------------------------------------


def test_a_batch_is_stored_and_counted() -> None:
    written = store()
    written.upsert(
        ["a", "b"],
        [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        [payload("a"), payload("b")],
    )
    assert written.count() == 2


def test_writing_the_same_chunks_again_does_not_duplicate_them() -> None:
    """Idempotency, stated directly: the second run adds nothing."""
    twice = store()
    for _ in range(2):
        twice.upsert(
            ["a", "b"], [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], [payload("a"), payload("b")]
        )
    assert twice.count() == 2


def test_writing_a_chunk_again_replaces_its_payload() -> None:
    replaced = store()
    replaced.upsert(["a"], [[1.0, 0.0, 0.0]], [payload("a", title="Old title")])
    replaced.upsert(["a"], [[1.0, 0.0, 0.0]], [payload("a", title="New title")])
    hits = replaced.search([1.0, 0.0, 0.0], limit=1)
    assert hits[0].payload["title"] == "New title"


# --- resume -----------------------------------------------------------------


def test_has_all_is_false_before_anything_is_written() -> None:
    assert store().has_all(["a", "b"]) is False


def test_has_all_is_false_when_only_part_of_the_batch_is_stored() -> None:
    """A half-written batch must be redone, not skipped."""
    partial = store()
    partial.upsert(["a"], [[1.0, 0.0, 0.0]], [payload("a")])
    assert partial.has_all(["a", "b"]) is False


def test_has_all_is_true_once_the_whole_batch_is_stored() -> None:
    complete = store()
    complete.upsert(
        ["a", "b"], [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], [payload("a"), payload("b")]
    )
    assert complete.has_all(["a", "b"]) is True


# --- searching --------------------------------------------------------------


def test_search_on_an_empty_collection_returns_nothing() -> None:
    assert store().search([1.0, 0.0, 0.0], limit=5) == []


def test_search_returns_the_nearest_first() -> None:
    searched = store()
    searched.upsert(
        ["far", "near"],
        [[0.0, 1.0, 0.0], [1.0, 0.0, 0.0]],
        [payload("far"), payload("near")],
    )
    hits = searched.search([1.0, 0.0, 0.0], limit=2)
    assert [hit.payload["chunk_id"] for hit in hits] == ["near", "far"]
    assert hits[0].score > hits[1].score


def test_search_returns_at_most_the_limit() -> None:
    limited = store()
    limited.upsert(
        ["a", "b", "c"],
        [[1.0, 0.0, 0.0], [0.9, 0.1, 0.0], [0.8, 0.2, 0.0]],
        [payload("a"), payload("b"), payload("c")],
    )
    assert len(limited.search([1.0, 0.0, 0.0], limit=2)) == 2


def test_a_hit_carries_its_payload_and_not_a_qdrant_object() -> None:
    """The boundary: nothing outside this module should see Qdrant's types."""
    searched = store()
    searched.upsert(["a"], [[1.0, 0.0, 0.0]], [payload("a")])
    hit = searched.search([1.0, 0.0, 0.0], limit=1)[0]
    assert hit.payload == {"chunk_id": "a", "title": "Marshall Plan"}
    assert isinstance(hit.score, float)
