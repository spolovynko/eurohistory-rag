# Phase 13 — The groundedness gate

**Result: built, measured, not shipped.** The gate fires on 5.6% of answers.
Of seven revisions read by hand, one was a real fix, four were defensible
trims, one was cosmetic, and one deleted a fact the source contains. It costs
3.4× the latency and roughly double the tokens. `VERIFY_ENABLED` stays false.

---

## What the phase was for

Every fix for an ungrounded claim before this one was an instruction inside the
*writing* step — Phase 6's grounding rule, Phase 11's rule about the joins
between facts. The `versailles-vs-trianon` reversal survived both, plus Phase
12's retrieval change. A rule inside the writing step cannot see an error the
writing step is making.

So: a second pass. The draft answer goes back to a model with the same sources,
and any claim the sources do not support is corrected or removed before the
answer is returned. Terminology: a **runtime groundedness gate**, as opposed to
the same idea used offline as a metric, which is what `judge.py` already is.

## The three things worth keeping from it

### 1. The golden thirty cannot measure a generation change

Two runs, one small change, and **28 of 30 answers came back different**. At
temperature 0. The three known unsupported claims all vanished and two brand
new ones appeared in answers the gate never touched.

Phase 8 recorded that generation is not repeatable and moved on. The
consequence nobody wrote down: an unsupported-claim count over 30 questions
drifts by one or two on its own. Any generation result smaller than that was
never a result. D-081's 7 → 3 is a move of four and probably survives; nothing
narrower does.

The instrument that does work is the paired one — record the draft next to the
revision and read both. That is what `EvalRecord.revised` and `EvalRecord.draft`
are for, and it is why step 7 stopped being "judge 813 claims" and became "read
seven revisions".

### 2. A probe before the money, again

The first version of `verify_prompt.md` caught **none** of the three known
defects and edited two answers anyway. The cause was mine: a section telling
the checker that most drafts are fine and that changing a supported sentence is
worse than missing an unsupported one. The guard against over-correction was
heavy enough to guarantee under-correction, and it did not even prevent the
cosmetic edits it was written for.

Cost of finding that out: three model calls, about half a cent. Cost of not
finding it out: the full $1.30 of paid runs, measuring an instrument that did
nothing. Third time this pattern has paid — `judge-probe` in Phase 10,
`scratch_rerank_check.py` in Phase 8.

### 3. Granularity is the variable

The same model, on the same sources, catches all three probe defects when
`judge.py` asks about one claim at a time. It catches one of three when asked
to review the whole answer. Reading a fluent answer produces the impression
that it is fine, and that impression is what a reversed subject hides behind.

Asking per claim is roughly eight calls per answer instead of one. Against a
5.6% firing rate that is a phase with its own argument, not a tweak to this one.

## The seven revisions

| Question | What the gate did | Verdict |
|---|---|---|
| Oscarsborg Fortress | replaced two invented causes with the sources' own | **good** |
| bourgeoisie stratification | deleted "as a result of the Industrial Revolution" | defensible |
| Aboriginal war memorials | deleted the model's own closing commentary | defensible |
| Jewish communities in the Americas | deleted "which influenced Jewish migration patterns" | defensible |
| Salazar's Estado Novo | narrowed "public order and financial stability" | defensible |
| Schwerin von Krosigk | changed a name to "He" | cosmetic |
| Habsburg rulers | deleted Frederick III, who is in the source | **wrong** |

Six deletions, one correction. Revised answers lost 5.2% of their characters.
**A gate that mostly deletes buys faithfulness with information** — including on
the Trianon answer it was built for, where the clause was removed rather than
reassigned to the states that actually bore the obligations.

## Numbers

```
                        before      after
recall@5 / @20      75.0/100.0  75.0/100.0   (free control -- reproduced)
mean faithfulness        99.0%      99.3%    (noise)
unsupported claims           3          2    (noise)
p50 latency              3,179     10,759 ms
prompt tokens           78,776    154,072
completion tokens        5,195     19,790
firing rate                 --       5.6%    (7 of 124)
```

Phase spend, both probes included: **about $0.75**.

## What is still true afterwards

- The Trianon reversal *can* be moved. Nothing before this phase moved it.
- A whole-answer review pass is not the mechanism. Per-claim might be, at eight
  times the cost.
- `verify.py`, both prompts, the setting and 16 tests stay, off by default —
  the same disposition as `THINNING_CONFIGS` after D-082.
