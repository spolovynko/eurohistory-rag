# Phase 10 — Eval hardening

The concepts behind the eval rewrite, in the order they matter. Every phase
before this one changed the system. This one changes the **ruler**.

---

## Why change the ruler at all

Two phases running produced results the eval could not resolve.

**Phase 8.** recall@5 read 75.0% before the reranker and 75.0% after. Six
questions changed — three gained a correct section in the top 5 and three lost
one. Plus three and minus three cancel, so the number said nothing happened.
Reading the three losses found no losses at all: one of them, scored as
*missing* the section on the historiographic debate over the Final Solution,
contains that debate in its answer, assembled from a different chunk.

**Phase 9.** A 4.2-point move needed a twelve-configuration sweep before anyone
could say whether it was real. With 24 answerable questions, one question **is**
4.2 points.

So the ruler has two faults, and they are different faults:

| Fault | What it means | Fixed by |
|---|---|---|
| Too short | one question = 4.2 points, so small real effects are invisible | more questions (synthetic) |
| Measures the wrong object | counts section ids, not whether the answer is right | faithfulness |

---

## Recall counts the wrong object, and why that is not a bug in recall

Recall asks: did the section we listed in advance come back in the top *k*.

That is a fair question about **retrieval**. It is the wrong question about the
**system**, because RAG assembles an answer from whatever it retrieved. If the
fact lives in three sections and the system used a different one from the one
we wrote down, recall calls that a miss and the reader gets a correct answer.

This is not an argument for dropping recall. Recall is cheap, deterministic,
and free of any model call — that is exactly what makes the sweep possible. It
is an argument for having a second metric that looks at the answer, which is
what faithfulness is.

---

## Synthetic questions

A model reads one chunk and writes a question that chunk answers. The answer
key is free: it is the section the chunk was cut from.

**Why they are systematically easier than real questions.** The question is
written *from* the passage, so it borrows the passage's vocabulary. A real user
asks "why did money stop being worth anything in Germany" where the passage
says "hyperinflation in the Weimar Republic". Word overlap is the thing dense
retrieval is best at, so a synthetic set flatters the system.

Two consequences, both load-bearing:

1. **A synthetic score is only ever compared to another synthetic score on the
   same file.** Never to the golden thirty.
2. **The golden set must stay hand-written.** It is the only measurement with
   real question language in it, and generating more of it would quietly delete
   the hardest cases.

**The sampling rule is a bias, chosen deliberately.** One chunk per article.
Long articles hold fifty chunks and short ones hold three, so sampling chunks
uniformly would ask most of the questions about Berlin and Moscow and almost
none about the treaties.

**Two filters, and who does what.** The model may answer `SKIP` when a passage
holds no factual claim — that is what removes the twin-town lists, book titles
and film credits Phase 4 counted. Everything a machine can check is checked in
code: ends in a question mark, plausible length, no "the passage" or "this
article", and no six consecutive words lifted straight out of the chunk. A rule
the code can enforce does not need to be argued for in English as well, which
is what keeps the generation prompt short enough to read.

---

## Faithfulness

**The defect it exists for.** Phase 6's answer said the Treaty of
Brest-Litovsk "required Russia to pay war reparations of six billion marks".
The source says a *supplementary protocol signed in August 1918* required it.
Nothing was invented. Every citation resolved. Recall was perfect. And a reader
comes away believing something the source does not say.

**How it works.** Split the answer into standalone claims, one per line, then
ask a model about each claim on its own: do these sources say this, yes or no.
Score is supported claims over judged claims.

**Why one call per claim rather than one call per answer.** It costs more, and
it is what makes the whole thing defensible:

| Known judge bias | What it is | What removes it here |
|---|---|---|
| Position | prefers whichever candidate came first | nothing is compared to anything, so there is no first |
| Verbosity | prefers longer text | the score is a fraction, so a longer answer must earn every extra claim |
| Self-preference | prefers its own model family | *mitigated only*: `JUDGE_MODEL` is one line, and the judge is recorded on every judgement |

Self-preference is the honest gap. The default judge is the same model that
writes the answers, so the bias is present by default. It is written down
rather than papered over, because a flattering default that nobody reads is
worse than an honest one that is.

**What the metric still cannot see.** Whether a claim is true of the world (only
whether the sources say it). Whether the answer addressed the question asked —
that is *answer relevance*, and it is deliberately not built. And whether the
claim splitter dropped a qualifier before the judge ever saw it, which would
hide the exact defect this exists for. The last one is the real weakness.

---

## Testing the ruler: the probe set

The judge has the shape of every component that has gone wrong in this
repository so far: its output looks plausible whether or not it works.

- Phase 7 shipped a refusal metric reporting 0% while the system refused
  correctly every single time. The phrase it matched had been guessed rather
  than read out of the prompt.
- Phase 8 loaded a reranker that gave two unrelated documents an identical
  0.000. 337 unit tests passed. No unit test **could** catch it — a test
  asserts the ranking came from the reranker, not that the reranker is any
  good.

So `eval/probes.toml` holds six claims whose correct verdict is already known,
against source text copied verbatim out of our own run transcript:

| Probe | Expect | What it catches |
|---|---|---|
| territory, near-verbatim | SUPPORTED | a judge that is simply strict about everything |
| Finland, reworded | SUPPORTED | a judge that matches words instead of meaning |
| wrong year | NOT SUPPORTED | a judge that is not reading at all |
| wrong signatory | NOT SUPPORTED | a judge using its own knowledge instead of the sources |
| **reparations attributed to the treaty** | NOT SUPPORTED | **the real Phase 6 defect** |
| **"paid" where the source says "agreed to pay"** | NOT SUPPORTED | the same defect in a verb |

The last two are the ones that matter. A judge that calls them SUPPORTED is a
word-overlap detector wearing a metric's clothes, and it would have graded both
answers Phase 6 caught by hand as perfect. `eurohistory judge-probe` exits
non-zero if any probe fails.

The file also refuses to load if every probe expects the same verdict — a judge
that answers SUPPORTED to everything must not be able to pass.

---

## The sweep, and what a control row is for

Retrieval is free and perfectly repeatable. Phase 8's accidental A/A run proved
it: two runs of the same configuration matched every retrieval metric to four
significant figures, while generation moved a refusal and 600 ms of latency.

That asymmetry is worth exploiting. recall, coverage and MRR need no model
call, so a dozen configurations cost one embedding per question instead of a
dozen full evals.

**A control row is a configuration whose answer is already known.** Phase 9's
sweep carried two — one reproducing the baseline run, one reproducing the failed
hybrid run — and both matched exactly. Without them, the table would have been
a machine nobody had checked producing numbers nobody could verify. That check
was done by eye; it is now `control_matches`, run before the table prints.

**The sweep is diagnosis, never a verdict.** Choosing the best of N
configurations on the same questions that measure them is fitting the settings
to the test. Read it for whether something looks *structurally* different — a
monotone curve, as Phase 9 found — not for a winner.

---

## The three commands

```bash
uv run eurohistory sweep --baseline eval/runs/2026-08-05T1311Z
uv run eurohistory synthesize
uv run eurohistory judge-probe
uv run eurohistory judge eval/runs/<id>
```

`judge` reads a run off disk and writes `judgements.jsonl` and
`faithfulness.txt` **beside** it, never into `records.jsonl`. Records are
immutable (D-068), so re-judging with a better prompt can never damage the run
it read — the same reasoning that gave `rescore` its existence.

---

## What happened when it was run

**The probe run is the headline, and it failed first.**

`judge-probe` came back **4/6**. The two failures were the two probes the file
exists for. On the second one the judge wrote its reason as *"Source 3 states
Soviets agreed to pay six billion marks"* — and then graded the claim "Russia
**paid** six billion marks" as SUPPORTED. It saw the difference and did not act
on it.

Had the probe set not existed, a faithfulness number would have been published
from that judge, and the two defects Phase 6 found by hand would both have been
scored as fine.

Two prompt passes, each measured:

| Pass | Change | Probes |
|---|---|---|
| 0 | rules stated as standards | 4/6 |
| 1 | two named tests + four worked examples | 5/6 |
| 2 | must **quote the sentence carrying the fact** before deciding | **6/6** |

Pass 2 is the transferable lesson. The judge had been answering from the source
block's *title* and general subject; forcing it to quote one sentence made it
read that sentence's own subject. **A rule that forces an observation beats a
rule that states a standard.**

The worked examples in the prompt are deliberately *not* the probes — a 1925
protocol, a withdrawal only agreed to, a country's share read as a programme
total. Putting the Brest-Litovsk cases in the prompt would be memorising the
answers to the test.

**Then the metric found seven real defects.** On the Phase 8 reranked run: 25
answers judged, 185 claims, 178 supported, **97.7% mean faithfulness**, 21 of 25
answers fully faithful. Two of the seven are outright reversals rather than lost
qualifiers — one has Hungary assuming financial obligations the source assigns
to Romania, Yugoslavia and Czechoslovakia; another has a king persuading a prime
minister to resign where the source says he overruled him. Every citation
resolved and recall was unaffected, so nothing built before this phase could
have seen any of them.

**The synthetic set came out at the ceiling.** 124 questions, recall@5
**100.0%**, MRR 0.95. The prediction was "easier than the golden thirty"; the
result is "as easy as it is possible to be". The cause is structural: a question
written from a chunk, checked against that same chunk's section, is close to a
nearest-neighbour identity test. It works as a regression alarm at n=124 and it
cannot resolve anything subtle. That is a negative result about the instrument,
recorded as the D-078 verdict.

**The sweep reproduced both known runs**, control row and failed-hybrid row, to
the decimal. Two independent implementations agreeing is the strongest evidence
available that either is right.

---

## What this phase does not have

**No CI regression gate.** The plan named one; it was cut. A gate is only worth
having once the metric it gates on is trusted, and the judge has not yet been
run against a real run. It is the obvious Phase 11 candidate and it should use
the retrieval-only path, which is free and deterministic — generation is
neither.

**No answer relevance.** It overlaps heavily with faithfulness and would double
the judge surface before the first one has been validated.

**No before/after number in the usual sense.** Nothing in the query path
changed, so no retrieval metric will move. The deliverable is what the new
instrument can see that the old one could not, and the probe run is what proves
it can see it.
