"""Everything Qdrant: the collection, writing points, and searching them.

The only module that imports `qdrant_client`. Both the offline indexing job and
the online /search path go through it, so nothing else in the project knows
which database is underneath -- swapping it is one file rather than a
search-and-replace. No Protocol yet: there is one implementation, and the
client's ":memory:" mode already gives tests the seam they need.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Self

from qdrant_client import QdrantClient, models
from qdrant_client.http.exceptions import ResponseHandlingException

# Fixed namespace for uuid5. Never change it: every stored point id is derived
# from it, so a new namespace orphans the entire collection at once.
NAMESPACE = uuid.UUID("feedefcf-eb15-4e3e-a4b9-b8afba2eb4b4")
# The name of the sparse vector on every point. Sparse vectors must be named;
# dense stays unnamed because it was there first, and naming it now would mean
# rewriting how every existing call addresses it.
SPARSE_VECTOR = "text"


class VectorStoreUnavailable(RuntimeError):
    """Qdrant could not be reached.

    Raised instead of letting the client's own exception escape, so callers can
    answer "the search service is down" without importing `qdrant_client`.
    Deliberately narrow: it means the server is unreachable, not that a request
    was wrong. A dimension mismatch or a bad query is a bug and still raises the
    client's own error, because retrying those would never help.
    """


def point_id(chunk_id: str) -> str:
    """Qdrant's id for a chunk.

    Qdrant only accepts integers or UUIDs, and `chunk_id` is text, so it is
    hashed into a UUID. Deterministic: the same chunk lands on the same point on
    every run and every machine, which is what makes re-running `index` safe.
    """
    return str(uuid.uuid5(NAMESPACE, chunk_id))


@dataclass(frozen=True, slots=True)
class Hit:
    """One search result, in this project's terms rather than Qdrant's."""

    score: float
    payload: dict[str, Any]


class VectorStore:
    """The chunk collection: create it, fill it, search it."""

    def __init__(self, client: QdrantClient, collection: str, dimensions: int) -> None:
        self._client = client
        self._collection = collection
        self._dimensions = dimensions

    @classmethod
    def connect(cls, url: str, collection: str, dimensions: int) -> Self:
        """Talk to a running Qdrant."""
        return cls(QdrantClient(url=url), collection, dimensions)

    @classmethod
    def in_memory(cls, collection: str, dimensions: int) -> Self:
        """An in-process store with the same API, for tests. No Docker."""
        return cls(QdrantClient(":memory:"), collection, dimensions)

    def ensure_collection(self, *, recreate: bool = False) -> None:
        """Make sure the collection exists, sized for the current embedder.

        `recreate` drops it first. That is the default for a full rebuild: chunk
        ids move whenever chunk size changes, so upserting into an old
        collection would leave orphaned points that nothing overwrites and
        nothing deletes, still competing for top-k slots.
        """
        if recreate and self._client.collection_exists(self._collection):
            self._client.delete_collection(self._collection)
        if not self._client.collection_exists(self._collection):
            self._client.create_collection(
                collection_name=self._collection,
                vectors_config=models.VectorParams(
                    size=self._dimensions,
                    distance=models.Distance.COSINE,
                ),
                sparse_vectors_config={
                    SPARSE_VECTOR: models.SparseVectorParams(
                        modifier=models.Modifier.IDF
                    )
                },
            )

    def upsert(
        self,
        chunk_ids: Sequence[str],
        vectors: Sequence[Sequence[float]],
        sparse_vectors: Sequence[Mapping[int, float]],
        payloads: Sequence[dict[str, Any]],
    ) -> None:
        """Write one batch. The four sequences must line up position by position.

        `sparse_vectors` is required rather than optional on purpose. An
        optional argument lets a forgetful caller write dense-only points that
        no test would notice and no error would report -- which is exactly how
        Phase 8 shipped a reranker that did nothing.
        """
        points = [
            models.PointStruct(
                id=point_id(cid),
                vector={
                    "": list(vec),
                    SPARSE_VECTOR: models.SparseVector(
                        indices=list(sparse.keys()), values=list(sparse.values())
                    ),
                },
                payload=payload,
            )
            for cid, vec, sparse, payload in zip(
                chunk_ids, vectors, sparse_vectors, payloads, strict=True
            )
        ]
        self._client.upsert(collection_name=self._collection, points=points, wait=True)

    def set_payload(
        self, chunk_ids: Sequence[str], payloads: Sequence[dict[str, Any]]
    ) -> None:
        """Overwrite the metadata on points that already exist, one point at a time.

        The vectors are not touched, which is the point: adding a payload field
        to 54,903 chunks this way costs nothing and takes seconds, where a full
        `index` would re-embed 13.0 M tokens for $0.26 and would move every
        cosine score in the fourth decimal. A run that has to be compared
        against the one before it cannot afford that noise.

        `set_payload` rather than `overwrite_payload`: the existing keys are
        still correct and only the new ones are being added. A point that is not
        in the collection is skipped by Qdrant rather than created, so this can
        never invent a vectorless point.
        """
        for chunk_id, payload in zip(chunk_ids, payloads, strict=True):
            self._client.set_payload(
                collection_name=self._collection,
                payload=payload,
                points=[point_id(chunk_id)],
                wait=False,
            )

    def index_payload_field(self, field: str) -> None:
        """Make a payload field filterable at speed.

        Qdrant will filter on an unindexed field by scanning, which is correct
        and slow. The temporal arm filters on `year_start` and `year_end` on
        every dated question, so both are indexed. Idempotent -- asking twice
        for the same index is not an error.
        """
        self._client.create_payload_index(
            collection_name=self._collection,
            field_name=field,
            field_schema=models.PayloadSchemaType.INTEGER,
            wait=True,
        )

    def has_all(self, chunk_ids: Sequence[str]) -> bool:
        """True if every one of these chunks is already stored.

        What makes an interrupted index run resumable: a batch already written
        can be skipped without re-embedding it.
        """
        found = self._client.retrieve(
            collection_name=self._collection,
            ids=[point_id(cid) for cid in chunk_ids],
            with_payload=False,
            with_vectors=False,
        )
        return len(found) == len(chunk_ids)

    def is_ready(self) -> bool:
        """True if Qdrant answers and the collection exists.

        What a readiness probe needs and `/health` deliberately does not check:
        the process can be perfectly alive while the database it depends on is
        not running, and answering "ok" in that state is a lie.
        """
        try:
            return self._client.collection_exists(self._collection)
        except ResponseHandlingException:
            return False

    def _query(
        self,
        query: list[float] | models.SparseVector,
        limit: int,
        using: str | None = None,
        query_filter: models.Filter | None = None,
        exact: bool = False,
    ) -> list[Hit]:
        """One search against the collection, in this project's terms.

        Both vectors share it: they differ in what is asked for, not in how a
        connection failure is reported or how a result is read.
        """
        try:
            response = self._client.query_points(
                collection_name=self._collection,
                query=query,
                using=using,
                limit=limit,
                with_payload=True,
                query_filter=query_filter,
                search_params=models.SearchParams(exact=True) if exact else None,
            )
        except ResponseHandlingException as error:
            raise VectorStoreUnavailable(str(error)) from error
        return [
            Hit(score=point.score, payload=dict(point.payload or {}))
            for point in response.points
        ]

    def search(self, vector: Sequence[float], limit: int) -> list[Hit]:
        """Nearest `limit` chunks by meaning, best first."""
        return self._query(list(vector), limit)

    def search_within(
        self, vector: Sequence[float], limit: int, start: int, end: int
    ) -> list[Hit]:
        """Nearest `limit` chunks by meaning, among those covering `start`-`end`.

        Overlap, not containment: a chunk spanning 1914-1918 is about 1916, and
        requiring the chunk's period to sit inside the question's would throw
        away every survey section ever written. Two ranges overlap when each
        starts before the other ends, which is the pair of conditions below.

        A chunk with no period has neither key in its payload and matches
        neither condition, so it is absent from this list. It is not absent from
        the caller's other lists, and that difference is deliberate: this is one
        arm of a fusion, never a gate on the search. See D-096.

        **Exact, unlike every other search here, and this is the whole reason
        the arm works.** Qdrant finds neighbours by walking an HNSW graph. With
        most of the points filtered out, the walk strands itself in a region the
        answer is not in: measured, `Cold War - Renewal of tensions (1979-1985)`
        was absent from eighty filtered results while a brute-force scan of the
        same filtered set put it second, and raising `hnsw_ef` eightfold did not
        find it either. Scanning costs nothing here because the filter has
        already made the candidate set small -- 7-26 ms against 7-31 ms
        approximate. See the D-096 second addendum.
        """
        return self._query(
            list(vector),
            limit,
            exact=True,
            query_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="year_start", range=models.Range(lte=end)
                    ),
                    models.FieldCondition(
                        key="year_end", range=models.Range(gte=start)
                    ),
                ]
            ),
        )

    def search_sparse(self, sparse: Mapping[int, float], limit: int) -> list[Hit]:
        """Nearest `limit` chunks by keyword match, best first.

        A second call rather than one fused query: D-076 keeps the merge in our
        own code so `RRF_K` is ours and the fusion can be unit-tested. Qdrant
        supplies the IDF half of BM25 here, from the collection's own
        document frequencies.

        An empty query returns nothing rather than raising. A question whose
        every word is unknown has no keywords to look for, and that is a normal
        outcome, not a failure.
        """
        if not sparse:
            return []
        return self._query(
            models.SparseVector(
                indices=list(sparse.keys()), values=list(sparse.values())
            ),
            limit,
            using=SPARSE_VECTOR,
        )

    def count(self) -> int:
        """How many points are stored. Used to report after indexing."""
        return self._client.count(collection_name=self._collection, exact=True).count
