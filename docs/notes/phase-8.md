# Phase 8 — One improvement, measured

Reranking. What it is, why it was chosen, what it did, and the four things
that went wrong on the way — three of which are more useful than the result.

Decisions: D-069 to D-072.

---

## 1. The two kinds of encoder

Everything in this phase follows from one fact about how the search you built
in Phase 5 works.

**A bi-encoder reads the question and the chunk separately.** Every one of your
30,362 chunk vectors was computed at index time, alone, months before anyone
asked anything. The question gets the same treatment. Search is then just:
whose numbers point in a similar direction.

That is why it is fast — the expensive part happened once, offline — and it is
why it is blunt. **Neither side ever saw the other.** By the time the
comparison happens, both have already been flattened into 1536 numbers.

**A cross-encoder reads them together.** Question and chunk go into the model in
one pass, and one relevance score comes out. It can notice that the question
says *differed* and that this chunk covers only one of the two treaties. A
bi-encoder structurally cannot.

The price is that nothing can be pre-computed. The score depends on the pair,
so it must be worked out per query:

| | Chunks scored per query | Tokens | Time |
|---|---|---|---|
| Rerank the whole corpus | 30,362 | ~7,600,000 | minutes |
| Rerank the top 20 | 20 | ~5,000 | ~11 ms |

So the architecture writes itself: **cheap and broad, then expensive and
narrow.** That shape — retrieve-and-rerank — is the standard modern one, and
this is the reason for it.

---

## 2. Why this technique, from your own numbers

Phase 7's baseline said:

```
recall@5   75.0%
recall@20 100.0%
```

Every section the ground truth expects is **already retrieved**. Six of them
sit at ranks 6, 6, 9, 10, 11 and 18. Nothing is unfindable.

That is a very specific diagnosis. It means the failure is not *search* — it is
*ordering*. Hybrid search would improve candidate generation, which the 100%
says is not broken. A reranker improves ordering, which is exactly what is
broken.

It also means **the ceiling is 100%**, not something lower. All the right books
are already on the table; somebody just has to pick the right five out of
twenty.

The rejected alternative was the one-line `MAX_PER_DOCUMENT` fix — capping per
article rather than per section. It has three sightings behind it and it will
still be one line in Phase 9. Running both at once would have made neither
attributable, which is the whole content of the one-change rule.

---

## 3. What was built

Four pieces, and only one of them is about a model.

| Piece | File | Job |
|---|---|---|
| `Reranker` Protocol, `RerankUnavailable` | `retrieval/rerank.py` | The seam |
| `LocalReranker` | same | Runs a cross-encoder in this process |
| `_rerank()` | `retrieval/search.py` | Reorders the candidate list |
| `FakeReranker`, `UnavailableReranker` | `tests/fakes.py` | Offline tests |

**The Protocol returns indices, not documents.** `rerank()` hands back
`(index, score)` pairs pointing into the list it was given. That keeps this
module ignorant of `SearchResult` and every other type in the project — the
same reason `Embedder` returns bare lists of floats.

It paid for itself inside one session. The vendor was changed twice —
Voyage → local `bge` → local `ms-marco` — and `search.py` was never touched.

**Reranking happens before thinning.** `thin()` walks the list in order and caps
per section, so it trusts whatever order it receives. Reranking after it would
be thinning the wrong list.

**A failure degrades rather than breaks.** `RerankUnavailable` is caught and the
vector order is returned with a warning. A missing model should cost ranking
quality, not the whole endpoint.

---

## 4. The result

Baseline `2026-08-04T1623Z` → reranked `2026-08-05T1311Z`:

```
                 baseline   reranked
recall@5            75.0%      75.0%
recall@20          100.0%     100.0%
coverage@5          53.5%      50.0%
MRR                  0.59       0.54
distinct articles     2.5        2.9
p50                4257ms     4462ms
```

**recall@5 did not move at all.** D-069's prediction was that it would clear
85%; its revert condition was that 75–80% counts as noise. The condition fired.

The headline number hides the whole story, though. Three questions gained a
top-5 hit and three lost one:

```
GAINED  bolsheviks-held-on      rank 11    -> rank 1
GAINED  finland-two-wars        ranks 6,10 -> ranks 3,5
GAINED  dawes-vs-young          ranks 6,8  -> ranks 3,6
LOST    sealion-after-britain   rank 5     -> rank 7
LOST    money-became-worthless  rank 4     -> rank 7
LOST    killing-became-policy   rank 4     -> rank 10
```

The gains are large, the losses are marginal, and two of the three gains are
comparison questions where **both sides** now reach the top 5 — the failure
this phase was chosen to fix. Distinct articles rose in every category.

It was kept, against the written condition, and D-069 records that as an
override with its reason rather than letting it pass silently.

### Then the answers were read, and the losses are not losses

`killing-became-policy` is the worst on paper: rank 4 → rank 10. Both answers
give the same core fact — Wannsee, 20 January 1942. The reranked one *also*
explains what Wannsee formalised, names the extermination camps, and ends with
a paragraph on the historiographic debate over whether Hitler's order predates
December 1941.

That paragraph is the content of `Final Solution — Historiographic debate about
the decision-making` — **the exact section recall counted as missing.** The
system assembled it from a different chunk.

`money-became-worthless` gained the Rentenmark and how the hyperinflation
ended. `sealion-after-britain` is a wash.

And the biggest gain shows the mechanism in one row. `bolsheviks-held-on` asks
how the Bolsheviks held power while the country was in arms against them:

```
baseline  #1  cos=0.616  Bolsheviks                     (topic match)
reranked  #1  cos=0.558  Russian Civil War -- Warfare   (question match)
```

The chunk promoted to first has a **lower** cosine score than three it demoted.
Cosine matched the word *Bolsheviks*. The cross-encoder understood the question
was about the fighting. That is the entire bi-encoder/cross-encoder difference,
visible in two numbers.

**So recall@5 recorded three losses and there are none.** The metric counts
section ids; the system assembles the same facts from different sections, which
is what RAG is for. That is a fact about the metric as much as the reranker,
and it is the strongest argument in this repository for Phase 10's eval
hardening — a faithfulness metric would have scored these correctly.

*Caveats: n=3, this is a reading rather than an independent assessment, and the
facts were not checked against their sources. A wrong claim present in both
answers would read as agreement.*

---

## 5. The four things that went wrong

More useful than the result. None appears in any tutorial.

### The dead switch

The wiring arrived as five separate fragments — a field, two imports, an
`__init__` change, a method, a call site. Two were wrong in opposite
directions: the call sat inside `if min_score is not None:`, which is never
true, and `__init__` never stored the reranker.

**Separately either is a crash. Together they cancel.** The call was never
reached, so the missing attribute never fired. The result lints clean,
type-checks clean, passes 337 tests, runs fine, and does nothing.

Had it shipped, the eval would have reported recall@5 unchanged at exactly
75.0% and D-069's revert rule would have discarded a feature that never ran.

*Whole files from now on, one at a time.* Phase 3's notes say the same thing.

### The run that measured nothing

The first real run was launched believing the reranker was on. It was not —
`RERANKER_ENABLED` was still false. Every retrieval metric came back identical
to the baseline to four significant figures.

The only reason anyone noticed was `RunMeta.reranker`, a field added twenty
minutes earlier, which recorded `""`. **A run directory outlives anyone's
memory of which flag was set that day.**

The mistake produced a free **A/A test** — same code, same config, twice:

```
                  1623Z    1249Z
recall@5          75.0%    75.0%
coverage@5        53.5%    53.5%
MRR                0.59     0.59
refusal rate      16.7%    13.3%
p50              4257ms   3657ms
```

**Retrieval is perfectly repeatable; generation is not.** Every retrieval
number matched exactly, while one question changed its refusal at temperature 0
and p50 moved 600 ms on identical work. That is the noise floor, and it is now
the standard for judging any latency claim here.

### The model that loaded fine and was broken

`BAAI/bge-reranker-base` imported cleanly and produced garbage. Four documents,
two models:

```
document                                    bge-base   ms-marco-L6
Berlin Wall built in 1961 to stop fleeing      0.793         +8.53
Treaty of Rome established the EEC, 1957       0.581        -10.35
Pasta is boiled in salted water                0.000        -10.95
East German emigration crisis, mid-1961        0.000         -7.25
```

It ranks the Treaty of Rome above the emigration crisis for a Berlin Wall
question, and gives two unrelated documents an identical 0.000.

The eval had already caught it — recall@5 fell to 41.7%, paraphrase to 0.0%,
and recall@20 to 95.8%, which should be impossible from reordering a fixed
pool. But no unit test could have: a test asserts that the ranking is the
reranker's, not that the reranker is any good. **The fakes cannot know what a
real model should say.**

Two things can catch this: an eval with a before number, and four lines of
hand-written sanity check. The second costs two minutes.
`scratch_rerank_check.py` is kept for that reason.

### The eval and production reranking different pools

`OVERFETCH = 4` multiplies whatever `k` is. The answer path asks for 5 and gets
a pool of 20; the eval runner asks for 20 and got **80**.

Under cosine alone that is invisible — sorting 20 or 80 gives the same top 5.
With a reranker it is not, so the eval was measuring a system that never ships.
It was also where the seven seconds went, and why recall@20 could fall at all.

Fixed by `RERANK_TOP_N = 20`: the top 20 are scored, everything below keeps its
vector position and follows. D-072.

---

## 6. Terminology

| Term | Meaning |
|---|---|
| **Bi-encoder** | Two separate passes, two vectors, compared afterwards. Pre-computable. What `embedding.py` does |
| **Cross-encoder** | One pass over the (question, chunk) pair, one score out. Not pre-computable. What a reranker is |
| **Candidate pool** | The `RERANK_TOP_N` results handed to the reranker |
| **Retrieve-and-rerank** | The two-stage shape: cheap and broad, then expensive and narrow |
| **NDCG@10** | Ranking quality over the first ten results. Higher is better |
| **Domain mismatch** | A model trained on one kind of text scoring another. MS MARCO is Bing search results; this corpus is encyclopedic history prose |
| **A/A test** | The same configuration run twice, to measure how much the numbers move when nothing changes |

---

## 7. What a good number looks like

Written because of D-073's third rule: a metric with no standard next to it
teaches nothing. This is the calibration for reading `summary.txt`.

The **impossible** column is the valuable one. A bad number means the system is
weak; an impossible number means the *measurement* is broken, and that is a
completely different investigation.

| Metric | Good | Poor | Impossible — stop and debug |
|---|---|---|---|
| **recall@5** | >85% | <60% | Higher than recall@20 |
| **recall@20** | ~100% | <90% | Falling when the only change was reordering a fixed pool |
| **coverage@5** | >70% | <35% | Higher than recall@5 |
| **MRR** | >0.70 | <0.35 | >1.0, or above recall@5 |
| **top-1 cosine** | 0.65–0.80 | <0.50 | >1.0, or <0 |
| **distinct articles** (of 5) | 2.5–3.5 | <1.5 — one article filling every slot | >5 |
| **refusal rate** | ~20% — six of thirty questions are unanswerable | <10% (answering things it cannot) or >35% (refusing answerable ones) | Refusals on questions whose expected sections were retrieved |
| **p50** | <5,000 ms | >8,000 ms | Below ~2,000 ms — generation alone takes longer than that |
| **invalid markers** | 0 | any | more markers than sources sent |
| **errors** | 0 | any | — |

**Two things this table cannot tell you**, both demonstrated in this phase:

- **A flat metric can hide a real change.** recall@5 was 75.0% before and after
  while six questions changed. Averages over 24 questions cancel.
- **A metric can be wrong about the answer.** All three recall "losses" here
  produced answers that were equal or better. recall counts section ids; it
  does not read.

Both are arguments for Phase 10, and both were found by reading rather than by
any number in this table.

---

## 8. What Phase 9 inherits

`2026-08-05T1311Z` is the new baseline. Hybrid search is measured against it.

Three things carried forward:

- **The ceiling is still 100%.** recall@20 is 100%, so every remaining failure
  is an ordering failure. Hybrid search changes the scores feeding that order.
- **The paraphrase losses.** Three questions got worse, all of them reworded
  rather than literal. If hybrid search makes that worse, D-069 gets revisited
  with two numbers instead of one.
- **A stronger reranker is untested.** `ms-marco-MiniLM-L6` is trained on short
  web passages, which is a real domain mismatch against 1,000-character
  encyclopedia prose. `L12`, a working `bge-v2-m3`, or a hosted model may
  simply be better, and that is one config line.
