# Phase 9 — Hybrid search, measured and reverted

The concept reference for Phase 9. Written after the work, against files that
exist in this repository.

The short version: BM25 keyword search was added alongside the dense search and
fused with reciprocal rank fusion. It made every retrieval metric worse. A
twelve-configuration sweep showed the harm was proportional to how much BM25
was used, so the technique was reverted rather than tuned. See the D-074
verdict in `decisions.md` for the numbers.

---

## 1. The two kinds of search

| | Dense (cosine) | Sparse (BM25) |
|---|---|---|
| Stores | 1,536 numbers describing meaning | one number per word present |
| Made by | OpenAI, over the network, costs money | `retrieval/sparse.py`, locally, free |
| Readable? | No — no slot means "Hungary" | Yes — every slot *is* a word |
| Finds | chunks about the same topic | chunks using the same words |
| Blind to | the difference between rare and common words | that "invaded" and "invasion" are related |

The names come from the shape. A dense vector has every one of its 1,536 slots
filled. A sparse vector has about 4.3 billion possible slots — one per possible
word — of which roughly a hundred are filled.

**Neither is a model in the sparse case.** BM25 is a formula, not something
trained: count the words, damp repetition, penalise length. There is nothing to
swap out and nothing to fine-tune.

---

## 2. BM25, in the three parts that matter

For one word in one chunk:

```
weight  =  frequency × (K1 + 1)
           ─────────────────────────────────────────────
           frequency + K1 × (1 - B + B × length / average)
```

| Part | Constant | What it stops |
|---|---|---|
| Frequency | — | Nothing on its own; a word appearing more should count more |
| Saturation | `K1 = 1.5` | The fourth "Trianon" being worth as much as the first — otherwise repetition wins |
| Length | `B = 0.75` | Long chunks winning by volume, since they mention everything |
| **Rarity (IDF)** | — | Common words dominating. **Computed by Qdrant**, not by us |

That last row is a design decision, not an omission (D-075). Rarity needs
document frequencies for the entire corpus. Qdrant already holds them, so the
collection declares `modifier=Idf` and the server multiplies it in at query
time. The client only ever computes the part that depends on one chunk.

**What was deliberately left out**, recorded before the result was known: no
stemming and no stopword list. "Invaded" and "invasion" are unrelated terms.
Both are cheap to add and both would have made this phase two changes.

---

## 3. Why word ids are hashed, and why not with `hash()`

Qdrant addresses sparse dimensions by integer, so every word needs a number.
`term_index()` uses `zlib.crc32`.

Python's built-in `hash()` is **salted per process** — it returns a different
number for the same string every time the interpreter starts. An index built on
Monday would not match a question asked on Tuesday, and the failure would be
silent: no error, no exception, just an empty result list forever.

`test_term_index_is_stable` pins the value of `term_index("trianon")` to a
literal. That test was written with a made-up constant and failed on the first
run, which is the argument for pinning it: a hardcoded number has to be
measured, never remembered.

---

## 4. Reciprocal rank fusion

Two ranked lists have to become one. The formula is a single line:

```
score(chunk) = Σ over lists  1 / (RRF_K + rank in that list)
```

**Why positions and not scores.** Cosine returns about 0.58 for a strong match.
BM25 returns about 14. Those live on different scales; adding them lets one
search outvote the other by units alone, and normalising them is a guess. A
rank is comparable by construction — first is first in any units.

**What `RRF_K` does.** It is the "do not over-trust first place" dial.

| `RRF_K` | rank 1 | rank 2 | Effect |
|---|---|---|---|
| 0 | 1.000 | 0.500 | First place worth double second |
| 60 | 0.0164 | 0.0161 | Nearly equal — agreement across lists wins |

Higher `RRF_K` flattens the curve, so being liked by *both* searches matters
more than topping one. 60 is the original paper's value.

**The hidden cost, which this phase found the hard way:** RRF only sees
positions, so it has no channel for "I am not confident about this". BM25's
first place counts exactly as much as cosine's first place, even when BM25's
first place is a palace.

---

## 5. What was built

| File | What it holds |
|---|---|
| `retrieval/sparse.py` | `tokenize`, `term_index`, `average_length`, `document_vector`, `query_vector` |
| `retrieval/vectorstore.py` | a named `"text"` sparse slot with `modifier=Idf`; `search_sparse()`; `_query()` shared by both searches |
| `retrieval/search.py` | `RRF_K`, `fuse()`, `SearchResult.sparse_score`, the `hybrid` switch |
| `pipeline/index/build.py` | the corpus average measured in one pass, then both vectors written per chunk |
| `eval/record.py`, `run.py`, `report.py` | `RunMeta.hybrid`, `Retrieved.sparse_score`, the transcript header |
| `core/config.py`, `.env.example` | `hybrid_enabled`, off by default |

**One design point worth keeping.** The corpus average length is measured over
all 30,362 chunks *before* the batching loop, not per batch. A per-batch average
would weight the same chunk differently depending on which batch of 200 it fell
into, and `resume` would then build a collection that no single run could
reproduce. The cost is tokenising twice, which is a regex over text already in
memory.

**And one about scores.** `SearchResult.score` stays strictly cosine. A chunk
found only by keyword carries `score = 0.0` and its real BM25 number in
`sparse_score`. Blending the two into one field would have destroyed the eval's
score column and made this run incomparable with Phase 7's baseline — the same
argument that kept `rerank_score` separate in Phase 8.

---

## 6. The result

Every retrieval metric moved the wrong way, and recall@20 — 100% since Phase 7
— fell to 91.7%. Six questions had an expected section pushed out of the top 20
entirely, including `bolsheviks-held-on`, which Phase 8 had promoted from rank
11 to rank 1.

D-074 had recorded, before the run, that a recall@20 drop was *possible* this
phase and would have been *impossible* in Phase 8. Reordering a fixed pool
cannot lose a section; changing what is in the pool can. That distinction is
what let the drop be read as a finding rather than hunted as a bug.

---

## 7. The sweep, and why it was affordable

One bad run does not distinguish "the technique is wrong" from "the settings
are wrong". Answering that normally means many eval runs.

**It did not, because retrieval is free and repeatable.** Phase 8's accidental
A/A run had already established that every retrieval metric reproduces to four
significant figures while generation does not. recall, coverage and MRR need no
model call at all — the ~$0.03 and four seconds per question are generation.

`scratch_sweep.py` therefore measured twelve configurations for the price of
thirty embeddings:

- each question embedded once, vectors reused across every config;
- pools fetched once at the widest depth any config asked for, then sliced;
- the cross-encoder scoring each (question, chunk) pair once and caching it,
  because a rerank score does not depend on the config that put the chunk in
  front of it;
- `metrics.summarise` reused rather than reimplemented — a second copy of a
  metric is a second chance to get it wrong, and Phase 7 already shipped one
  metric that lied.

**Two rows existed only to validate the harness** — `dense only` had to
reproduce the Phase 8 baseline and `fuse w=1.0` had to reproduce the failed run.
Both matched exactly. Without those two rows the other ten mean nothing.

---

## 8. Why hybrid loses on this corpus

Five reasons, ordered by how much they explain.

1. **There was no problem to fix.** recall@20 was already 100%: every needed
   section was already being retrieved. Hybrid search improves *candidate
   generation*, and candidate generation was not failing.
2. **Aspect sections share their rare words.** `Hyperinflation — Causes` and
   `Hyperinflation — Stabilization` contain the same distinctive vocabulary at
   similar frequencies, so BM25 sees them as near-identical. Only meaning
   separates "how it started" from "how it ended". Long articles split by aspect
   are the worst shape for term matching, and the opposite of the code and
   error-code corpora BM25's reputation rests on.
3. **Dense search already finds keywords.** In the hand probe nearly every
   hybrid result also carried a BM25 score — both searches were returning the
   same chunks. BM25 was casting a duplicate vote, not adding information.
4. **Proper nouns are ambiguous.** A keyword probe for `trianon` returned
   `Palace of Versailles` above `Treaty of Trianon`, because the Grand Trianon
   is a building on that estate.
5. **The reranker had already taken this win.** Hybrid's benefit is a better
   ordering of candidates. A cross-encoder does that better, because it reads
   the question and the chunk together. **Hybrid search is most valuable in a
   system that has no reranker.**

Where it would pay off, worth recognising later: code and logs (`--no-verify`,
`ENOTFOUND`), product catalogues with SKUs, and controlled legal or medical
vocabulary. All corpora where a token is rigid, rare, and means exactly itself.

---

## 9. Terminology

| Term | Meaning here |
|---|---|
| Dense vector | The embedding. 1,536 numbers, every slot filled, describes meaning |
| Sparse vector | One weight per word present. Billions of possible slots, ~100 used |
| BM25 | The formula scoring word overlap: frequency, damped, length-penalised, rarity-weighted |
| IDF | Inverse document frequency — how rare a word is corpus-wide. Qdrant's half |
| RRF | Reciprocal rank fusion. Merges ranked lists by position, `1/(k + rank)` |
| Dose-response | A result that varies monotonically with the amount of a treatment. What made the sweep decisive rather than suggestive |
| A/A test | The same configuration run twice, to learn what "no change" looks like |

---

## 10. What a good number looks like

Written before each result, as the contract requires.

| Measurement | Good | Bad | Impossible |
|---|---|---|---|
| Corpus average length | 140–190 tokens | under 100, over 300 | under 20, over 1,000 for 1,000-character chunks |
| recall@5 vs baseline | above 83.3% | 70.8–79.2% (±1 question) | above 100% |
| recall@20 | 100% held | below 100% — real, means fusion evicted a section | above 100% |
| Sweep control row | exactly 75.0 / 100.0 / 50.0 / 0.54 | — | anything else — the harness lies and the table is void |

The last row is the one that made the sweep usable. A benchmark whose control
does not reproduce a known result is not evidence about anything.

---

## 11. What Phase 10 inherits

**The instrument is now the bottleneck.** Two phases running have produced
results that recall@5 could not resolve. Phase 8 read 75.0% before and after
while six questions changed, three of them for the better. Phase 9 needed a
twelve-configuration sweep to establish that a 4.2-point move was a dose-response
curve rather than noise, because with 24 answerable questions one question *is*
4.2 points.

**And the retrieval ceiling looks reached.** recall@20 has been 100% since Phase
7, and two candidate-generation techniques have now been measured against it —
one kept on a diversity argument, one reverted. The remaining failures are not
findability failures, so the next real gains are more likely to come from
measuring better (Phase 10), storing better (Phases 11–12), or from what this
corpus specifically needs — dates and infoboxes (Phases 19–20).

**Kept, flag off:** `sparse.py`, the sparse vectors in the collection, `fuse()`,
and `hybrid_enabled`. A retest after Phase 10 costs one flag and a sweep.
