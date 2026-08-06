# Phase 16 — the noise floor

No code was written. The phase ran the same sixty questions three times with
nothing changed, and measured how much the answers moved anyway.

Cost: **$0.94** — two evaluation runs, two faithfulness runs, one judge probe.
The third run was already on disk from Phase 15.

---

## Idea 1 — what a noise floor is

Every result this project has published on the generation side is a difference
between two numbers. Phase 13 changed one thing, one answer changed, and the
unsupported-claim count went from 3 to 2. Was that the change working, or would
it have moved anyway?

Nobody knew, because nobody had ever run the thing twice without changing it.
A **noise floor** is that missing number: how far a metric moves when the
answer is "nothing happened". Anything smaller than the floor is unreadable.

**In plain words.** You want to know if a diet is working, so you weigh
yourself before and after and you are 300 grams lighter. Useless — until you
know that stepping on the scales three times in one morning already gives you a
spread of a kilogram. Then 300 grams is nothing, and you need to lose two kilos
before you can honestly say anything. This phase weighed the same person three
times.

**Terminology.** The floor is also called the *minimum detectable effect*: the
smallest change an instrument can actually see.

---

## Idea 2 — the answer is 4 claims wide

Three identical runs. Sixty questions each. The faithfulness judge found:

```
                          run 1   run 2   run 3
unsupported claims            7      11      10
mean faithfulness         98.7%   98.0%   98.1%
```

So the count wanders by 4 with nothing changed at all, and the percentage
wanders by 0.7 points. The rule that follows: **a generation change has to move
the unsupported-claim count by more than 4 before anyone may call it a result.**

Retrieval, by contrast, did not move at all. Across 1,200 chunk slots — sixty
questions, twenty results each, three runs — not one slot held a different
chunk. recall, coverage and MRR are identical in all three runs and in the two
before them.

**In plain words.** The search half of this system gives the same answer every
single time, like a calculator. The writing half is a person paraphrasing from
notes: same notes, same facts, different sentences each time. So a small change
in the search numbers means something, and a small change in the writing
numbers means nothing.

---

## Idea 3 — the ruler is part of the wobble

This is the finding that made the phase worth doing.

When a claim was marked unsupported in one run, the other two runs were checked
for the same claim. 56 such comparisons:

| The other run | count |
|---|---|
| also called it unsupported | 28 |
| never made that claim at all | 15 |
| **called the same claim supported** | **13** |

That last row should not exist. The claim is the same text, the sources are the
same text, and the judge gave opposite verdicts.

Reading the seven distinct cases one by one, four are plainly the judge being
wrong. `brexit-why` is the clearest. The claim is byte-identical in both runs.
The source sentence says older Leave voters "consider it a potential threat to
national identity and culture". Run 1 quoted that sentence and passed the claim.
Run 3 quoted a shortened version of the same sentence and failed the claim for
not being explicit.

The judge's instructions tell it to *find the one sentence carrying the fact*
before deciding. **That search step is the unstable part** — it is a little
retrieval problem living inside the judge, and when it lands on the wrong
sentence the verdict follows the wrong sentence.

**In plain words.** You gave the same essay to the same marker three times and
got three different marks — not because the essay changed, but because the
marker kept looking at a different paragraph before deciding. About a quarter of
the disagreement is the marker, not the essay.

---

## Idea 4 — an instrument can invent a defect

`stasi-scale` was flagged as unsupported in **all three runs**. A defect that
survives resampling is the one you trust most. This one is not real.

The answer said, close to word for word what the article says:

> In 1989, it employed 91,015 full-time employees, including 2,000 fully
> employed unofficial collaborators, 13,073 soldiers, and 2,232 officers of the
> GDR army

The judge works in two steps. First a model **splits** the answer into separate
standalone claims. Then a model **checks** each claim against the sources. The
splitter turned the sentence above into:

> In 1989, the Stasi employed 2,000 fully employed unofficial collaborators.

It threw away "91,015 people full-time, including" — the very thing its own
instructions say to keep. The checker then correctly failed that fragment for
attaching the number to the wrong thing. **The defect was created by the
instrument and then detected by the instrument.**

`judge-probe` cannot catch this, because the probes hand the judge a claim
directly. The splitter is never on trial.

**In plain words.** A machine cuts a sentence in half, loses the half that
mattered, and then reports the remaining half as wrong. Both halves of the
machine did their job. The output is still a lie.

---

## Idea 5 — the three defects that are real

The other recurring ones were opened next to the Wikipedia text they came from
and checked by reading. All three are genuine, and they are the same class of
error Phase 6 first found: nothing invented, a qualifier lost.

**`versailles-vs-trianon` — the worst defect this project has recorded.**

> Source: "Romania, Yugoslavia and Czechoslovakia had to assume part of the
> financial obligations of the former Kingdom of Hungary"
>
> Answer: the treaty "required Hungary to assume financial obligations for parts
> of its former territory assigned to Romania, Yugoslavia, and Czechoslovakia"

It reverses who pays. Every word is from the source and the meaning is inverted.

**`travel-without-showing-papers`.** The source says Schengen countries "(of
which Ireland is not included)" abolished document checks. The answer copies the
sentence and drops the parenthesis.

**`seveso-1976`.** The source says unregulated industrial expansion led to
widespread pollution and to disasters such as Seveso. The answer says the Seveso
accident caused the pollution.

---

## Idea 6 — what a number stops meaning

The decision rule in `decisions.md` is the deliverable, but the part worth
remembering is what it takes away. Any generation finding in this project that
rested on four claims or fewer is now inside the noise, including the one that
caused this phase to be scheduled.

And a count is the wrong shape of evidence anyway. Because a quarter of the
movement is the judge changing its mind, "11 went to 7" is not readable.
**Which defects appeared and which vanished** is readable, and it is free —
`scratch_noise.py` computes it from runs already on disk.

**In plain words.** Stop comparing totals. Compare lists.

---

## The one thing that never moved

Refusals: 7, 7, 7. Identical across three runs and across three different ways
of defining the word — the metric's phrase match, answers opening with "Not in
the sources.", and answers that cited nothing at all. It is the only generation
behaviour here with zero measured variance, which makes it the only one a future
phase can read one question at a time.
