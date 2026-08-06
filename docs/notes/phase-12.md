# Phase 12 — Thinning: one article should not take every slot

A negative result, and the shortest phase in the project. No production code
changed. What it bought is knowing where this system is *not* losing.

---

## What thinning is

Search returns a pool of candidates. The model is shown five of them. `thin()`
picks which five, and it is the last thing that happens before the prompt is
built:

```
question -> embed -> Qdrant returns 20 -> reranker reorders -> THIN -> top 5 -> prompt
```

The rule since Phase 5 has been **at most two chunks from any one `doc_id`**.
It exists because chunks overlap: neighbouring chunks are near-copies, and the
Berlin Wall query in Phase 5 returned the same section at ranks 1 and 4. Five
slots paid for, three ideas delivered.

---

## The failure this phase was written for

`doc_id` is a **section**. `page_id` is an **article**. An article has many
sections, so the cap never stopped one article taking every slot.

Measured on `2026-08-05T1848Z`: **4.2 distinct sections but 2.8 distinct
articles** in five slots, and 1.9 on easy questions. The canonical case is
`versailles-vs-trianon` — five Versailles sections, zero Trianon, coverage 33%,
and one of the three surviving unsupported claims sits in that answer.

Five independent sightings across Phases 5, 6, 7, 8 and 9. One line to change.
Free to measure once Phase 10 built the sweep. That combination is why it went
first, ahead of the roadmap's contextual retrieval — which fixes chunks nobody
can *find*, a failure recall@20 = 100% says we do not have.

---

## What an arm is

One version of the experiment, run over the same questions. Borrowed from
clinical trials: the drug group and the placebo group are each an arm. Here,
six settings of the same rule, one table, and a **control row** that must
reproduce a run already on disk before anything else in the table is read
(D-080). If the control does not match, the harness is broken and every other
row is a number from a machine nobody has checked.

---

## The result

```
config                     r@5    r@20   cov@5    MRR   arts
------------------------------------------------------------
dense only (control)     75.0%  100.0%   50.0%   0.54    2.8
no cap at all            75.0%  100.0%   47.9%   0.54    2.6
section cap 3            75.0%  100.0%   50.0%   0.54    2.7
article cap 3            75.0%   95.8%   50.0%   0.53    3.2
article cap 2            75.0%   87.5%   46.5%   0.53    3.7
article cap 1            50.0%   58.3%   24.3%   0.42    5.0
```

**The mechanism works.** Article diversity rises exactly as predicted — 2.8 to
3.7 at cap 2, against a written prediction of 3.5 or more.

**The payoff never arrives.** coverage@5, the number that says whether the
sections we expected are actually present, does not rise at any setting.

Per question at article cap 3, the whole effect is two rows:

```
versailles-vs-trianon   1/3 -> 2/3   Trianon finally takes a slot
barbarossa-aims         2/3 -> 1/3   an expected section is evicted
```

**The named failure is fixed, at the exact price of breaking a question that
worked.** That is a reshuffle, not an improvement, and at 24 questions it is
indistinguishable from noise.

---

## Reading a table like this without fooling yourself

Three habits, all of which this phase used:

1. **Write the prediction and the reject conditions before the run.** D-082
   holds both, timestamped by the commit. After the fact, every table looks like
   it supports something.
2. **Check the aggregate against the individual questions.** 50.0% versus 50.0%
   looks like "nothing happened". Two questions changed and cancelled. This is
   the Phase 8 lesson repeating, and it is why the per-question check is worth
   the five minutes.
3. **Distrust a metric that moves in the wrong units.** `arts` went up and
   `cov@5` did not. Diversity was never the goal — it was the *proxy* for the
   goal. When a proxy improves and the real number does not, the proxy was
   wrong.

---

## Why a lower cap collapses

At cap 1, everything falls off a cliff: recall@5 75% → 50%, recall@20 100% →
58.3%. One article, one slot, and a question whose answer genuinely lives in
three sections of one article can never be answered.

That is the honest shape of this knob: **it trades depth for breadth, and this
corpus needs depth.** A history question about the Treaty of Versailles is
answered by the Treaty of Versailles article, several times over.

---

## The recall@20 artefact

The article caps drop recall@20 below 100%, which reads alarming after five
phases of quoting that ceiling. The cause is the eval, not the system: the
runner thins at depth 20 while `/ask` thins at 5, so an article contributing
four or more expected sections gets truncated in a list nobody ever reads.

Worth knowing rather than quoting as a defect — but it does mean that the
moment a cap is applied at depth, recall@20 stops being the "is anything
unfindable" ceiling it has been since Phase 7.

---

## What this rules out

Slot allocation is not where this system loses. The fix works, is measurable,
and does not help. `versailles-vs-trianon` fails because the corpus holds far
more Versailles than Trianon — no rule about how to spend five slots can
manufacture the second half of a comparison that was never retrieved well.

A negative result recorded is a completed phase. The five-sighting item that
has been parked since Phase 5 is now closed rather than parked, and the next
phase has one fewer cheap explanation to reach for.
