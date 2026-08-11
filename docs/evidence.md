# Does it work?

Every number on this page comes from a run saved in `eval/runs/`, and every one
of them can be recomputed from that run without spending anything. Where a
number is weak, that is said here rather than left for a reader to discover.

The newest run is **`2026-08-11T0635Z`**. Its `meta.json` records the exact
configuration, and `records.jsonl` holds every question, every retrieved chunk
with its score, and every answer.

---

## The headline

106 questions across five suites, scored against hand-written ground truth.

| | |
|---|---|
| Questions answered correctly from the top 5 chunks (`recall@5`) | **85.9%** |
| Found anywhere in the top 20 (`recall@20`) | **97.8%** |
| Share of *all* expected sections present in the top 5 (`coverage@5`) | **64.5%** |
| Questions asking for a specific value whose answer states it (`fact_rate`) | **94.7%** |
| Refused to answer | **11 of 106** |
| Answers with a broken or missing citation | **0** |
| Cost of the full run | **$0.1374** |
| Median time to a complete answer | **4,049 ms** |

**What those words mean, without the jargon.** We wrote 106 questions and, for
each one, wrote down by hand which parts of Wikipedia actually contain the
answer. Then we ask the system and check whether it went to those parts.
`recall@5` is how often the right source is in the five it chose to read.
`coverage@5` is stricter: when a question needs two or three sources, did it get
*all* of them. It is the weakest number here and it is the honest one to look at.

---

## Why you should believe the numbers

Metrics are easy to fool. Four things here make these harder to fool, and they
matter more than the figures themselves.

**1. The predictions were written down before the measurements.** Every phase
from 8 onward states, in `decisions.md`, what a good result would be, what a bad
one would be, and what would be *impossible* — before the command runs. The
third is the useful one. In Phase 8 a recall figure fell in a way that was not
merely bad but arithmetically impossible, and that is what exposed a broken
model rather than a poor one. A prediction sealed in advance cannot be adjusted
after seeing the answer.

**2. The failures are written down in the same place as the wins.** Phase 32
built a well-known technique (HyDE), measured it, and it lost to switching a
component off; that is [D-108](decisions.md). Phase 30 found two of its own
premises were already false. Phase 8 kept a change against its own written
revert condition and says so in those words. A record with no negative results
in it is a record that was edited.

**3. There is a tool whose job is to fail.** `eurohistory gate` compares two
saved runs and exits non-zero if anything regressed. It is not decorative — the
most recent phase **failed it on four checks**, and the failures are published
in `eval/runs/gate-D-108.txt` alongside the reasoning for shipping anyway.

**4. The scoring code is pinned to published figures.** `tests/eval/test_baseline_pinned.py`
holds the committed baseline to the numbers quoted in the decision record, so
the metric code cannot quietly start reporting something different about runs
that were already published. It runs in CI, on every push, with no database and
no API key.

---

## Check it yourself, for free

Nothing below costs money or needs an OpenAI key.

```bash
uv run pytest
```

839 tests, no network, no Docker, no model download.

```bash
uv run eurohistory rescore eval/runs/2026-08-11T0635Z
```

Recomputes every metric on this page from the saved run. If the code disagrees
with the published summary, this is where it shows.

```bash
uv run eurohistory gate eval/runs/2026-08-11T0525Z eval/runs/2026-08-11T0635Z --changed reranker
```

The regression check for the most recent change, including the four failures.

Thirty-one runs are saved in `eval/runs/`, going back to Phase 7. `transcript.txt`
in each one is readable prose: the question, the chunks it retrieved, and the
answer it produced.

---

## What the questions are

106 questions in five suites, kept separate and never averaged into one number —
because a change that helps one kind and hurts another looks like no change at
all in the total.

| Kind | n | What it tests |
|---|---|---|
| easy | 48 | A single section answers it directly |
| multi | 27 | The answer needs two or more articles |
| paraphrase | 17 | Worded deliberately unlike the source — the closest thing here to a real user |
| unanswerable | 14 | The corpus genuinely does not contain it, and the system must say so |

The `unanswerable` set is the one people leave out. A system that answers
everything confidently scores well on the other three and is dangerous. Here,
**11 of 106 questions were refused**, and refusing correctly is treated as a
pass.

---

## The weakest numbers, stated plainly

- **`coverage@5` is 64.5% against `recall@20` of 97.8%.** Translation: the
  material is almost always retrieved, but when a question needs several
  sources the system often brings back only one of them. This is the largest
  measured shortfall in the system and no change has yet attacked it.
- **One question of 106 is never retrieved at all**, `empires-let-go`, and has
  not been since Phase 15.
- **Latency measurements are noisy.** The same configuration measured 725 ms
  apart on two consecutive days with no code change. Any latency claim smaller
  than that is not a measurement.
- **The refusal metric has a known error rate** of about 1 answer in 224, found
  and quantified in Phase 27.
- **Sentences that stated a measurement can end mid-sentence.** The Wikipedia
  cleaner drops a template that renders units, so a small number of chunks read
  "*It extended  from north to south*". The model fills the gap and cites it.
  One confirmed sighting, understood mechanism, queued as the next piece of
  work, and it is the most serious known defect in the system because no metric
  can see it.

---

## The corpus

**1,271 Wikipedia articles** (curated down from 1,390 candidates) across 9 themes of 20th- and 21st-century
European history, split into **56,324 chunks**, each indexed with the exact
revision it came from — so every citation points at the version of the article
that was actually read, not at whatever the page says today.
