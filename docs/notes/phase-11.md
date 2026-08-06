# Phase 11 — The joins between facts

One prompt rule, measured. The shortest phase in the project and the first one
to fix something a *user* would notice.

---

## The failure

Phase 10's faithfulness metric found seven unsupported claims. Not one was an
invented fact. All seven were invented **connections**:

| Claim | What was made up |
|---|---|
| the deputies were absent **because** they had been banned | a cause |
| the majority was obtained **by** surrounding the Reichstag | a cause |
| **Hungary** assumed the financial obligations | a direction |
| **Both** treaties disbanded the defeated forces | a generalisation |
| the King **persuaded him to resign** | one relationship for another |
| **rather than** a mass demonstration | a contrast |
| industrial potential **allowed it to** pass the initiative | a causal weld |

Every date, name and number in those sentences is in the sources. The joining
words are not.

**Ten-year-old version:** you're given two true photographs — a man holding an
umbrella, and a wet street — and you write "the street is wet *because* he
opened his umbrella". Both pictures are real. The word "because" isn't in
either of them.

---

## Where the prompt allowed it

`# GROUNDING` said:

> You may combine facts from two or more sources to answer a question neither
> answers alone. You may not add a fact that no source contains.

The model reads *fact* as an atom — a date, a name, a number — and treats the
connective tissue between atoms as its own writing. So it obeyed the rule
exactly as written and still reversed who owed whom.

**The gap was a definition, not a missing rule.** The fix names five kinds of
join and says each is a claim: cause, direction, generalisation, contrast, and
a verb stronger than the source's.

---

## Why the revert condition watched answer length

**Faithfulness is trivially gamed by saying less.** An answer that asserts
nothing scores 100%. So a rule that made the model timid would have shown up as
a big improvement while making the system worse, and the metric could not have
told the difference.

The revert condition therefore had three legs, only one of which was the score:

1. unsupported claims still 6 or more → the rule did nothing;
2. refusals above the baseline 16.7% → it got timid;
3. answers shorter, or "The sources do not cover" on complete answers → same
   thing, seen differently.

None fired. Claims *rose* from 185 to 215 and refusals fell to 13.3% — the
answers say more and get more of it right, which is the opposite of gaming.

---

## The result, and the one that survived

```
                       before   after
unsupported claims          7       3
claims judged             185     215
mean faithfulness       97.7%   99.0%
refusal rate            16.7%   13.3%
recall@5 / @20     75.0/100.0  75.0/100.0
```

Retrieval reproduced bit-for-bit, which is the control this phase got for free:
nothing in the query path changed, so everything above is generation.

**The prediction was ≤2 and the answer is 3.** Missed, recorded as missed. The
change stands on the revert condition, which was written first and did not
fire.

**Six of the seven are gone, including all four the rule names directly. The
Trianon reversal is not.** The prompt now says, in as many words, "check the
subject of the sentence you took it from" — and the answer still puts the
obligations on Hungary. The likely reason is that the *question* asks what
Hungary lost, and the question's subject overrides the source sentence's.

**A prompt instruction is not a guarantee.** Third sighting: Phase 6 recorded
two style rules that were ignored, and this is the first defect to survive a
rule aimed squarely at it. If it earns its own phase, the next step is not
another rule — it is a check that runs *after* the answer exists, either a
groundedness gate or a self-check in the same call.

---

## The shape of the phase, which is the transferable part

```
measure  ->  change exactly one thing  ->  measure again  ->  write it down
```

Every part of it existed before this session started. The metric came from
Phase 10, the baseline run came from Phase 8, the prediction and revert
condition were written into `decisions.md` before the prompt file was opened,
and the whole change was five minutes of typing.

**That is what the eval was for.** Phases 8 and 9 spent two sessions each on
retrieval techniques against a 100% recall@20 ceiling and produced one kept
result and one revert. This phase took an hour and fixed six real defects,
because for the first time the failure was named before the work started.
