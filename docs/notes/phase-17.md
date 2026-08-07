# Phase 17 — the regression gate

A command that compares two saved evaluation runs and refuses the second one if
the system got worse, plus a robot on GitHub that runs everything not needing a
database or money.

Cost: **$0.00**. Nothing in this phase calls a model. The three identical runs
Phase 16 paid for were the test material.

---

## Idea 1 — what a regression gate is, and what CI means

Three words, one idea.

- **Regression** — something that used to work got worse.
- **Gate** — a checkpoint that refuses to let something through.
- **CI**, continuous integration — a robot that runs the checkpoint every time
  the code changes, so nobody has to remember to.

**In plain words.** A restaurant kitchen where someone tastes every dish before
it leaves the pass. Nobody has to be told, nobody has to be in a good mood, and
a bad dish physically does not reach the table. Without it the food is still
tasted — but only sometimes, and only by whoever remembered.

**Why this project needed one.** There is a number in this repository: **75%**.
For the original thirty questions, the correct source material is in the top
five results three times out of four. It has been exactly 75% on five separate
runs across three shipped changes, and until this phase **nothing in the repo
said it had to stay there.** The only thing between a change dropping it to
62.5% and the finished system was a person opening a text file and noticing.

---

## Idea 2 — the roadmap asked for something that cannot be built

`roadmap.md` says: *"the eval runs on every commit and fails the build if recall
drops."* That is not expensive, it is impossible. The robot on GitHub has:

- no Qdrant container holding 54,903 points,
- no `data/` directory — it is deliberately not in git,
- no OpenAI key,
- and each run costs about $0.08 and four minutes.

So the phase is two gates, not one.

| What | Where | When | Cost |
|---|---|---|---|
| lint, formatting, types, 486 tests, the pinned baseline | GitHub | every push | free |
| comparing two runs | either | end of a phase | free |
| producing a run to compare | this machine, Docker up | end of a phase | ~$0.08 |

**In plain words.** The robot in the cloud has no database and no key, so it
cannot ask the system sixty questions. It can still check the code compiles, the
tests pass, and that the old saved answers still add up to the published
numbers. Asking the questions happens on your laptop, once per phase.

---

## Idea 3 — the first check is not a measurement

The gate does not start with recall. It starts by asking whether the two runs
are **comparable**: same collection, same number of points, same `k`, same
reranker, same question set. If any of that differs, it refuses and prints no
metric at all.

That ordering is the whole design, and it comes from the two worst near-misses
in this project. Neither was a number moving:

- **Phase 8** shipped a run with the reranker switched off and presented it as a
  measurement of the reranker. Every number in it was real. It measured nothing.
- **Phase 14** came one command away from re-fetching articles under a new
  theme, which would have shifted section positions so that every ground-truth
  answer key named a different section — **with the eval still printing
  numbers.**

**In plain words.** Before comparing this month's electricity bill to last
month's, check they are both for the same flat. A table of numbers computed
across two runs that were not measuring the same thing is worse than no table,
because it looks exactly like one that was.

**Terminology.** The run's conditions live in `meta.json`, one file per run,
written at run time. That file existing at all is why Phase 8's dead switch was
caught by eye; this phase is that catch, automated.

---

## Idea 4 — declaring your change, and the trap in it

A phase changes something on purpose, so the gate takes `--changed reranker`.
Two rules, and the second one is the interesting half:

1. Anything that differs must be declared, or the gate refuses.
2. **Anything declared must actually differ**, or the gate refuses.

Rule 2 is Phase 8's dead switch, caught in one line. Saying "I changed the
reranker" when both runs record the same reranker means the run did not measure
what it claims to. Run against the real files:

```
FAIL reranker    identical -> identical    declared changed, and is not
```

Declaring two changes at once is allowed but warns, because two changes and the
result cannot be attributed to either. That is the one-change rule — a thing
people remembered — turned into a thing the tool enforces.

---

## Idea 5 — what gates and what only gets printed

This is where Phase 16 pays for itself.

| | Metric | Rule |
|---|---|---|
| **Fails the build** | recall@5, recall@20, coverage@5, MRR | any drop |
| | refusals, errors, invalid citation markers | any change |
| | top-1 score | drop over 0.001 |
| **Printed only** | unsupported claims, faithfulness, claims extracted | never fails |
| | p50 latency | never fails |

**Why the split.** Retrieval gives the same answer every time — Phase 16 checked
1,200 chunk slots and not one held a different chunk — so if it moves, something
broke. The generation numbers wobble on their own, and about a quarter of that
wobble is the faithfulness judge disagreeing with itself on claims it has
already seen. A gate built on those would fail builds at random.

**In plain words.** Fail the build on the parts that are the same every time.
Print the parts that move on their own and let a person read them.

---

## Idea 6 — the prediction that missed, and why it is the best part

D-089 predicted the gate would pass both no-op pairs with zero failures. It did
not. It failed on latency:

```
FAIL golden p50 latency ms    3799 -> 4693    rise <= 600
```

Two runs of identical code, nothing changed, and the gate stopped the build.

The 600 ms threshold came from Phase 8 and was carried forward without asking
what it had been measured on. It was the **whole-run** median of thirty
questions. Applied to a thirty-question *slice* of a sixty-question run it fails
on nothing:

```
p50 ms, three runs with no change at all
             run 1   run 2   run 3   range
golden        3799    4693    3947     893
extended      3822    3339    3310     512
all sixty     3822    3813    3508     315
```

A median of thirty numbers is the fifteenth one. One question crossing the
middle drags it. And nearly all of that time is the model provider's servers,
which is not a property of this code at all.

**In plain words.** You set a rule that the build fails if the average delivery
takes more than ten minutes longer than last week — and then discover the
average already swings fifteen minutes by itself, because of traffic. The rule
was never measuring your kitchen.

D-089 wrote down in advance what to do if this happened: *move the check to the
reported tier rather than widen its threshold until it passes.* That is what was
done. Latency is now printed with its measured spread and cannot fail anything.

**This is the same mistake as D-088's,** one phase later: a threshold quoted
without the thing it was measured on.

---

## Idea 7 — proving the alarm rings

A gate that has never been seen to fail is indistinguishable from a gate that
does nothing — which is exactly what Phase 8's reranker was while 337 tests
passed. So one pair was built to fail: a copy of the baseline with one
question's six correct chunks deleted, the answer key left untouched.

```
GATE FAILED -- 8 checks
FAIL golden recall@5     0.750 -> 0.708
FAIL golden recall@20    1.000 -> 0.958
FAIL golden MRR          0.536 -> 0.494
...
```

One question of sixty losing its correct sections, and the gate exits non-zero.

**And the gate corrected me once.** The first version of that test forced the
drop by *editing the answer key* instead of the results. The gate did not fail
on recall — it stopped at comparability, because an edited key is a change to
the conditions of the run and not a regression in it. The test was wrong and the
code was right.

---

## What is now true

- `uv run eurohistory gate <baseline> <candidate>` compares two runs, free and
  offline, and exits non-zero on a regression.
- `.github/workflows/ci.yml` runs lint, formatting, types and 486 tests on every
  push, with no database, no key and no money.
- `tests/eval/test_baseline_pinned.py` holds the published figures —
  75.0 / 100.0 / 47.9 / 0.536 / 0.655 and the rest — to the run they were
  computed from, so a metric edited in good faith fails a build instead of
  quietly rewriting six phases of history.
