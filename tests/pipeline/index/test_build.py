"""The Gold-to-Qdrant job, run end to end with a fake embedder and an
in-process Qdrant.

Everything `build` needs is passed in, so the whole job runs here with no
network, no API key and no Docker -- which is the payoff for `build` never
constructing its own embedder or store.
"""

import datetime as dt
from pathlib import Path

import pytest

from eurohistory_rag.pipeline.gold.store import Chunk, to_frame, write
from eurohistory_rag.pipeline.index.build import build, read_chunks, to_payload
from eurohistory_rag.retrieval.embedding import MAX_TEXTS_PER_REQUEST
from eurohistory_rag.retrieval.sparse import query_vector
from eurohistory_rag.retrieval.vectorstore import VectorStore
from tests.fakes import FakeEmbedder

# --- helpers ----------------------------------------------------------------


def chunk(position: int, text: str, page_id: int = 30030) -> Chunk:
    """A Gold chunk with every column populated."""
    return Chunk(
        chunk_id=f"{page_id}:1:{position}",
        doc_id=f"{page_id}:1",
        page_id=page_id,
        position=position,
        title="Marshall Plan",
        heading="Origins",
        text=text,
        themes=("reconstruction",),
        revision_id=100 + page_id,
        revision_timestamp=dt.datetime(2026, 7, 1, tzinfo=dt.UTC),
        license="CC BY-SA 4.0",
    )


def write_gold(root: Path, chunks: list[Chunk]) -> None:
    """Put a Gold table on disk where `build` will look for it."""
    write(root, to_frame(chunks))


def fresh_store(embedder: FakeEmbedder) -> VectorStore:
    return VectorStore.in_memory("chunks", embedder.dimensions)


# --- the payload ------------------------------------------------------------


def test_the_payload_holds_the_ten_fields_that_were_chosen(tmp_path: Path) -> None:
    """Whatever is missing here cannot be cited or filtered on later."""
    write_gold(tmp_path, [chunk(0, "Marshall plan aid to Europe.")])
    row = read_chunks(tmp_path).row(0, named=True)
    assert to_payload(row) == {
        "chunk_id": "30030:1:0",
        "doc_id": "30030:1",
        "page_id": 30030,
        "position": 0,
        "title": "Marshall Plan",
        "heading": "Origins",
        "text": "Marshall plan aid to Europe.",
        "themes": ["reconstruction"],
        "revision_id": 30130,
        "revision_timestamp": "2026-07-01T00:00:00+00:00",
    }


def test_the_licence_is_not_repeated_on_every_point(tmp_path: Path) -> None:
    """It is the same string on all 30,000 rows; the API states it once."""
    write_gold(tmp_path, [chunk(0, "Marshall plan aid to Europe.")])
    assert "license" not in to_payload(read_chunks(tmp_path).row(0, named=True))


# --- indexing ---------------------------------------------------------------


def test_every_chunk_becomes_a_point(tmp_path: Path) -> None:
    write_gold(tmp_path, [chunk(i, f"Marshall plan paragraph {i}.") for i in range(5)])
    embedder = FakeEmbedder()
    report = build(tmp_path, fresh_store(embedder), embedder, batch_size=2)
    assert report.indexed == 5
    assert report.skipped == 0
    assert report.points == 5


def test_chunks_are_embedded_in_batches_of_the_requested_size(tmp_path: Path) -> None:
    """The one place batch size is decided, so the one place worth asserting it."""
    write_gold(tmp_path, [chunk(i, f"Marshall plan paragraph {i}.") for i in range(5)])
    embedder = FakeEmbedder()
    build(tmp_path, fresh_store(embedder), embedder, batch_size=2)
    assert [len(call) for call in embedder.calls] == [2, 2, 1]


def test_a_stored_point_can_be_found_by_searching_for_its_own_words(
    tmp_path: Path,
) -> None:
    """End to end: text on disk, through the embedder, into the store, back out."""
    write_gold(
        tmp_path,
        [chunk(0, "Berlin blockade and the airlift."), chunk(1, "Treaty of Rome.")],
    )
    embedder = FakeEmbedder()
    store = fresh_store(embedder)
    build(tmp_path, store, embedder)

    hits = store.search(embedder.embed(["Berlin blockade"])[0], limit=1)
    assert hits[0].payload["text"] == "Berlin blockade and the airlift."


def test_a_stored_point_can_also_be_found_by_keyword(tmp_path: Path) -> None:
    """The guard against a sparse vector that is written but empty.

    `build` could pass an empty dict for every chunk and nothing else here
    would notice -- lint, types and every other test would stay green while the
    keyword half of hybrid search did nothing. That is precisely how Phase 8
    shipped a reranker that never ran.
    """
    write_gold(
        tmp_path,
        [chunk(0, "Berlin blockade and the airlift."), chunk(1, "Treaty of Rome.")],
    )
    embedder = FakeEmbedder()
    store = fresh_store(embedder)
    build(tmp_path, store, embedder)

    hits = store.search_sparse(query_vector("blockade"), limit=5)
    assert [hit.payload["text"] for hit in hits] == ["Berlin blockade and the airlift."]


# --- re-running -------------------------------------------------------------


def test_running_twice_leaves_the_same_number_of_points(tmp_path: Path) -> None:
    """Idempotency at the job level: a repeat run is a no-op on the result."""
    write_gold(tmp_path, [chunk(i, f"Marshall plan paragraph {i}.") for i in range(4)])
    embedder = FakeEmbedder()
    store = fresh_store(embedder)
    first = build(tmp_path, store, embedder)
    second = build(tmp_path, store, embedder)
    assert first.points == second.points == 4


def test_a_rebuild_drops_chunks_that_no_longer_exist(tmp_path: Path) -> None:
    """Re-chunking changes every chunk id, so the old points must not survive."""
    embedder = FakeEmbedder()
    store = fresh_store(embedder)

    write_gold(tmp_path, [chunk(i, f"Marshall plan paragraph {i}.") for i in range(4)])
    build(tmp_path, store, embedder)

    write_gold(tmp_path, [chunk(0, "One larger chunk of Marshall plan prose.")])
    assert build(tmp_path, store, embedder).points == 1


# --- resuming ---------------------------------------------------------------


def test_resume_skips_batches_already_stored(tmp_path: Path) -> None:
    write_gold(tmp_path, [chunk(i, f"Marshall plan paragraph {i}.") for i in range(4)])
    embedder = FakeEmbedder()
    store = fresh_store(embedder)
    build(tmp_path, store, embedder, batch_size=2)

    report = build(tmp_path, store, embedder, batch_size=2, resume=True)
    assert report.indexed == 0
    assert report.skipped == 4
    assert report.points == 4


def test_resume_finishes_a_run_that_stopped_half_way(tmp_path: Path) -> None:
    """The failure this exists for: interrupted at chunk N, restarted."""
    embedder = FakeEmbedder()
    store = fresh_store(embedder)

    write_gold(tmp_path, [chunk(i, f"Marshall plan paragraph {i}.") for i in range(2)])
    build(tmp_path, store, embedder, batch_size=2)

    write_gold(tmp_path, [chunk(i, f"Marshall plan paragraph {i}.") for i in range(4)])
    report = build(tmp_path, store, embedder, batch_size=2, resume=True)
    assert report.skipped == 2
    assert report.indexed == 2
    assert report.points == 4


def test_resume_does_not_re_embed_what_it_skips(tmp_path: Path) -> None:
    """The point of resuming: the skipped chunks cost nothing the second time."""
    write_gold(tmp_path, [chunk(i, f"Marshall plan paragraph {i}.") for i in range(4)])
    embedder = FakeEmbedder()
    store = fresh_store(embedder)
    build(tmp_path, store, embedder, batch_size=2)
    embedder.calls.clear()

    build(tmp_path, store, embedder, batch_size=2, resume=True)
    assert embedder.calls == []


# --- guards -----------------------------------------------------------------


@pytest.mark.parametrize("batch_size", [0, -1, MAX_TEXTS_PER_REQUEST + 1])
def test_an_impossible_batch_size_is_refused(tmp_path: Path, batch_size: int) -> None:
    write_gold(tmp_path, [chunk(0, "Marshall plan aid to Europe.")])
    embedder = FakeEmbedder()
    with pytest.raises(ValueError, match="batch_size"):
        build(tmp_path, fresh_store(embedder), embedder, batch_size=batch_size)
