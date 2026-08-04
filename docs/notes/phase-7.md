# Phase 7 — Break it on purpose

Concept reference for the evaluation phase. Written against the first baseline,
`eval/runs/2026-08-04T1623Z`.

---

## Why this phase exists

Everything after this point is a fix for a specific failure. Without a
repeatable measurement, "hybrid search improved things" is a feeling. The eval
turns it into two numbers that moved or did not.

The rule that follows from it: **no phase starts without a named failure from
the eval, and no phase ends without a before/after number.**

---

## The vocabulary

| Term | What it means here |
|---|---|
| **Ground truth** | The answer key. For each question, the Silver sections that *should* come back. Written by hand from `corpus_map.txt`. |
| **recall@k** | Of the questions with an answer key, how often did at least one expected section land in the top k. |
| **coverage@k** | Of the expected sections, what fraction actually landed in the top k. Recall says "something correct came back"; coverage says "how much of it". |
| **MRR** | Mean reciprocal rank. 1 divided by the position of the first correct hit, averaged. Rank 1 → 1.0, rank 4 → 0.25. Recall cannot tell those apart; this can. |
| **p50 / p95** | Median and near-worst latency. An average hides the slow ones. |
| **Retrieval failure** | The wrong chunks came back. |
| **Generation failure** | The right chunks came back and the answer is still wrong. |

**Why both recall@5 and recall@20.** 5 is what the model actually sees. 20 is
how good the answer *could* be if the ranking were perfect. The gap between
them is the exact size of the prize a reranker is competing for.

---

## The baseline

30 questions, `k=5`, 30,362-point collection, `gpt-5-mini`.

```
kind           n     r@5   r@20  cov@5    MRR    top  docs  arts  refuse   p50ms   p95ms  gen ms
easy           8  100.0% 100.0%  85.4%   0.88  0.761   3.2   1.1    0.0%    4302    8149    3953
multi          8   62.5% 100.0%  39.6%   0.58  0.702   3.9   2.6    0.0%    5150    8090    5115
paraphrase     8   62.5% 100.0%  35.4%   0.31  0.659   4.5   3.4    0.0%    4257   10059    4795
unanswerable   6     n/a    n/a    n/a    n/a  0.464   4.2   3.0   83.3%    2087    2375    1803
all           30   75.0% 100.0%  53.5%   0.59  0.659   3.9   2.5   16.7%    4257    8090    4058

no citation: 0   invalid marker: 0   errors: 0
tokens: 70,070 prompt, 5,386 completion
```

Cost: about 75,000 tokens for the whole set. Latency is 97% generation —
retrieval is a rounding error, which settles any argument about optimising it.

---

## The failure log

### 1. recall@20 is 100% and recall@5 is 75%

**The headline.** Every single expected section is retrieved — not one is
missing from the corpus, not one is unfindable by the embedder. Six questions
have it ranked outside the top 5, at ranks 6, 6, 9, 10, 11 and 18.

| Question | Kind | First correct hit |
|---|---|---|
| `dawes-vs-young` | multi | 6 |
| `finland-two-wars` | multi | 6 |
| `austria-czechoslovakia-1938` | multi | 9 |
| `france-fell-fast` | paraphrase | 10 |
| `bolsheviks-held-on` | paraphrase | 11 |
| `democracy-to-one-party` | paraphrase | 18 |

This is a **ranking** problem, not a retrieval problem. Nothing needs to be
found that is not already being found. That is the textbook argument for
**cross-encoder reranking**: fetch 20, re-order, keep 5.

### 2. Comparison questions return one side — now measured

`versailles-vs-trianon` **scores a hit at 5** and returns five Versailles
sections and zero Trianon. `sealion-after-britain` does the same: one article
in all five slots. Recall calls both successes. Coverage calls them 33% and
50%, which is the truth.

`mean_distinct_articles_at_5` is **1.1 for easy questions** — seven of eight
fill all five slots from a single article. `MAX_PER_DOCUMENT` caps chunks per
*section*, and one article has many sections, so the cap never fires.

**Third independent sighting** of the same defect, and now with a number
attached. Leading Phase 8 candidate.

### 3. There is a usable score floor after all

| Kind | Top-1 score range |
|---|---|
| easy | 0.708 – 0.840 |
| multi | 0.628 – 0.771 |
| paraphrase | 0.611 – 0.710 |
| **unanswerable** | **0.265 – 0.532** |

The bands **do not overlap**. Every answerable question scores at least 0.611;
no unanswerable question reaches 0.532. A `min_score` around 0.57 would refuse
all six and keep all twenty-four.

This is new evidence against D-047, which said a threshold could not be chosen
honestly. It could not — on two questions. On thirty it can. The caveat is real
though: thirty questions is a small sample, the six unanswerable ones were
chosen partly *because* the corpus is thin on them, and a threshold tuned on
its own test set is the oldest mistake in the book.

### 4. Refusal holds — 5 of 6, and the sixth is arguably correct

`brexit-why` did not open with "Not in the sources." It gave the withdrawal
date from a newspaper article, then said the sources do not cover the reasons.
That is the **partial-answer** path, and the corpus does contain that date, so
the behaviour is right and the metric is blunt. Counted as a pass on reading,
a fail on the automatic number.

`transformer-attention` scored 0.265 — the floor, exactly as Phase 5 predicted.

### 5. Paraphrase is a ranking problem, not a matching problem

recall@5 62.5% but **MRR 0.31**, the worst of any kind. The correct sections
come back, deep. `democracy-to-one-party` puts the right chunk at rank 18 while
ranks 1–3 are `Weimar Republic`, `The Holocaust — Rise of Nazi Germany` and
`Nazi Germany — History` — all topically plausible, none of them the answer.

Semantic search matches the *subject* well and the *specific claim* badly.

---

## Retrieval failure or generation failure?

| | Count | Evidence |
|---|---|---|
| **Retrieval** | 6 | The six ranked outside the top 5, plus every one-sided comparison |
| **Generation** | 0 confirmed | No invented citations, no missing citations, no errors |

**Every observed failure in this baseline is a retrieval failure.** The prompt
work in Phase 6 is holding; the ranking is not. That is a clean verdict and it
points Phase 8 at exactly one half of the system.

The two generation defects Phase 6 found by hand — a claim losing its
qualifier, a figure losing the country it applied to — are **not** counted here.
No automatic metric catches them and this baseline's 30 answers have not been
read claim by claim. That reading is still owed.

---

## What a metric cannot tell you

The first baseline reported **0% refusals**. The system was refusing correctly;
the constant being matched had been guessed (`"i don't know"`) rather than read
out of `prompt.md` (`"Not in the sources."`).

A metric is code, it can be wrong, and a wrong one is worse than none because
it looks authoritative. The fix — `eurohistory rescore` recomputing from saved
records — exists so that discovering this costs nothing rather than another 30
model calls.

---

## Commands

```bash
uv run eurohistory evaluate --note "what is different about this run"
uv run eurohistory rescore eval/runs/<run-id>
```

`evaluate` needs Qdrant up and costs a few cents. `rescore` is free and offline.

---

# How to prepare an eval set

The transferable part of this phase. Written for the next project, and grounded
in what went wrong in this one.

A **golden set** is a fixed list of questions with known-correct answers, used
to measure a system the same way every time. "Golden" because it is the
reference everything else is compared against.

## Where the questions come from

1. **Write them from the data, never from memory.** Dump what is actually in
   the corpus and read it first. Both earlier attempts here guessed, and both
   produced "unanswerable" questions the system answered perfectly.
2. **Verify every absence before claiming it.** Search for the topic first. A
   *mention* is not *coverage* — `Chernobyl` appears in eight sections of this
   corpus and not one of them says what happened.
3. **The person who knows the domain writes them.** This is the step
   automation makes worse, not better.
4. **Use real user questions where they exist.** Support tickets, search logs.
   Invented questions are always cleaner than real ones, and cleaner means
   easier.

## What goes in the set

5. **Mix difficulty on purpose.** Here: 8 easy, 8 multi-document, 8 paraphrased,
   6 unanswerable. An all-easy set gives a flattering number that never moves.
6. **Always include questions the system should refuse.** A system that never
   says "I don't know" is not accurate, it is confident.
7. **Include one clearly out-of-domain control.** `transformer-attention`
   scored 0.265 and established the floor, which is what makes any threshold
   argument possible at all.
8. **Paraphrase deliberately.** Ask in words the source never uses. This is what
   separates matching *meaning* from matching *vocabulary*.
9. **Include multi-hop questions.** Answers spanning two documents are where
   retrieval fails, and single-document questions never reveal it.
10. **30–50 is enough to start.** Small enough to read by hand, large enough
    that one question does not swing the number.
11. **Tag every question with its kind.** Reporting by kind is what exposes a
    change that helps one group and hurts another; the total hides it.

## The answer key

12. **Pick a unit that survives your own experiments.** Sections (`doc_id`) here,
    not chunks (`chunk_id`) — chunk ids move on every re-chunk, and ground truth
    invalidated by your own experiments is worthless.
13. **Pick a unit a human can name.** "Berlin Wall — Background" is checkable;
    a hash is not.
14. **Validate the key against the real data, automatically.** A typo'd id can
    never be retrieved, so its question scores zero forever and reads as a
    retrieval bug. `test_committed_ground_truth_points_at_real_sections` is the
    guard.
15. **List every acceptable source, not just one.** Two sections often say the
    same thing, and demanding a specific one punishes a correct answer.
16. **Record why a question is in the set.** The `note` field on
    `versailles-vs-trianon` says what it was written to catch. Six months from
    now that is the only thing that explains it.

## Keeping it honest

17. **Freeze it.** Same questions every run, or comparison means nothing.
18. **Version it with the code.** Every run records its git sha. "Recall went
    up" is meaningless without knowing what changed.
19. **Never tune a threshold on the set you validate with.** The 0.57 cut-off
    this baseline suggests is chosen on its own test data and proves very
    little. Hold questions back, or accept the caveat out loud.
20. **Change the set only deliberately, and rebaseline when you do.** Adding two
    easy questions raises every number without improving anything.
21. **Keep it out of the tuning loop.** A prompt tuned against these 30
    questions stops measuring the system and starts measuring the tuning.

## What to record per run

22. **Store observations, never verdicts.** A re-run rewrites the records; a
    judgement living on them would be destroyed with it (D-065).
23. **Capture the config alongside the results.** Model names, `k`, index size,
    every knob. Two result files with no headers are two mysteries.
24. **One immutable directory per run.** Never overwrite — the history is the
    deliverable.
25. **Make rescoring free and offline.** The first baseline here reported 0%
    refusals because the metric was wrong. Fixing it cost nothing. Without
    `rescore` it costs a full re-run, and so nobody fixes it.
26. **Store the retrieved text, not just ids.** Whether a claim is grounded
    cannot be checked against a section *name*.

## Metrics

27. **Measure retrieval and generation separately.** Otherwise "wrong books" and
    "right books, bad reader" are indistinguishable — and they have opposite
    fixes.
28. **Report at two depths.** The *gap* between recall@5 and recall@20 is the
    reranking argument. Here it is 75% and 100%.
29. **Recall alone is too generous.** Add coverage: `versailles-vs-trianon`
    scored a hit while returning zero Trianon.
30. **Add a rank-sensitive metric.** MRR sees the difference between rank 1 and
    rank 19; recall cannot.
31. **Measure cost and latency too.** A change that doubles recall and triples
    cost is a decision, not a win.
32. **Accept that the important things are not automatic.** Correctness,
    groundedness and lost qualifiers need eyes. Automate what can be automated
    and do not pretend the rest is covered.

## The rule that outranks the rest

33. **Read the output by hand, every time.** Metrics say *that* something is
    wrong; only reading says *what*. Both defects Phase 6 found — a claim losing
    its qualifier, a figure losing the country it applied to — were invisible to
    every metric built here, and both were real.
