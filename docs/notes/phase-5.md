# Phase 5 notes — embeddings, Qdrant, `/search`

Reference for the concepts Phase 5 requires. Written against the state of this
repo on 2026-08-02, with `qdrant-client` 1.18.0, `openai` 2.52.0 and
`numpy` 2.5.1.

Everything below is grounded in files that exist here, or in output that was
actually produced. Where a number is quoted, it was measured on this corpus.

---

## What Phase 5 built

| File | Purpose |
|---|---|
| `retrieval/embedding.py` | the `Embedder` Protocol and the OpenAI implementation |
| `retrieval/vectorstore.py` | everything Qdrant — the only file importing `qdrant_client` |
| `retrieval/search.py` | `SearchService`, `SearchResult`, `thin()` |
| `pipeline/index/build.py` | Gold to Qdrant, batched and resumable |
| `api/dependencies.py` | the cached `SearchService` factory |
| `api/main.py` | `GET /search` and its response models |
| `cli/cli.py` | `eurohistory index` |
| `compose.yaml` | Qdrant with a named volume |
| `docs/tuning.md` | every knob, its file, and what changing it costs |
| `tests/retrieval/`, `tests/pipeline/index/`, `tests/api/` | 60 tests, none touching the network |

Dependencies added: `openai`, `qdrant-client`, `numpy`.

Result: **30,362 points, `size=1536`, cosine distance, collection status
green.** `/search` answers in well under a second.

Decisions recorded: **D-043 to D-050**.

---

## Part 1 — what an embedding is

A fixed-length list of numbers a model produces from text. For
`text-embedding-3-small` it is always 1,536 numbers, whether the input is one
word or a 1,200-character chunk.

The model was trained so that texts it treats as related come out **pointing in
a similar direction**. That is the only property, and it is the only thing you
can use.

Two consequences, both load-bearing.

**The numbers mean nothing individually.** Position 400 is not "war-ness".
Nobody assigned them; they fell out of training. You never read an embedding,
you only compare it to another one.

**Direction is relative to that model's own coordinate system.** Every model
builds its own during training and two systems have nothing to do with each
other. Embed the corpus with one model and the question with another and the
comparison is not slightly worse — it is meaningless, with no error anywhere.

That last point is why `retrieval/embedding.py` exists as a single module used
by both the indexing job and `/search`. The moment those two use different
models, retrieval returns plausible-looking nonsense.

### What it buys over keyword search

The corpus never contains the phrase "how expensive was the Marshall Plan".
Keyword search finds nothing. But the chunk reading "the programme distributed
$13.3 billion over four years" comes out pointing in a similar direction to
that question, so it is found without sharing a single word.

It is also why D-039 prepends the title and heading to every chunk: the vector
is built from the text you hand the model and nothing else.

---

## Part 2 — cosine similarity, written out

The comparison is the angle between two vectors, ignoring their length:
multiply them element by element, sum that, divide by both lengths. The result
runs -1 to 1, where 1 is the same direction.

Written in three lines against 200 real chunks, in `scratch_search.py`:

```python
scores = (vectors @ query) / (
    np.linalg.norm(vectors, axis=1) * np.linalg.norm(query)
)
```

`vectors @ query` is 200 dot products at once. The division is by the two
lengths. That is the whole formula, and it is exactly what Qdrant computes —
Qdrant is faster, not different.

### Why cosine and not Euclidean distance

A longer chunk tends to produce a vector with a larger magnitude. Euclidean
distance measures magnitude as well as direction, so it would systematically
prefer or penalise chunks by length. Length is not relevance. Cosine throws
magnitude away and keeps only direction, which is the part the model was
trained to make meaningful.

### Calibrating the numbers

Measured on this corpus with the query `why was the Berlin Wall built`:

| | by hand, 200 chunks | Qdrant, 30,362 chunks |
|---|---|---|
| 1 | 0.414 Berlin — History | 0.579 Berlin — History |
| 2 | 0.309 East Germany — Government | 0.575 Germany — History |
| 3 | 0.306 Cold War — Final years | 0.543 East Germany — History |
| 4 | 0.296 **Bucharest — Architecture** | 0.529 Berlin — History |
| 5 | 0.295 East Germany — Demographics | 0.527 East Germany |

Two things this shows.

**~0.55 is a strong match, ~0.30 is noise, nothing approaches 1.0.** These are
OpenAI embedding scores; the range is compressed and there is no absolute
number that means "relevant".

**The corpus-size effect is visible.** Same question, same model, same formula
— the 200-chunk pool tops out at 0.414 and returns Bucharest architecture at
rank 4, because *something* always comes back ranked first. This is the
concrete version of the plan's warning that a small corpus makes retrieval look
different from what it is.

---

## Part 3 — what Qdrant stores

Four layers.

**Collection** — like a table. Fixed vector size (1536) and distance metric
(cosine) at creation. Every point must match.

**Point** — one record: `id`, `vector`, `payload`.

**Payload** — ordinary JSON stored beside the vector. Without it a search
returns 1,536 numbers and nothing else. It does two jobs: shows and cites the
hit (`text`, `title`, `heading`, `revision_id`), and filters (`themes`). See
D-044 for the ten fields chosen and why `license` is not one of them.

**Index** — the interesting layer. Comparing a query against all 30,362 vectors
one by one is *exact* search and would be fine at this size. It stops being
fine at millions. So Qdrant builds an HNSW graph: each vector linked to a few
neighbours, in layers — a sparse top layer for jumping across the space, denser
layers below for refining. A search enters at the top, hops greedily toward
vectors closer to the query, drops a layer, repeats. It touches a few hundred
vectors instead of thirty thousand.

### What "approximate" costs

The graph walk can settle in a local pocket and miss a vector that was genuinely
closer. In practice it finds 95-99% of the true top-k, tunable higher for more
latency. At 30,362 points this costs essentially nothing — worth knowing
because it is the explanation people forget when a result is inexplicably
absent.

Visible in this collection: `points_count` is 30,362 but `indexed_vectors_count`
is 29,800. Not a gap. Qdrant only builds the graph for segments above
`indexing_threshold` (10,000); smaller segments are searched exactly, which is
faster at that size.

### Why the size must match exactly

The collection was created with `size=1536` because that is what
`text-embedding-3-small` returns. Write a 768-dimension vector into it and
Qdrant rejects it. `retrieval/embedding.py` checks the width of the first
returned vector for the same reason: caught there it names the misconfigured
setting, caught at Qdrant it is a dimension error three layers from the cause,
and not caught at all if the collection happened to be created from the same
wrong number.

---

## Part 4 — the point id

Qdrant accepts **only** an unsigned integer or a UUID as an id. `chunk_id` is
`"30030:1:4"`, so it cannot be used directly; it travels in the payload
instead.

The id answers one question: **what happens when you run `index` twice?**

| id scheme | second run |
|---|---|
| running counter | overwrites arbitrary points — the number means nothing |
| random UUID | a second copy of the whole corpus |
| **derived from `chunk_id`** | **the same chunk lands on the same point; a no-op** |
| derived from the text | two chunks with identical text collapse into one |

`uuid.uuid5(NAMESPACE, chunk_id)` is a hash with a fixed namespace:
deterministic, no lookup table, stable across machines.

**The namespace must never change.** Every stored id derives from it, so
editing that one line orphans the entire collection at once. It is listed under
"not knobs" in `docs/tuning.md` for that reason.

### And the orphan problem

`chunk_id` is `"{doc_id}:{position}"`, so it moves whenever chunk size, overlap
or `MIN_SECTION_CHARS` changes. Re-chunk and every chunk gets a new id. Upsert
into the existing collection and you get 30,000 new points sitting beside
30,000 old ones that nothing will ever overwrite and nothing will ever delete —
still competing for top-k slots, with no error to reveal it.

So `index` drops and recreates by default (D-046). The Qdrant collection is a
cache derived from Gold, exactly as Gold is a cache derived from Silver.
`--resume` is the narrow exception, for finishing an interrupted run.

---

## Part 5 — the two problems visible in real results

Both were found by running a real query, not by a test.

### Duplicates

`why was the Berlin Wall built` returned `Berlin — History` at ranks 1 **and**
4 — two chunks cut from the same section. Chunks overlap by 150 characters and
neighbours say nearly the same thing, so they score nearly the same and crowd
each other into the top-5. Five slots paid for, three viewpoints delivered.

Fixed in `thin()`: ask Qdrant for `k * 4`, walk the list, keep at most 2 from
any one `doc_id`, stop at `k`. Costs nothing — Qdrant returns 20 as fast as 5.
Two per section rather than one because a long answer legitimately spans two
consecutive chunks. See D-047.

### No floor

Search always returns `k` results, even when all of them are junk. Nothing in
the system says "there is no good answer here".

Deliberately **not** fixed with a score threshold. The obvious move is "drop
anything below 0.45", and it is a guess: a strong match is ~0.58 on one
question and ~0.42 on another, so any number chosen today silently discards
good answers on some queries. `min_score` exists as a parameter and defaults to
off. Phase 7 produces thirty questions with real scores, and that is when a
number can be picked from evidence. Until then Phase 6's prompt does the
refusing, which needs no threshold at all.

This is the gate rule applied to something that looked obviously worth doing.

---

## Part 6 — why the API must not import the vector store

Stated in the plan as a concept to be able to explain, and it is really two
rules.

**`api/` must not import `pipeline/`.** The web process answers queries. It has
no reason to pull in wikitext parsing, the Bronze schema and the ingestion
stack — that is startup cost, dependency surface and a much larger thing to
reason about, all for code that never runs there. This is why `retrieval/`
exists as its own package (D-048): `Embedder` and `VectorStore` are needed by
both sides, so they live where both may reach them.

**Nothing outside `retrieval/vectorstore.py` imports `qdrant_client`.** Search
returns `Hit`, our own two-field type, not Qdrant's `ScoredPoint`. So swapping
the database is one file rather than a search-and-replace, and the endpoint's
response shape does not silently change when the client library does.

No `Protocol` was written for the store. There is one implementation, and
`QdrantClient(":memory:")` already gives tests the seam an interface would
have. The rule applied: write the interface when the second implementation
arrives — and a test double counts as one, which is exactly why `Embedder`
*does* have a Protocol and the store does not.

---

## Part 7 — the API layer

### `def` and not `async def`

```python
@app.get("/search")
def search(...) -> SearchResponse:
```

Both work. Only one stays fast under load.

An `async def` handler runs on the event loop, and the loop can only do one
thing at a time. The OpenAI and Qdrant clients here are blocking, so a blocking
call inside an async handler stalls every other request for the duration.
Declared `def`, FastAPI runs the handler in a thread pool instead and the loop
stays free.

`/health` stays `async def` because it does nothing at all.

### `Depends` and the test seam

The endpoint declares `service: Annotated[SearchService, Depends(get_search_service)]`
— it says *what* it needs, not how to build it. FastAPI calls that function and
passes the result in.

Tests replace the function:

```python
app.dependency_overrides[get_search_service] = lambda: stub
```

That swaps the entire retrieval stack for one app object, so `/search` is
tested for status codes, validation and response shape with no Qdrant, no
OpenAI and no network. Retrieval itself is tested separately, where it belongs.

### Validation from annotations

`Query(min_length=1, max_length=500)` and `Query(ge=1, le=50)` reject an empty
question or `k=999` with a 422 **before the handler body runs**. There is a
test asserting the stub was never called for bad input, because "validated"
and "validated early" are different claims.

---

## Part 8 — what the tests cover, and why those things

60 tests, none touching the network or Docker.

| File | The property it protects |
|---|---|
| `tests/retrieval/test_embedding.py` | vectors come back in the order the texts went in; a wrongly sized vector is refused |
| `tests/retrieval/test_vectorstore.py` | idempotency: the same chunk always lands on the same point, twice written is once stored |
| `tests/retrieval/test_search.py` | thinning: at most 2 per section, order never changed, short list over duplicates |
| `tests/pipeline/index/test_build.py` | the whole job end to end; re-chunking drops the old points |
| `tests/api/test_api.py` | status codes, validation, and the response shape |

Two are worth singling out.

**Ordering.** The embedding stub answers its items in reverse on purpose. If
the `sorted(...)` line in `embed()` were removed, every vector would attach to
the wrong chunk and *nothing downstream could detect it* — no error, no bad
shape, just quietly wrong retrieval forever.

**The rebuild.** Index four chunks, re-chunk into one, index again, assert the
collection holds 1. Without `recreate=True` it would hold 5, and the four
orphans would keep turning up in searches. That test is D-046 written as code.

The whole suite runs in under two seconds because `QdrantClient(":memory:")` is
the real engine in-process and `FakeEmbedder` counts words instead of calling a
model.
