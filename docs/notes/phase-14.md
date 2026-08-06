# Phase 14 — expanding the corpus past three themes

Short, because almost nothing was built. The concepts here are about **data
curation and what an evaluation can and cannot see**, not about code.

---

## What this phase did

The corpus was three themes ending in 1945, in a project whose title claims the
20th *and* 21st centuries. `plan.md:263` said to expand to 8-12 themes before
Phase 5 and it was skipped in Session 5, then carried for nine phases. Six
themes were added, taking it to nine and to 2024.

```
bronze articles   664  ->  1,274
gold chunks    30,362  ->  54,903
```

Cost: **$0.26** to re-embed, **$0.34** for the whole phase.

---

## The one idea worth keeping: an eval only tests the corpus it was written from

The corpus grew by 81% and **not one retrieval number on an answerable question
moved.** recall@5 stayed at 75.0%, recall@20 at 100.0%, MRR at 0.54.

That looks like a broken run, and D-086 had said in advance that it would be —
identical recall figures were written down as an impossibility condition,
because Phase 8 once shipped a reranker that did nothing and passed 337 tests.
So it was checked three ways:

| Check | Result |
|---|---|
| Does the run record the new collection? | `meta.json` says `points: 54903`, not 30,362 |
| Do new articles appear in results at all? | 104 of 600 slots, **17.3%** |
| Did any question return a different list? | **12 of 30** did |

The run was real. The condition was wrong, for a reason nobody had spotted:

> All 24 answerable questions are about **1914-1945**. All 615 new articles are
> about **1945-2024**. The new material was never going to compete.

Per question, **0 of 24 changed their recall@5 verdict** and 23 of 24 had an
identical rank for the first correct chunk.

**Say it plainly.** Imagine tripling the size of a library and re-running the
same exam. Every mark comes back the same. That normally means someone
re-marked the old papers by mistake. Here the new books really were on the
shelves — but the exam only asked about the war years, and every new book was
about what came afterwards.

**Why this matters more than the corpus.** Phase 13 found the golden thirty
cannot measure a *generation* change. Phase 14 found it cannot measure a
*corpus* change. Same root cause. Every remaining idea in `roadmap.md` is
measured by this instrument, and it has now failed twice.

---

## The second finding: a test can stop being a test

Six questions existed to check the system says "Not in the sources." when it
should. **Four of the six are now genuinely answerable** — Chernobyl, the Good
Friday Agreement, Srebrenica and Brexit are all in the corpus now, and all four
are answered correctly.

That is not the system getting worse. It is the **metric losing its test
cases**, and it leaves the refusal check standing on two questions.

The out-of-domain floor survived: "how does a transformer neural network work"
scored **0.235**, against 0.253 on a corpus half the size. Nearly doubling the
pool moved the floor by 0.018, which is the evidence that a score floor
separates *subject matter*, not *difficulty* — the same conclusion D-047 reached
from the other direction.

---

## Three hazards, all found by reading data rather than by a test

### 1. A command that would have destroyed earlier work

`curate` overwrites the whole registry. Run on nine themes, it would have
regenerated the first three as untrimmed candidates, and `ingest` would then
have fetched articles cut by hand in Phase 2. **A tool that is safe the first
time is not automatically safe the second time.**

### 2. The one that would have been invisible

This is the important one, and it is a chain of three innocent decisions:

- `ingest` skips on `(theme, requested_title)`, so an article already in Bronze
  under an old theme is fetched **again** under a new one — at today's revision.
- Silver deduplicates with `.first()` over the parquet scan.
- `cold-war-divided-europe` sorts alphabetically **before** `interwar`.

Put together: the newer text wins, section positions shift, and a `doc_id` in
`questions.toml` quietly stops naming the section it was written against. The
eval would have carried on producing numbers, and they would have been numbers
about a different answer key.

Avoided by dropping the 131 already-ingested titles. Afterwards **all 50
ground-truth `doc_id`s were verified present and still naming the same
sections** — `10160:4` is still `Final Solution — Historiographic debate`.

**Say it plainly.** The answer key refers to sections by "article 10160,
section 4". Re-downloading an article can change how many sections it has, so
section 4 could become a different piece of text — while still being called
section 4. Nothing would look broken.

### 3. My own rule, wrong, caught by reading the bytes

The trim exempted the decolonisation theme from the "not about Europe" rule,
because that theme *is* about Europe's colonies. But it let through **bare
country surveys** — Philippines, Israel, Pakistan, Oceania, Singapore, Canada.
46 articles, **14% of the new content**, roughly 10,000 chunks of non-European
domestic history.

The distinction the rule needed: `French Algeria` is this theme; `Algeria` is a
country survey that happens to contain one section about it.

Found by sorting the fetched articles by size and reading the top of the list.
No test could have caught it, because nothing was broken — the pipeline
correctly ingested exactly what it was told to.

---

## A smaller lesson: `MIN_SEEDS` is a coverage rule wearing a quality badge

A title enters the registry when **two or more** seeds link to it. That reads
like a quality filter, and it silently assumes the seeds are topically close.

`postwar-society-and-economy` had six seeds that barely link to each other and
returned **62 candidates**, against 232-372 for every other theme. Ten more
seeds took it to 433. The rule was not filtering for quality; it was reporting
that the seeds did not overlap.

---

## Housekeeping, cleared

Five items owed since Phases 1-9: `registry.py` split into `seeds.py` +
`registry.py`; `_to_revision()` extracted from `fetch_batch`;
`data/bronze/_missing.csv` written; the `StarletteDeprecationWarning` removed
with a dev-only `httpx2`; scratch files deleted.

**One thing went wrong doing it, and it is instructive.** Splitting the test
file, 10 of 11 tests were carried over — the file was read to line 139 and
continued past there. The suite went 460 → 459 and the count was the only
signal. Reading part of a file and assuming the rest is the same failure that
produced a dead reranker in Phase 8.

**And one pre-existing quirk surfaced:** `ingest` is not idempotent on the first
re-run. When two registry titles redirect to the same article, the later one
wins and the earlier is stored under the wrong `requested_title`, so its skip
key never matches. A second run fetches 3, a third fetches 0 — it converges.
Bronze now holds 18 page_ids twice within a theme; Silver deduplicates on
`page_id`, so the corpus is unaffected at 1,274 unique articles.
