# Roadmap — Phases 9 and beyond

The follow-up list. Advanced RAG techniques, evaluation, and improvement.

**Do not open this until Phase 8 in [plan.md](plan.md) is finished.** Every
technique here is a fix for a specific failure. Without Phase 7's failure log
you have no way to choose between them, and adopting a technique on faith is
how you end up with a system full of machinery you cannot justify.

---

## The gate rule

> **No phase in this document starts without a named failure from your eval
> that justifies it, and no phase ends without a before/after number in
> `decisions.md`.**

This one rule is what stops the roadmap from becoming a checklist of
techniques you have "done". If the eval cannot show the change helped, the
change does not land — you revert it and record that it did not work.

**A negative result recorded is worth more than a technique adopted on faith.**
It tells you something true about your corpus that no blog post can.

---

## What changes after Phase 8

**The shape of a phase changes.** Phases 0-8 *build* the system — each adds a
component that was not there. Every phase from here has the identical shape:

```
measure  ->  change exactly one thing  ->  measure again  ->  write it down
```

That is a loop, not a sequence. Learning the loop is worth more than any
individual technique below, and it is what separates people who tune RAG
systems from people who accumulate libraries.

**The ownership split ends.** By now the plumbing exists — CLI, config, Docker,
tests, eval runner. There is nothing left that you would learn nothing from
writing. From here you write all of it and Claude reviews.

**One change at a time. Always.** Two changes at once and you cannot attribute
the result. This will feel slow and it is the entire methodology.

---

## The committed order — Phases 15 to 24

**Fixed at the end of Session 15, and deliberately rigid.** Phases 9 to 14 each
picked the next phase from the previous one's evidence, and that worked. It also
meant every session reopened the question of what to do next, and twice the
answer was "the instrument is broken" — which is not a thing you can discover
your way out of one phase at a time.

So this table is **a queue, not a list of topics.** Serhiy's instruction, in his
words: *"we will be rigid by doing them. no step aside, we will do eval at the
end and analyze if there are any problems."*

| Order | Phase | Group | Cost | The failure it fixes |
|---|---|---|---|---|
| **15** | Questions matching the corpus | C | ~$0.15 | Nine themes graded by thirty questions about three of them |
| **16** | D-085 noise floor, on the finished set | C | ~$0.30 | "Did that change anything, or is that just drift?" |
| **17** | CI regression gate | B | free | Nothing stops a silent regression between phases |
| **18** | Front end | A | free | There is no way to use this that is not `curl` |
| **19** | Configurable retrieval and generation | A | ~$0.16 | Every knob needs a `.env` edit and a restart to try |
| **20** | Run an experiment from the page | A | ~$0.10 | Starting an eval needs a terminal, and the prediction rule runs on trust |
| ~~**21**~~ | ~~Streaming + TTFT~~ **done, D-095** | A | $0.0803 | 3,300-9,700 ms with a blank screen throughout |
| ~~**22**~~ | ~~Temporal retrieval~~ **done, D-096 — gate FAILED, default off** | D | $0.315 | A history corpus with no idea what a year is — **and it turned out to have one** |
| ~~**23**~~ | ~~Infobox / structured lookup~~ **done, D-097 — gate FAILED on 3 of 62, shipped on** | D | $0.25 | Facts Silver read and **Gold** discarded — fact rate 50.0% -> 85.7% |
| ~~**24**~~ | ~~Conversation~~ **done, D-098 — gate PASSED, on by default** | A | $0.30 | Follow-ups retrieve nothing — **and the real failure was that they get answered anyway.** recall@5 46.2% -> 92.3% |
| ~~**25**~~ | ~~The reranker's cold start~~ **done, D-099 — shipped, no gate owed** | A | $0.00 | First question of a session takes 7.4 s against 1.1 s warm — **and it was the model being loaded twice per request, at 88 MB not 487.** Cold passages 6.9 s -> 1.0 s |
| ~~**26**~~ | ~~Per-article thinning~~ **done, D-100 — gate FAILED, not shipped, setting defaults off** | D | $0.14 | `MAX_PER_DOCUMENT` caps chunks per *section*. **"Never once measured" was wrong — D-082 measured it in Phase 12.** Re-measured on nine themes: articles@5 2.7 -> 3.2, coverage@5 60.3% -> 58.3%, and the 35 multi-article questions did not move at all |
| ~~**27**~~ | ~~The refusal metric, and the claim splitter~~ **done, D-102 — shipped, no gate run** | C | ~$0.03 | Two instrument defects that turned out to be one event. Refusals 161 -> 208 across 27 runs; D-100's 9 -> 9 corrected to 12 -> 14; splitter probe 6/10 -> 10/10 |
| ~~**28**~~ | ~~Tracing~~ **done, D-101 — shipped, gate PASSED** | B | $0.1388 | Generation owns 87.1% of the clock; the follow-up rewriter costs 1.7x the whole retrieval chain |
| **29** | Prompt caching | B | ~$0.10 | An identical system prompt re-processed on every call |
| **30** | Cost ceilings | B | free | The page can start a paid run and there is no authentication anywhere in this system |
| **31** | Semantic answer cache | D | ~$0.20 | The same question in different words is paid for twice — **and the one item here that can make the system confidently wrong** |
| **32** | Paraphrase retrieval | D | ~$0.25 | **37.5% recall@5, the worst number in this eval** — and 93.8% at 20, with the misses sitting at ranks 7 to 10 |
| ~~**33**~~ | ~~Packaging and documentation~~ **done, D-110 — no gate owed** | B | $0.0026 | No `Dockerfile`, no `LICENSE`, no screenshot, and a README shaped like an argument rather than a README. **The image is 8.89 GB with torch and 732 MB without, for a reranker switched off since D-108** |
| **34** | The cleaner's blanks | D | ~$0.30 | `{{convert}}` is dropped, so sentences end in a hole and the model fills it and cites the hole. **Moved from 33 to 34 by Serhiy in Phase 33, not dropped: it is still the most serious known correctness defect in this system, and Phase 33 is not more important than it** |

**Queue extended in Session 24, and this time evidence did most of it.** "25+"
had been one row holding four unspecified items since Session 15; it is now
phases 25 to 31, and **four of the seven were added from this project's own
failure log rather than from any reading list.** 25, 26 and 27 each carry a
number that was measured and then parked, and 26 has been sighted four separate
times across Phases 5, 6, 7 and 23 without once being measured. That makes them
better candidates than anything left in the elective pool below, and it is why
they sit ahead of tracing and caching.

**The ordering inside 25-31 is Claude's and a different call would look
different.** The rule applied: things with a measured failure first (25, 26, 27),
then the ones that cannot change an answer (28, 29, 30), then the one that can
make the system confidently wrong (31), because that one wants every other
instrument working before it is trusted. Ordering by cheapness would put tracing
and cost ceilings first; ordering by user impact would put the cold start alone
at the top and everything else after Phase 24.

**32 and 33 were added at the end of Session 24 and both are at the back of the
queue on position, not on merit.** 32 carries the worst measured number in the
whole eval — paraphrase recall@5 at 37.5% against easy's 100% — and by evidence
alone it outranks everything from 25 onward except 26. 33 is a silent
fabrication mechanism with one sighting. **Appending them was the conservative
call and it is the owner's to overturn**; the rule that a queue is a queue is
what stops findings reordering it every session, and that rule is worth more
than either phase's position.

**Two of these are hygiene, not capability, and they are in the queue anyway.**
27 fixes the instrument rather than the system, and 30 exists because the API can
now spend money and nothing checks who asked. Neither will improve a single
retrieval figure. Both were parked findings that would otherwise never be
reached, which is exactly how a parked list becomes a graveyard.

**Queue changed in Session 19, twice, and neither time was it evidence that
changed it.** Serhiy asked to switch reranker, hybrid search, answering model and
`k` from the interface, and then to start an evaluation from the page. Those are
capability requests, not failures the eval named, so this is recorded as what it
is: **the owner added two phases and moved streaming down two places.** D-091
holds the spec for both.

They were kept out of Phase 18 because they touch `retrieval/` and
`generation/`, which ends that phase's gate exemption and would have mixed a UI
change with a retrieval change in one measurement.

**"18 and 19 must stay adjacent" is overridden, deliberately, and the argument
against it is recorded rather than deleted.** That rule was written before
either was scheduled, on the reasoning that a UI makes the blank screen the
first thing anyone notices — and Phase 18 confirmed it: measured in the browser,
questions took **3.3, 4.8, 8.9 and 9.7 seconds** with nothing on screen
throughout. Serhiy was shown that and chose the controls first anyway. Streaming
now runs at 21.

**Groups**, from the Session 15 audit: **A** nobody can use it. **B** nothing
stops it rotting. **C** the instrument cannot see change. **D** real capability
gaps with evidence behind them.

### Why this order, since it is now fixed

**15 and 16 come first because four later phases cannot start without them.**
This is dependency, not preference. Read the done-when clauses already written
in this document: temporal retrieval needs *"a temporal question subset added to
the eval"*, infobox lookup needs *"a factual-lookup question subset, added to
the eval"*, conversation needs *"its own eval cases"*, and the semantic cache
is judged on a **wrong-hit rate** that a broken eval cannot detect. Phase 15 is
one job standing in for four.

**17 follows 16** because a regression gate automates an instrument, and
automating an uncalibrated one just makes a wrong number arrive faster.

**18 and 19 were required to stay adjacent**, in that order, and that
requirement was overridden in Session 19 — see the note under the committed
order. The reasoning still stands and is now measured rather than predicted; it
is simply no longer the owner's priority.

**22 and 23 are the two capability gaps this corpus makes obvious.** Both were
strengthened by Phase 14: the corpus ran 1914-1945 and now runs 1914-2024, so
"after the war" is ambiguous across two world wars *and* a cold one.

**22 is done and its premise was wrong, which is worth leaving on the page
rather than editing away.** "The system has no idea what a year is" was written
from first principles and never measured. Measured, on eighteen temporal
questions written from the corpus, the system scored **87.5% recall@5 before any
of this phase's code existed** — because D-040 pastes the section heading into
the text that gets embedded, and the heading is where Wikipedia writes the
period. `Cold War — Renewal of tensions (1979–1985)` carries `1979–1985` inside
its own vector. The arm was built anyway, measured, failed the gate on recall@20
and coverage@5 with no recall@5 gain, and is off by default. See the D-096
verdict.

**The lesson for 23 and 24, both of which have done-when clauses written the
same way:** write the question subset and measure the failure *before* building
the fix. Phase 22 did that in the right order and it is the only reason the
result is trustworthy rather than flattering.

**Both followed it, and 24 is the third phase running whose premise was partly
wrong.** "Follow-up questions retrieve nothing" was half right — four of thirteen
were unfindable at any depth, but two hit at rank 1 before anything was built,
and the failure that mattered was not empty retrieval at all: the system
**answered thirteen of fourteen**, fluently and with citations, about whatever it
had found. See the D-098 verdict.

### What rigid means, and the one exception

**Rigid means findings do not reorder the queue.** A defect discovered in Phase
18 goes into `progress.md`'s parked list and is dealt with when the queue reaches
it. Phases 9-14 produced a parked list of a dozen items precisely because every
finding was treated as a candidate for the next phase.

**It does not suspend the gate rule.** Each phase still ends with a before/after
number in `decisions.md` and a prediction written before the run. "Eval at the
end" means the *analysis of whether the sequence as a whole worked* happens at
the end — not that individual phases skip their measurement.

**The one exception, stated in advance so it cannot be invented later:** if a
phase's result invalidates the *premise* of a later phase, the queue changes and
the change is recorded in `decisions.md` with the evidence. Example: if Phase 16
finds the noise floor is so wide that generation changes are unmeasurable at
thirty questions, the conversation phase's done-when has to be rewritten before
it starts. That is not stepping aside; that is a later phase losing its argument.

### Numbering

**The order column above is the phase number from here on.** The write-ups
further down are headed `# Topic N` and their numbers are *historical* — they
were assigned as topics were identified, before any queue existed, and they no
longer mean anything except "where the write-up is". They were renamed from
`# Phase N` in Session 15 for exactly that reason: two different numbering
schemes both calling themselves "Phase" is how the drift started.

| Queue | Write-up |
|---|---|
| **15** | `# Phase 15 — Questions that match the corpus` (below; the only queued phase with its own section) |
| **16** | D-085 in `decisions.md`, not here |
| **17** | Cut from `# Topic 10 — Eval hardening`; no section of its own |
| **18** | `# Topic 21 — Front end` |
| **19** | `# Topic 22 — Configurable retrieval and generation` |
| **20** | `# Topic 23 — Run an experiment from the page` |
| **21** | `# Topic 16 — Streaming and latency budget` |
| **22** | `# Topic 19 — Temporal retrieval` |
| **23** | `# Topic 20 — Structured / infobox retrieval` |
| **24** | `# Topic 13 — Conversation` |
| **25** | `# Topic 24 — The reranker's cold start` |
| **26** | `# Topic 25 — Per-article thinning` |
| **27** | `# Topic 26 — The refusal metric, and the claim splitter` |
| **28** | `# Topic 15 — Tracing` |
| **29** | `# Topic 17 — Prompt caching` |
| **30** | `# Topic 27 — Cost ceilings` |
| **31** | `# Topic 18 — Semantic answer cache` |
| **32** | `# Topic 28 — Paraphrase retrieval` |
| **33** | Packaging and documentation; no `# Topic` section — it fixes no eval failure and is owed none |
| **34** | `# Topic 29 — The cleaner's blanks` |

**Topics 24 to 27 were written in Session 24 and break the naming rule above on
purpose.** Every other `# Topic N` number is historical and means nothing; these
four were assigned after the queue existed, so for the first time a topic number
and a queue number describe the same thing at different offsets. Renumbering the
older ones to match would rewrite twenty-three headings and every reference to
them. The table is the mapping; the headings are just where the text lives.

**Three topics have no place in the queue and that is deliberate.**

- **`# Topic 11 — Chunking v2`** is unbuilt and no evidence has ever pointed at
  it. Across seven measured phases, not one defect has been a chunk-boundary
  problem.
- **`# Topic 12 — Contextual retrieval`** had three named triggers. Expanding
  past three themes fired one of them in Phase 14 — but recall@20 stayed at
  100%, which was the trigger arguing the other way. Weaker case now, not
  stronger, and it costs a model call per chunk over 54,903 chunks.
- **`# Topic 14 — Metadata filtering and routing`.** Nine themes finally make
  the facet real, but nothing in any eval has asked for it.

All three stay in this document. Any of them enters the queue only by the
exception above, with the evidence recorded.

---

# Phase 15 — Questions that match the corpus

**Why this phase exists**, quoted from the eval as the gate rule requires:

> The corpus grew **81%** — 30,362 to 54,903 chunks, 1914-1945 to 1914-2024 —
> and **not one retrieval number on an answerable question moved.** recall@5
> 75.0%, recall@20 100.0%, MRR 0.54, all identical. Verified real three ways.
> The cause: all 24 answerable questions are about 1914-1945 and all 615 new
> articles are about 1945-2024, so the new material never competes. Per
> question, 0 of 24 changed their verdict and 23 of 24 kept an identical rank.

Second failure, same run: **four of the six "unanswerable" questions became
answerable.** `chernobyl-cause`, `good-friday-agreement`, `srebrenica-1995` and
`brexit-why` are all correctly answered now, so the refusal check stands on two
questions.

Third, from Phase 13 and unresolved: the golden thirty **cannot measure a
generation change** either. Two runs, one change touching one answer, 28 of 30
answers different.

**The instrument has failed twice. This phase is the repair.**

## What gets built

- **~30 new questions covering the six new themes**, with ground-truth `doc_id`s,
  in the four kinds Phase 7 defined: easy, multi-article, paraphrased, and
  genuinely unanswerable.
- **Replacements for the four dead refusal questions.** Finding a real gap now
  means searching the nine-theme corpus for topics it truly lacks.
  `windrush-generation` survived and is the worked example: British
  decolonisation is in the corpus, the Windrush article is not.
- **A new baseline on the extended set**, with metrics reported **two ways** —
  the original thirty alone, and all sixty.
- A judged faithfulness run on the same set.

**The original thirty are not touched.** That is the load-bearing design
decision: keeping them as an untouched subset means every comparison back to
Phase 7 survives, while the new questions give the corpus something that can
actually see it.

## The rule that must not be broken again

**Questions come from reading the corpus, never from guessing it.** Three phases
in a row produced "unanswerable" questions the corpus answered perfectly well —
Phase 5 (the 2008 crisis, the euro), Phase 6 (`Kyiv` scored 0.817 from an article
nobody knew was there), Phase 7 (the set had to be rewritten from
`corpus_map.txt`). Every one came from writing a question against an assumption
about what was indexed.

## Concepts to be able to explain

- Why an evaluation only ever tests the corpus it was written from, and why that
  is not fixed by having more questions.
- Why the original thirty must stay byte-identical rather than being "improved"
  alongside the new ones.
- What ground truth costs to produce, and why it is written against sections
  rather than chunks.
- Why a question that stops being unanswerable is a *metric* failure and not a
  *system* failure.

**Done when:** the extended set is in `eval/questions.toml`, a new baseline and
faithfulness run are on disk, and `decisions.md` records the numbers for the
original thirty and the full set side by side — with the original thirty
reproducing `2026-08-06T1331Z`, which is this phase's control.

## Done — and what Phase 16 inherits

**Complete, D-087, baseline `2026-08-06T1703Z`.** Sixty questions, the golden
thirty byte-identical and reproducing the control exactly on two separate runs.

**Two things Phase 16 must carry, neither of which blocks the noise floor.**

1. **The extended answer keys are narrow, and it is measured.** Extended
   recall@5 is 62.5% against the golden 75.0%, and reading the results shows
   most of that gap is the key rather than retrieval — in six of the seven
   zero-coverage questions the top result was the same article at a different
   section, or a different article covering the same material. Cause: the
   candidate articles were listed by filtering to the six *new* themes, so
   `British Empire`, `Wirtschaftswunder`, `Trente Glorieuses` and `Schengen
   Agreement` were never on the list the keys were chosen from. The fix is to
   re-derive keys from **all 1,274 articles**, and it must be done from the
   corpus, never from a run's output.
2. **`recall@20` is no longer 100%** (91.7% extended). That is one of the three
   named triggers for contextual retrieval — and it fired for a reason that is
   not retrieval, so **the trigger is not met**. Recorded here so a later phase
   cannot cite the number without the reason.

**And one thing that makes Phase 16 easier than expected:** the golden thirty
returned identical retrieval figures on three separate runs. Retrieval variance
is zero, so whatever noise D-085 finds is entirely generation.

---

# Phase 16 — the noise floor

**Done, D-088 and its verdict in `decisions.md`.** Three identical runs of all
sixty questions. Unsupported claims 7 / 11 / 10, mean faithfulness 98.7 / 98.0 /
98.1%, refusals 7 / 7 / 7, every rank-based retrieval figure identical across
1,200 chunk slots. $0.94.

The decision rule lives in the D-088 verdict and is not repeated here. The short
form: **generation results need more than 4 claims, 0.7 faithfulness points or
2 fully-faithful answers to be readable; retrieval and refusal results are
readable at any size.**

**Two things Phase 17 inherits, and one correction.**

1. **The judge disagrees with itself on about a quarter of its own findings.**
   13 of 56 claim-versus-other-run comparisons had the same claim judged
   SUPPORTED in one run and NOT SUPPORTED in another. A regression gate built on
   an unsupported-claim count would therefore fail builds at random. This is the
   central design problem the gate has to solve, not a footnote to it.
2. **The claim splitter drops qualifiers it is told to keep**, manufacturing a
   defect that recurs in every run and so looks maximally structural
   (`stasi-scale`). `judge-probe` cannot see it, because probes bypass the
   splitter. Parked, not chased — the queue is rigid.

**Correction to what Phase 15 carried out.** "Retrieval variance is zero" is too
strong. **Rank** is deterministic: not one of 1,200 chunk slots changed. **Score**
is not: 35 slots moved by up to 0.0006, because the embedding API is not
bit-exact. Every published retrieval figure is unaffected at the precision it is
printed to.

---

# Phase 17 — the regression gate

**Done, D-089 and its verdict in `decisions.md`.** Spec written into
`decisions.md` before any code, because this phase had no section here — it was
one bullet in `# Topic 10 — Eval hardening`. `$0.00`, six pairs of real runs, in
`eval/runs/gate-D-089.txt`.

**That bullet's wording was not buildable and the correction stands.** *"The
eval runs on every commit and fails the build if recall drops"* needs a Qdrant
container with 54,903 points, a gitignored `data/` directory, an OpenAI key and
$0.08 per commit. The phase shipped two gates instead: the free half in CI
(lint, types, 486 tests, and a pinned baseline holding `2026-08-06T1703Z` to its
published figures), and `eurohistory gate <baseline> <candidate>`, run by hand at
the end of a phase.

**Three things Phase 18 and everything after it inherit.**

1. **Every phase from here ends with `evaluate` then `gate`**, and the gate's
   output goes in the verdict. Anything changed on purpose must be named with
   `--changed <field>`, and anything named must actually differ — that second
   half is Phase 8's dead switch as a check.
2. **Latency no longer gates anything.** D-088's `p50 > 600 ms` line was
   inherited from Phase 8's whole-run median of thirty questions; re-measured on
   three identical runs it swings **893 ms inside a thirty-question suite** and
   315 ms across all sixty. It is reported with its spread and cannot fail a
   build.
3. **The gate cannot see an improvement.** A metric that rises passes silently.
   It stops rot; it does not replace reading the run.

---

# Topic 9 — The other half of Phase 8

Phase 8 was hybrid search or reranking. This is the other one.

**Why both.** They fix different failures and they compose. Hybrid search
fixes *candidate generation* — the right chunk was never in the top 50 at all.
Reranking fixes *ordering* — the right chunk was at rank 8 and you only passed
5 to the model. Neither substitutes for the other.

**Hybrid search** — BM25 (sparse, keyword) plus dense (semantic), fused with
reciprocal rank fusion. Qdrant supports sparse vectors natively, so this stays
in one store.

Concepts to be able to explain: why BM25 beats embeddings on exact tokens
(flag names, error codes, version strings); how RRF combines two ranked lists
without needing comparable scores; what `k` in the RRF formula does.

**Cross-encoder reranking** — retrieve 50 candidates, score each against the
query with a cross-encoder, keep the top 5.

Concepts to be able to explain: how a cross-encoder differs from a bi-encoder
and why it is both slower and more accurate; why retrieve-many-then-rerank is
the standard modern architecture; what the latency cost is and where it is
paid.

**Done when:** both are in place, and `decisions.md` records the recall@5
improvement from each one *separately*.

---

# Topic 10 — Eval hardening

**Why this phase exists.** 30 handwritten questions caught your obvious
failures. They will not catch a regression in the long tail, and re-running
them by hand does not scale to the pace Phases 11+ need.

**What gets built**

- **Synthetic question generation** — an LLM reads your chunks and writes
  questions each one answers. Turns 30 test cases into 500.
- **A faithfulness metric** — is every claim in the answer supported by the
  retrieved context? This is the metric that catches hallucination.
- **Answer relevance** — does the answer address the question asked?
- **A CI regression gate** — the eval runs on every commit and fails the build
  if recall drops.
- Your original 30 stay as the golden set. Synthetic questions are for
  coverage, not ground truth.

**Concepts to be able to explain**

- Why synthetic questions are systematically easier than real ones, and what
  that does to your numbers.
- LLM-as-judge failure modes: position bias (prefers whichever came first),
  verbosity bias (prefers longer), self-preference (prefers its own model
  family). And what you did about each.
- The difference between retrieval metrics (recall, MRR, NDCG) and generation
  metrics (faithfulness, relevance) — and why a system can score well on one
  and badly on the other.
- Why a golden set must stay handwritten.

Frameworks worth knowing: RAGAS, TruLens, DeepEval, promptfoo. **Learn the
metrics before the framework.** They are thin wrappers over ideas you can
implement in an afternoon, and implementing them once is how you learn what
they actually measure.

---

# Topic 11 — Chunking v2

**Why this phase exists.** You wrote naive chunking in Phase 4 and read the
output, so you already know what is wrong with it. This fixes what you saw.

**What gets built** — pick based on your Phase 4 notes and Phase 7 failures:

- **Structure-aware splitting** — split on Markdown headers, never inside a
  table or infobox. Carry the header path into each chunk's metadata so a chunk
  knows it belongs to "Configuration > Environment variables".
- **Parent-document retrieval** (small-to-big) — embed small precise chunks
  for retrieval accuracy, but return the larger parent section so the model
  has enough context to answer.
- **Sentence-window** — the finer-grained version: embed single sentences,
  return them plus their neighbours.

**Concepts to be able to explain**

- The tension this resolves: small chunks retrieve precisely but answer badly;
  large chunks answer well but retrieve imprecisely.
- Why the retrieval unit and the generation unit do not have to be the same
  object — this is the key insight of the phase.
- What you decided about tables and infoboxes this time, and why it differs
  from Phase 4.

**Cost note:** any change here means re-embedding the whole corpus. Budget the
wall-clock time; the money is still cents.

---

# Topic 12 — Contextual retrieval

**Why this phase exists.** Your Phase 4 notes probably contain a chunk like
"It supports three modes." Three modes of *what*? The chunk is unretrievable
because the subject lives in a heading two hundred words earlier.

**What gets built**

- At index time, an LLM writes a one-or-two-sentence "where this sits in the
  document" blurb for each chunk.
- The blurb is prepended to the chunk text **before embedding**.
- The blurb may or may not be included in what you send to the generation
  model — decide, and record why.
- Prompt caching over the parent document makes this affordable.

**Concepts to be able to explain**

- Why this is an *indexing* fix and not a query-time fix.
- Why it composes with everything else — including hybrid search and
  reranking.
- The economics: one LLM call per chunk, paid once, at ~15,000 chunks.
- Why prepending context changes the embedding in a way that helps retrieval
  even though the underlying content is unchanged.

Anthropic's published results reported retrieval-failure reductions in the
tens of percent, and larger still when combined with BM25 and reranking. This
is the highest-value indexing technique on the list.

---

# Topic 13 — Conversation

**Why this phase exists.** The moment there is a second turn, "what about the
second one?" retrieves nothing, because it is not a question — it is a
reference to something in the history.

**What gets built**

- **Query rewriting** — an LLM turns the history plus the new message into one
  standalone question, and *that* is what gets embedded.
- Conversation storage. In-memory is fine to start; the decision of where
  state lives is the interesting part.
- A decision about context window management as history grows.

**Concepts to be able to explain**

- Why you rewrite the query rather than just embedding the whole history.
- What breaks when the rewriter is wrong, and how you would detect it.
- Why this needs its own eval cases — your Phase 7 questions are all
  single-turn and will not catch rewriting bugs.

**Shipped as Phase 24, D-098, $0.30, on by default.** A fourteen-case
`conversation` subset was written and measured first: **recall@5 46.2% -> 92.3%,
recall@20 69.2% -> 100%, `fact_rate` 60% -> 100%. GATE PASSED, 73 checks**, and
**0 of the 92 single-turn questions changed a chunk**, because a question with no
history never reaches the rewriter.

**All three questions above were answered.** The query is rewritten rather than
the history embedded, because one vector for a paragraph plus five words is a
vector mostly about the paragraph. State lives in the client — the tab already
holds the thread, and a server copy needs session ids in a system with no
authentication. The window is the last two exchanges, dropped rather than
summarised.

**What breaks when the rewriter is wrong, measured rather than imagined.** Three
of the fourteen cases are controls whose text is byte-identical to a question
already in the file, with unrelated history attached. **Two of the three were
rewritten anyway** — "the Soviet capital" became "Moscow", "the Easter Rising"
became "the Easter Rising in Ireland" — both adding world knowledge the prompt
forbids, both improving the rank, neither changing an answer. **The consequence
is for queue 32:** a paraphrase question asked as a second turn gets
un-paraphrased, so a multi-turn rewriter is an accidental query-expansion arm.

**And the one question whose recall fell is the one whose answer became correct.**
`c-euro-outside` went from a rank-5 hit answering about the Schengen Area to a
rank-11 miss correctly naming the six states that kept their own currencies. The
answer key is too narrow and was deliberately left alone so both runs stay
comparable.

---

# Topic 14 — Metadata filtering and routing

**Why this phase exists.** Your corpus has natural facets — repo, version,
section, document type. Right now you cannot use any of them.

**What gets built**

- Qdrant payload indexes on the fields worth filtering.
- Filtered search: "answer only from articles in the Cold War theme".
- **Filter extraction** — an LLM pulls structured filters out of a natural
  language question.
- Optionally **query routing** — classify the question and send it to the
  right index, or to a different tool entirely.

**Concepts to be able to explain**

- Why pre-filtering beats post-filtering, and what it costs the ANN index.
- What happens when a filter is too narrow and returns nothing — and what your
  system should do about it.
- When routing is worth it and when it is premature.

This phase pays back the Bronze provenance work from Phase 2. Every field you
chose to record there becomes a filter here; every field you skipped is now
unavailable.

---

# Topic 15 — Tracing

**Why this phase exists.** By now one query passes through rewriting,
retrieval, fusion, reranking, prompt assembly, and generation. When an answer
is bad, "which stage broke?" is not answerable by reading logs.

**What gets built**

- Structured tracing over the full chain for a single query.
- Latency and token cost attributed per stage.
- A way to replay one recorded query end to end.
- Optionally OpenTelemetry, or a purpose-built tool like Phoenix or LangSmith.

**Concepts to be able to explain**

- What a span is and why traces are trees rather than lines.
- Why you cannot debug a multi-stage RAG system without this.
- Which stage is actually consuming your latency budget — and whether that
  matched your guess.

**Shipped as Phase 28, D-101, $0.1388 — and both premises above are wrong,
which is left standing rather than edited away.** "Six stages": **eleven exist
and six run.** `fusion` is named here and never executes on the shipped
configuration, and "retrieval" is one word covering embed, dense and rerank,
which differ from each other by 9:1 in cost. "Not answerable by reading logs"
survived completely and was worse than written — the live `/ask` path had **no
timer in it at all**.

**generate 87.1% of the wall clock, search 11.7%, and inside search the
reranker owns it: rerank 287 ms, embed 149 ms, Qdrant 34 ms, thin 0.0 ms.**
GATE PASSED, 73 checks, every retrieval figure identical to the decimal —
which is what this phase was required to produce.

**The number nobody had:** the follow-up rewriter costs **795 ms**, which is
**1.7× the entire retrieval chain it feeds**, on the 14 questions that carry
history. D-098 shipped it on a recall argument and nothing could price it until
now.

**The prediction came out three of seven.** The guess was right in direction on
both halves; the reranker is a fifth bigger than I gave it room for and Qdrant
is half. The two bands on *shares of the total* both missed by 0.3 points
despite being arithmetic I had already done — a share has two moving parts, and
`generate_ms` rose 16.6% between runs on identical token counts.

**One impossible check appeared to fail on 4 of 106 and the check was wrong:**
the excess was +0.1 ms every time, which is the 0.1 ms rounding I had
introduced myself, compared against a one-span tolerance. Fifth sighting of *a
metric is code and can be wrong*, and the first where the wrong metric was
written in the same phase as the thing it checked.

**OpenTelemetry was proposed under obligation 7 and rejected** — it exists to
carry context across processes, and this is one process, one thread, eight
spans. Storage is a typed `trace` field on `EvalRecord` plus an SSE event, not
the `extra` dict.

---

# Topic 16 — Streaming and latency budget

**Why this phase exists.** Phase 7's baseline: p50 **4,257 ms** end to end, of
which generation is **4,058 ms**. Nothing reaches the caller until the whole
answer is finished, so the screen is blank for the entire four seconds. That is
acceptable for `curl` and unusable behind a UI.

**What gets built**

- `POST /ask` streams instead of returning one blob — server-sent events, one
  event per token or small group of tokens.
- The retrieved sources are the **first** event, emitted before generation
  starts. They are already known at ~500 ms.
- **Time to first token added to `metrics.py` first**, before any change. The
  gate rule needs a before number and the eval does not currently record one.
- A decision on what the non-streaming path becomes: kept for the eval runner
  and for clients that want one JSON object, or removed.

**Concepts to be able to explain**

- The difference between total latency and time to first token, and why only
  the second one is what a user experiences.
- Why streaming does not make anything faster, and why it is still the largest
  available win.
- What breaks when an error occurs mid-stream — the status code was sent at
  byte zero and cannot be taken back.
- Why the sources can be emitted early but the citations cannot.

**Done when:** a before/after TTFT number in `decisions.md`, measured by the
eval, not by feel.

**Explicitly not in this phase:** shortening answers. Fewer output tokens is
the other half of the clock, but it trades answer quality for speed and must be
judged by the eval's quality metrics, not its timings. It belongs with prompt
work.

**Shipped as Phase 21, D-095, $0.0803.** `POST /ask` streams when the caller
sends `Accept: text/event-stream`; there is no second endpoint. TTFT went into
`metrics.py` before anything changed, and a run made before streaming reads its
first token as arriving at the end — so the "before" was free.

**p50 time to first token 3,521 ms -> 1,121 ms, and every rank figure identical.**
Gate PASSED, 34 checks, nothing declared changed. Seven of seven predictions
held, including the impossible one, which was checked per question rather than
on the average: no question's TTFT fell below its own `search_ms`, 0 of 60. Read
below the gate, **60 of 60 questions returned the identical twenty chunks in the
identical order**.

**Warm and cold, in a browser:** warm first word 1,202-1,671 ms, sources on
screen at 449-982 ms. **Cold 7,400 ms** — the 487 MB reranker loading inside the
first request, unchanged and untouchable by streaming. That load is now the
largest single item on the clock and is parked as its own phase.

---

# Topic 17 — Prompt caching

**Why this phase exists.** The system prompt in `generation/system_prompt.md` is
identical on every call and is re-processed every time. The retrieved context
is not, so only the front of the prompt is cacheable — which is exactly the
part that never changes.

**What gets built**

- Prompt caching enabled on the generation call, with the static prefix ordered
  first so it can be cached at all.
- Cost per query recorded in the eval, before and after.

**Concepts to be able to explain**

- Why caching only works on a *prefix*, and what that implies about prompt
  ordering.
- Why this cannot change a single answer, and why that makes it the safest
  change in this document.
- The cache lifetime, and why a low-traffic system may never hit it.

**Done when:** a before/after cost-per-query number in `decisions.md`.

---

# Topic 18 — Semantic answer cache

**Why this phase exists.** Two users asking the same question in different
words pay full generation cost twice.

**What gets built**

- Answers keyed by *query embedding similarity*, not by exact string.
- A similarity threshold, chosen from data — Phase 7's score bands are the
  starting evidence.
- An invalidation rule: any change to the corpus, the prompt or the model must
  empty the cache.

**Concepts to be able to explain**

- Why the **wrong-hit rate** is the metric that matters, not the hit rate. A
  cache that answers a slightly different question is worse than no cache.
- Why the threshold cannot be tuned on the same questions used to test it.
- Why this is the one item in this document that can make the system
  confidently wrong, and what that costs a system whose selling point is
  grounding.

**Done when:** hit rate *and* wrong-hit rate in `decisions.md`. If wrong hits
are not zero, the honest outcome is to revert.

**Shipped as Phase 31, D-105 and D-106, $0.1572.** **Hit rate 50.0% on 20
held-out rewordings; wrong-hit rate 0.0% on the 10 answers actually served, all
ten read by hand.** Threshold 0.8124, tuned on 20 disjoint pairs by the only
rule this write-up leaves open -- the lowest bar admitting none of their
near-misses. The D-089 gate passed 73 checks with every figure byte-identical.

**Two of this write-up's premises were wrong and are left standing rather than
edited away.** "Two users" is not a thing this system has -- one user,
localhost, no authentication, which D-104 had already established. And the eval
cannot measure this at all: it asks each question once, so a perfect cache
fires at most 4 times in 106, and 3 of those 4 are the conversation controls,
which a cache would destroy by answering them with the golden question's
answer. **The cache is therefore off inside the eval by construction** -- the
runner passes no vector -- and 0 cache spans across 106 records is the proof.
A purpose-built probe, `eval/cache_probes.toml`, is the instrument instead.

**The finding that should be read before this feature is ever trusted further:
in 4 of 40 pairs the near-miss sits closer to the original than the genuine
rewording does.** Including the only real paraphrase pair in the eval itself --
`weimar-hyperinflation-cause`, whose true paraphrase scores 0.5695 while "how
was the hyperinflation brought to an end" scores 0.7548. No threshold separates
those. It is the same weakness Topic 28 exists for, and it is now evidence for
queue 32 rather than an argument against what shipped here.

---

# Topic 19 — Temporal retrieval

**Why this phase exists.** This is a corpus about the 20th and 21st centuries
and the system has no idea what a year is. "What happened in Europe between
1945 and 1949" retrieves on the *words* 1945 and 1949, so a chunk mentioning
1945 once outranks a chunk covering the whole period. Every generic RAG
roadmap misses this because most corpora are not about time.

**What gets built**

- Date and period extraction at index time — a `year_start` / `year_end` span
  per chunk, written into the Qdrant payload.
- Range filters: retrieve only chunks whose span overlaps the question's.
- **Temporal expression parsing in the query** — "after the war", "the
  interwar years", "the early Cold War" resolved to actual year ranges.
- A decision on chunks with no extractable date, which will be many.

**Concepts to be able to explain**

- Why embeddings are bad at numbers and ranges, and what a vector actually
  does with "1945".
- The difference between the date a chunk *mentions* and the period it
  *covers*, and why only the second is useful.
- What happens to recall when a filter is applied before the ANN search, and
  why an over-narrow date filter is worse than none.
- Why a relative expression ("after the war") is ambiguous in a corpus that
  contains two of them.

**Done when:** a before/after recall@5 on a temporal question subset added to
the eval — the existing 30 do not test this.

---

# Topic 20 — Structured / infobox retrieval

**Why this phase exists.** Phase 3 reads every article's infobox to learn what
kind of thing it is, then throws the contents away. Wikipedia infoboxes are
clean structured data — dates, leaders, casualties, treaty signatories,
populations — and the system currently answers "how many died at Verdun" by
hoping a sentence somewhere says so.

**What gets built**

- Infobox key/value pairs preserved into Silver as a real column rather than
  discarded after the type is read.
- A structured store for them, and a path that answers factual lookups from it
  rather than from prose.
- A routing decision: which questions go to structured lookup, which to
  semantic search, and what happens when both have something.
- Optionally, the structured facts injected into the prompt alongside chunks.

**Concepts to be able to explain**

- Why a vector search is the wrong tool for "when was X signed", and what the
  right one is.
- Why hybrid *retrieval* (dense + sparse) and hybrid *storage* (vectors +
  structured) are different ideas that get the same name.
- What it costs to rebuild Silver and Gold to carry a field you previously
  dropped — and why Bronze being immutable is what makes that possible at all.
- How to resolve a conflict between an infobox value and a sentence.

**Done when:** a before/after on a factual-lookup question subset, added to
the eval.

**Note.** This phase reaches back into Phase 3. It is the clearest payoff of
the medallion layout: Bronze still holds every byte of raw wikitext, so a
field discarded eight phases ago costs a rebuild, not a re-crawl.

**Shipped as Phase 23, D-097, $0.25 — and the note above is wrong, which is
left standing rather than edited away.** Phase 3 never discarded the infobox:
D-031 kept the whole box and Silver has carried it on every row since. The
discard is D-041's, at Gold, and it was deliberate. So no Silver rebuild was
needed and no re-crawl was ever in question — the phase reaches back into
**Phase 4**, and its whole cost was one re-chunk and 1,524 embeddings at $0.008.

**A fourteen-question `factual` subset was written first**, nine of them facts
found in a box and nowhere in their own article's prose, out of 715 such facts
counted corpus-wide. **`fact_rate` 50.0% -> 85.7%**; on the nine, 22.2% ->
77.8%. Golden, extended and temporal retrieval identical throughout.
**GATE FAILED, 3 checks of 62** — two are refusals correctly becoming answers,
which D-089 already recorded the gate cannot distinguish from damage, and the
third is 0.001 of golden top-1 score.

**The routing decision this write-up asks for was made and it was "none".** The
box competes in the same dense search; no classifier. It cost one golden answer
— `chernobyl-cause` lost its mechanism to the box's `cause:` field — and that is
the strongest argument on record for the router, held at one sighting.

**The conflict rule it asks for was also made: neither source wins.** Both are
shown to the model. Measured on `f-hungary-1956-soviet-dead`, where the box says
722 Soviet dead and the prose says 699, the answer stayed at 699 in both runs.

**And the phase found a hallucination it did not cause.** `Second Polish
Republic — Geography` reads "The country's total area... was ." because
`clean.py` drops `{{convert}}`; the model filled the blank with the correct
figure from its own weights and cited the sentence that had the blank. **A
truncated sentence is a hallucination surface.** Parked for whatever phase
reopens `clean.py`.

---

# Topic 21 — Front end

**Done as queue 18. D-090 and its verdict in `decisions.md`.** One HTML page at
`GET /`, one call to `/ask`, citations clickable and each carrying the passage
the model was given. 492 tests, no new dependency, ~$0.007. The exception below
was used exactly as written and not re-argued; the evidence in place of a gate
run is an empty `git diff` over `retrieval/`, `generation/` and `pipeline/`.
**What it found that the eval never could:** the first question of a session
takes 9.7 s because the reranker loads inside it, against a p50 of 3,822 ms.
That is Phase 19's problem, and streaming cannot fix it.

**Why this phase exists.** There is no way to use this system that is not
`curl` or `scripts/ask.ps1`. Everything built so far is judged by an eval
runner reading JSON; nobody has ever watched an answer arrive.

**This phase does not obey the gate rule, and that is deliberate.** Every other
phase in this document starts with a named failure from the eval. A front end
has none — the eval cannot measure something it has no metric for, and "I
cannot show this to anyone" is a real problem that no recall figure will ever
report. Recorded as an exception rather than smuggled in as a technique.

**The consequence, stated before any code:** the moment a UI exists,
**streaming stops being optional.** p50 was 4,257 ms when this was written and
is **4,823 ms** as of `2026-08-06T1331Z`, with generation as 4,393 ms of it, and
nothing reaches the caller until the whole answer is finished. Behind `curl`
that is a pause. Behind a UI it is nearly five seconds of blank screen on every
question, and it is the first thing anyone will notice. **This is now scheduled
rather than expected: queue 18 then queue 19, back to back, measured
separately.**

## What Serhiy decides

The whole shape, and it is one decision made of three:

1. **Where the UI lives.** Templates served by the existing FastAPI app, or a
   separate front-end project talking to it over HTTP. The first keeps one
   process, one deploy and no build step; the second is what a real product
   looks like and brings a toolchain with it.
2. **What a question looks like on screen.** A search box and an answer is the
   minimum. The interesting question is what happens to the **sources** —
   Phase 6 built inline `[n]` markers and a citation list precisely so a reader
   can check a claim, and a UI that hides them throws away the phase that made
   this system trustworthy.
3. **What it must not do.** No new endpoint that bypasses `/ask`. The eval
   runner and the UI must go through the same path, or the numbers stop
   describing the thing people use.

## What Claude decides

Templating and static file wiring, the CORS decision if the answer to 1 is
"separate project", the request/response plumbing, and the tests.

## What gets built

- One page: ask a question, see the answer, see the sources it cites.
- Citation markers in the answer are clickable and resolve to the source
  passage — the `oldid` URL already on every `SearchResult` is the permanent
  link back to Wikipedia at the exact revision indexed.
- An honest failure state. `/ask` returns 503 when the model is unreachable and
  the corpus genuinely refuses with "Not in the sources." — both must look
  different from each other and neither may look like a bug.
- Nothing else. No history, no login, no settings panel. Those are Phase 13
  (conversation) and they have their own failures to justify them.

## Concepts to be able to explain

- Why the API and the UI stay separate processes even if they ship together,
  and what `api/` must never import (the same rule as `pipeline/`).
- Why the sources are the product here rather than a footnote — an ungrounded
  answer with a nice interface is a worse thing than no interface.
- What a user actually experiences as "slow", and why it is time to *first*
  token rather than total latency. This is Phase 16's argument, and building a
  UI is what turns it from a number into something you can see.

**Done when:** a question can be asked and answered without a terminal, the
citations are checkable from the page, and `uv run pytest` still passes with
Docker stopped.

**Explicitly not in this phase:** streaming (Phase 16), conversation history
(Phase 13), authentication, and deployment. Each is its own change with its own
before and after.

---

# Topic 22 — Configurable retrieval and generation

**Queue position 19.** Added by request in Session 19, not by a failure the eval
named — see the note under the committed order, and D-091 for the spec. Written
in this document's own shape so it is judged like every other phase.

**Why this phase exists.** Four knobs decide what this system does, and every
one of them needs a `.env` edit and a process restart to try: `reranker_enabled`
and `reranker_model`, `hybrid_enabled`, `generation_model`, and `k`. Phase 8
proved how expensive that is — a run shipped with the reranker flag still false
and 337 tests passed against a feature that did nothing, because nothing on any
screen said which configuration was live.

**What gets built**

- Optional overrides on `POST /ask` — `hybrid`, `reranker`, `model`, `k`. **No
  new endpoint**: D-090's third decision stands, and the eval and the page must
  keep running the same path.
- The controls sit **in the header of the ask view**, and again on the
  evaluation view, where they describe the run to be started rather than the
  question to be asked.
- **Not the run button.** That is queue 20 and its own write-up below, split out
  because background-job state has nothing to do with the knobs and is the
  larger job of the two.
- A settings row on the ask view, and the live configuration shown next to it,
  in the same panel style the evaluation view uses for a run's conditions.
- **The answer states which configuration produced it.** An answer whose
  settings are invisible is Phase 8's dead switch waiting to happen again.
- A decision on reranker loading: each is ~487 MB and ~6 s on first use, and
  both stay resident once loaded. Either a small allow-list, or one at a time.

**The hazard to design around, not discover.** `BAAI/bge-reranker-base` is the
value in `config.py` today and Phase 8 measured it as broken — recall@5 41.7%,
paraphrase 0.0%, "Treaty of Rome" ranked above East German emigration, and two
unrelated documents given an identical 0.000. A dropdown offering it without a
warning hands someone a known-bad result to screenshot.

**Concepts to be able to explain**

- Why a per-request override is safe where a second endpoint is not.
- What a cached service is, and why `get_settings()` being cached is exactly why
  these are restart-only today.
- Why "the numbers describe the thing people use" stops being true the moment a
  UI can run a configuration the eval never measured — and what showing the
  configuration on the answer buys back.
- Why the noise floor is per-configuration: D-088 measured it on
  `gpt-4.1-mini`, so a different answering model has no floor until one is
  measured for it.

**Done when:** the four knobs are switchable from the page, every answer names
the configuration that produced it, and `decisions.md` records a before/after
from `evaluate` then `gate` on the one knob whose flip is measured — hybrid
being the cheapest, and `2026-08-05T1834Z` already holding a `bm25+rrf(k=60)`
run to compare against.

**Explicitly not in this phase:** persisting a chosen configuration between
sessions, per-user settings, and changing any default. The defaults are settled
decisions with written reasons; this phase makes them visible and temporarily
overridable, not different.

---

# Topic 23 — Run an experiment from the page

**Queue position 20.** Added by request in Session 19. Split from `# Topic 22`
because the knobs and the job runner share a screen and nothing else: one is a
parameter passed to an existing call, the other is the first piece of state in
this system that outlives a request.

**Why this phase exists.** Starting an evaluation means a terminal, and the rule
that makes an evaluation worth anything — write the prediction before the run —
is enforced by nothing but discipline. Phases 8 and 15 both recorded predictions
that missed, and both were honest only because a person chose to be.

**What gets built**

- A control on the evaluation view that runs `evaluate` with the current knob
  settings and writes a run directory exactly as the CLI does.
- **A required prediction.** The confirm control stays disabled until it is
  typed, and it is written to `prediction.txt` in the run directory *before the
  first question is asked*, so it cannot be edited once numbers exist.
  **Obligation 9 enforced by the interface rather than by discipline** — which
  is stronger than what the CLI does today.
- **The cost, stated and confirmed before anything is spent.** Question count
  times the per-question cost measured on the previous run.
- Automatic `--changed` declaration. The page knows which knobs it changed; the
  gate already refuses a comparison where a declared change did not happen.
- **The gate run when the eval finishes**, against a baseline chosen in the same
  dialog, its verdict shown beside the new run. A run without its comparison is
  half a result.
- One run at a time, cancellable, with progress. Sixty questions take about four
  minutes.
- Preconditions reported as an actionable refusal, not as a failure four minutes
  in: Docker up, an API key present, Gold data on disk.

**Concepts to be able to explain**

- Why a request that outlives its response needs somewhere to keep its state,
  and what breaks if that state lives in a module-level variable.
- Why the prediction has to be written *before* the run and not merely *first*
  in the file.
- Why this is the point where the API becomes able to spend money, and what that
  would mean the day it is not on localhost. There is no authentication
  anywhere in this system.
- Why a progress bar for a four-minute job is a design decision about failure,
  not about reassurance.

**Done when:** a run started from the page is byte-comparable with one started
from the CLI, its `prediction.txt` predates its `records.jsonl`, and
`decisions.md` records a gate verdict produced by the button rather than by
hand.

**Shipped as Phase 20, D-094, $0.085.** All three met. Run `2026-08-08T1327Z`
differs from a CLI run's `meta.json` in `run_id`, `started_at`, `git_sha` and
`note` alone; `prediction.txt` predates `records.jsonl` by **201.9 seconds**;
the gate passed 31 checks and its verdict is in `decisions.md`. Beyond the
done-when: **60 of 60 questions returned the identical twenty chunks in the
identical order** as the baseline run.

---

# Topic 24 — The reranker's cold start

**Queue position 25.** Added in Session 24 from a measurement, not a wish.

**Why this phase exists**, quoted from the D-095 verdict:

> Warm: passages on screen at 449-982 ms, first word at 1,202-1,671 ms. **Cold:
> first word at 7,400 ms** — the 487 MB reranker loading inside the first
> request. That is now the largest single item on the clock and streaming cannot
> touch it.

Six and a half seconds, paid by whoever asks the first question after a restart,
and paid again by the second person if the process was recycled. **The eval has
never seen it**: the runner asks 92 questions in a row, so question one absorbs
the load and the other 91 report a p50 that describes a machine nobody meets.

**What gets built**

- The model loaded when the process starts rather than when the first request
  arrives, so the cost lands where nobody is waiting on it.
- A decision on what `/health` and the readiness endpoint say while it loads.
  A server that answers "ok" and then takes 7.4 s is lying by the only
  definition that matters.
- A decision on the test suite: 628 tests pass with Docker stopped and must keep
  passing without downloading 487 MB.

**Concepts to be able to explain**

- Why a lazily-loaded singleton is the right default and the wrong one here, and
  what "amortised" hides when the sample size is one.
- Why an average over 92 questions cannot see a cost paid once.
- What a readiness check is for, as distinct from a liveness check — the
  distinction parked back in Phase 1 and never built.

**Done when:** a cold first-token number in `decisions.md`, measured the way
D-095 measured it — by hand, in a browser, on a process that has just started.
**The eval cannot produce this number and must not be used to claim it.**

**Shipped as Phase 25, D-099, $0.00 — and the quote above is wrong in both of
its facts, which is left standing rather than edited away.** The model is
`cross-encoder/ms-marco-MiniLM-L6-v2` at **88 MB**, not 487; and the 4,885 ms
`torch` import it blames was never in the request at all, because `rerank.py`
imports it at module level and uvicorn has always paid it before binding.

**What was in the request was the model being constructed twice.** The page
sends a reranker name on every call, so `_overridden()` was always true: FastAPI
resolved `Depends(get_generation_service)` and loaded the model, then the handler
built a configured service and **loaded the same model again into a second
object** — 2,181 ms and 2,066 ms, both copies resident for the life of the
process. One line made `get_reranker` delegate to `get_named_reranker`; a
blocking `lifespan` moved what remained to startup.

**Measured by hand on five uvicorn processes: cold passages 6.9 s -> 1.0-1.1 s,
cold first word 7.7 s -> 1.5-2.8 s**, against 0.6-0.7 s and 1.3-1.4 s warm. The
eval was not run and produced none of it. Retrieval is bit-identical — the same
five chunks at the same scores. **All three decisions were made**: a blocking
lifespan; `/health` stays 200 while `/ready` is refused-then-503-on-failure,
because a socket that is not open is how "not ready" is said; and a `warm_start`
setting, off in `conftest.py`, keeps 653 tests offline in 7.2 s.

**The residual is not the reranker.** `OpenAIEmbedder` and `OpenAIGenerator`
hold separate clients and separate connection pools, so a process pays two first
HTTPS connections. Worth ~350 ms. Parked.

---

# Topic 25 — Per-article thinning

**Queue position 26.** The oldest unmeasured finding in this project.

**Why this phase exists.** `MAX_PER_DOCUMENT = 2` caps chunks per `doc_id`,
which is a **section**. It has never capped per `page_id`, which is an
**article**. Sighted four times and measured zero:

| Phase | What it looked like |
|---|---|
| 5 | "how did Versailles and Trianon differ" returned five Versailles sections and zero Trianon |
| 6 | every citation marker piled onto the last sentence, because five chunks said the same thing |
| 7 | `versailles-vs-trianon` scores a **hit** at rank 5 with 33% coverage; easy questions averaged **1.1 distinct articles in five slots** |
| 23 | the Austrian Empire infobox chunk was thinned out of the top twenty by its own article's lead |

Phase 7's own baseline called it "the leading Phase 8 candidate". Phase 8 did
reranking instead, and nine phases later it is still a one-line change with four
observed failures behind it and no before/after number.

**What gets built**

- A second cap, per `page_id`, alongside the existing per-`doc_id` one.
- A decision on the value, defended against the measured cost: the current
  golden run buys **2.8 distinct articles in five slots**, and easy questions
  buy 2.1.
- A decision on what it does to the infobox chunks from D-097, which share a
  `doc_id` with their article's lead and would now also share an article cap.

**Concepts to be able to explain**

- Why "distinct articles at 5" is the metric this phase moves and recall is not.
- Why a comparison question is the case that exposes it, and why coverage@5 sees
  it while recall@5 cannot.
- What a cap costs when the right answer genuinely is five chunks of one
  article, and how you would know that had happened.

**Done when:** a before/after on `coverage@5` and `mean_distinct_articles_at_5`
in `decisions.md`, with the multi-article questions reported separately.

**Shipped as Phase 26, D-100, $0.14 — and "measured zero" above is wrong, which
is left standing rather than edited away.** It was measured in Phase 12 as D-082,
a six-arm sweep whose verdict was already *not shipped*. What was genuinely
unmeasured is the corpus: D-086 recorded D-082 as **unverified on the corpus that
exists**, and D-082's own closing line asks for the re-run this phase did.

**Articles@5 2.7 -> 3.2, coverage@5 60.3% -> 58.3%, recall@5 80.4% -> 80.4%,
`fact_rate` 89.5% -> 78.9%. GATE FAILED, 17 checks. Not shipped**; the setting
exists and defaults to off. **The 35 questions whose key spans more than one
article — the whole case for the phase — moved by nothing at all.**

**The number that closes four sightings across five phases:** of 182 expected
sections, only **14 (7.7%)** sit where a per-article cap could promote them.
32 more sit at rank 6-20 but belong to an article that already holds a slot, so
the cap moves them *further away*; 52 are past rank 20 or absent from a 100-deep
pool entirely. Slot allocation is not where this system loses, and that is now a
measurement rather than an argument.

**Two treaty dates were lost to the D-097 interaction.** The infobox shares its
article's lead `doc_id` and scores below the prose, so it sits at slot 4 or 5 —
exactly what a cap removes. `f-versailles-in-force` and `f-saint-germain-in-force`
both went from a correct dated answer to a refusal, and coverage@5 could not see
it because coverage is scored on sections and the box shares one.

**Two findings it did not go looking for:** the follow-up rewriter is **not
deterministic** — 2 of 13 rewrites differ between runs, so the conversation suite
has an unmeasured noise floor and D-098's "0 of 92 chunks changed" says nothing
about the 14 that carry history. And both new refusals opened "The sources do not
cover", so the refusal count sat at 9 -> 9 while two answers stopped answering —
queue 27's defect caught live.

---

# Topic 26 — The refusal metric, and the claim splitter

**Queue position 27.** Both are instrument defects. Neither improves a single
answer, and that is the argument for doing them rather than against it.

**Why this phase exists.** Two measurement bugs are on the record, both found by
reading and both still live:

> `REFUSAL` matches only the exact phrase "Not in the sources". The D-096
> verdict records an answer opening "The sources do not cover what NATO agreed
> at its 2023 summit in Vilnius" — a correct refusal, scored as an answer.

> The claim splitter drops the qualifiers it is told to keep. `stasi-scale` is
> flagged unfaithful in all three D-088 runs and is a **false positive**: the
> splitter dropped "91,015 people full-time, including" and the verdict judge
> correctly failed the fragment the splitter had made. `judge-probe` cannot see
> this, because probes bypass the splitter.

**What gets built**

- A refusal test that is not one hardcoded string. The candidates are a short
  phrase list, a structured field the model fills, and asking the prompt to emit
  a marker — and the third changes the prompt, which makes it a generation
  change and not a metric change.
- A probe for the **splitter**, not only the verdict judge, on claims whose
  correct split is written down by hand first.
- A rescore of every run already on disk, which is free, and a note of every
  published refusal figure that moves.

**Concepts to be able to explain**

- Why a metric is code, and why this is the fourth time in this project that a
  wrong one was worse than no metric at all.
- Why a two-stage judge has two places to be wrong and why probing only the
  second is how a manufactured defect survives three runs.
- Why fixing a metric never costs another model call, and what that says about
  where raw observations should be stored.

**Done when:** both probes exist, every run on disk is rescored, and
`decisions.md` records which published numbers changed and by how much.
**A phase whose only output is "three earlier figures were wrong" has succeeded.**

**Shipped as Phase 27, D-102, ~$0.03 — and twelve figures were wrong, not
three.** Refusals across all 27 runs on disk **161 -> 208**, the shipped run
**9 -> 12 of 106**, the CI pin **7 -> 8 of 60**, `answers_with_no_citation`
**10 -> 0**. The splitter probe went **6/10 -> 9/10** on the fix and 10/10 after
one of the probes was found asserting the wrong rule; `stasi-scale` cleared from
0.909/0.833/0.833 to **1.000**.

**D-100's "refusals 9 -> 9" is corrected to 12 -> 14**, and the two added are
exactly the treaty dates Phase 26 found by hand — the gate would have failed on
refusals had the instrument been right.

**The finding worth more than the headline: the two defects were one event.**
`seveso-1976` opens "The sources do not cover", so the old metric did not skip
it, so the splitter was handed a refusal and made five claims out of it, one of
which the judge failed — and that claim is one of D-088's three "recurring
defects verified against the Wikipedia text". It was the instrument, twice over.
**D-088's noise floor moves with it**: mean faithfulness 98.7/98.0/98.1% ->
99.0/98.4/98.5%, range 0.7 -> 0.6 points, answers judged 53 -> 52.

**And the splitter's defect is not the one on record.** It does not drop
qualifiers so much as **detach them by splitting too eagerly** — "signed on 14
June 1985 by five EEC member states" became one claim with the date and no
signatories and one with the signatories and no date. Three of four probe
failures are that, and neither half dropped a word.

**Nine of twelve sealed predictions held. One was lost to a recount** forced when
a 27th run appeared on disk mid-session, and two missed: I predicted two kinds of
published figure would move and three did (the faithfulness table was one step
further down a causal chain I had already written out), and the test-count band
was drawn on test *functions* while the suite counts *cases*.

---

# Topic 27 — Cost ceilings

**Queue position 30.** The one item here that is about what happens when this
stops being a laptop.

**Why this phase exists.** Since Phase 20 the web page can start an evaluation
that spends money, and **there is no authentication anywhere in this system**.
The confirm dialog states the cost and a person agrees to it, which is a
convention, not a control. Nothing caps a single query, nothing caps a day, and
nothing notices a loop.

**What gets built**

- A per-run and per-day ceiling, enforced in code rather than in a dialog.
- A decision on what the system does at the ceiling: refuse, queue, or degrade
  to a cheaper model. All three are defensible and they are not the same
  product.
- The per-question cost already computed by `eval/cost.py`, tracked live rather
  than only after the fact.

**Concepts to be able to explain**

- Why a confirmation dialog is not a limit.
- Why the ceiling belongs next to the code that spends, not next to the code
  that asks.
- What this system would need before it could be reachable from anywhere but
  localhost, and why that list starts with authentication and not with a cap.

**Done when:** a run that would exceed the ceiling is refused before the first
question is asked, and a test proves it without spending anything.

---

# Topic 28 — Paraphrase retrieval

**Queue position 32.** Added in Session 24. **It carries the worst measured
number in this project and it is at the back of the queue, which is a decision
worth arguing with rather than a fact.**

**DONE, Phase 32. See D-107 and D-108.** Paraphrase recall@5 41.2% -> 70.6%
across 17 questions, golden 50.0% -> 62.5% and extended 25.0% -> 75.0%. **The
change was not one of the three techniques below.** HyDE was built and measured
and lost to switching the reranker off, which is what shipped. The table quoted
below is stale in two ways: it is 16 questions rather than 17, and its reading
of the reranker was backwards — the reranker was not failing to rescue these
questions, it was losing them.

**Why this phase exists**, quoted from run `2026-08-09T1022Z`:

```
suite      kind          n     r@5    r@20   cov@5    MRR
golden     paraphrase    8   50.0%  100.0%   25.0%   0.31
extended   paraphrase    8   25.0%   87.5%   12.5%   0.20
both       paraphrase   16   37.5%   93.8%   18.8%   0.25
```

**37.5% against golden easy's 100% and factual's 100%.** Ten of sixteen miss at
five. And the shape of the miss is the whole phase: **fifteen of sixteen are
found by rank 20**, and the ten misses sit at ranks 7, 7, 7, 8, 8, 10, 10, 16,
19 and never. The material is in the pool. The order is wrong, and it is wrong
by two or three places on most of them.

**The reranker has already had its shot at this and did not take it.** It is on
by default and it scores 20 candidates against the question, which is exactly
what a cross-encoder is for — a chunk that says the same thing in different
words is the case it exists to rescue. It is not rescuing them. **That is the
finding this phase starts from**, and it points at candidate generation rather
than at ordering, which is the opposite of what Phase 7's write-up concluded
from recall@20 being 100%.

`empires-let-go` is the one question in the whole 92 that is not found at
twenty, in any configuration, and it has been that way since Phase 15.

**What gets built** — one of these, chosen and defended, not all of them:

- **Multi-query expansion.** An LLM writes three to five rephrasings, each is
  retrieved, and the lists are fused with the RRF already in `search.py`. Cheap,
  composes with everything, adds a round trip to every question.
- **HyDE.** An LLM writes a fake answer to the question and *that* is embedded.
  Aimed squarely at the case here — a question worded unlike any document — and
  it puts a generated document into the retrieval path, which is a new class of
  thing to be wrong.
- **Step-back prompting.** Ask a broader question first, retrieve for both.
  Suited to the abstraction failures specifically: Phase 5 recorded that "what
  made ordinary people take part in killing their neighbours" returns generic
  sociology, and `killing-became-policy` still misses at rank 10.

**The trap this phase must avoid.** All three of these are query-side and all
three add an LLM call before retrieval, so **the eval's `search_ms` stops
meaning what it meant** and every latency figure back to Phase 7 becomes a
comparison between two different things. Record that before the run, not after.

**Concepts to be able to explain**

- Why recall@20 at 93.8% with recall@5 at 37.5% is an ordering problem, and why
  the reranker being on already makes that reading suspect.
- What a fake answer is doing in HyDE, and why embedding something untrue can
  find something true.
- Why paraphrase questions are the only kind here written deliberately unlike
  the source, and why that makes them the closest thing in this eval to a real
  user.

**Done when:** a before/after on paraphrase `recall@5` and `coverage@5`, both
suites reported separately, in `decisions.md` — and a statement of what happened
to `search_ms`.

---

# Topic 29 — The cleaner's blanks

**Queue position 33, and it is last for a reason that is not importance.**

**Why this phase exists**, found in Phase 23 by reading an answer next to its
chunk:

> `Second Polish Republic — Geography` reads *"The country's total area, after
> the annexation of Trans-Olza, was . It extended  from north to south and
> from east to west."* The answer said "388,634 square kilometers [5]" and cited
> that chunk. The figure is in no prose chunk in the corpus.

D-027's template allow-list drops `{{convert}}`, so every sentence in this
corpus that stated a measurement now ends in a hole. **A truncated sentence is a
hallucination surface**: it reads as an assertion, it gets cited as one, and its
content is whatever the model supplies. The answer above happens to be correct,
which is the worst possible outcome — nothing in any metric can catch it and
only opening the chunk shows it.

**One sighting, and it is in the queue anyway.** The usual rule is that one
sighting is not evidence, and it is overridden here because the mechanism is
understood rather than guessed: the cause is a named line in `clean.py`, the
population of affected sentences is countable without a model, and the failure
mode is silent fabrication rather than a bad number.

**What gets built**

- `{{convert}}` rendered rather than dropped — the value and one unit, not both
  unit systems, which would double every measurement in the corpus.
- **A count first, before any rebuild.** How many Silver sentences currently end
  in a hole, and how many chunks contain one. That number is the phase's real
  deliverable and it costs nothing.
- A sweep for the same shape from other dropped templates. `{{convert}}` was
  found by accident; the allow-list has other entries and no one has checked
  what their absence leaves behind.

**Why it is last, and why that might be wrong.** It rebuilds Silver, Gold and
the collection — **$0.26 and, far more expensive, every run on disk stops being
comparable to every run after it.** Seventeen runs and every published figure
back to Phase 7 sit on one corpus. Doing this late means fewer comparisons are
broken; doing it *early* would mean everything after it shares one corpus and
compares cleanly. **Both arguments are good and the second may be better.** If
this moves, it should move to the front of the remaining queue rather than one
place at a time.

**Concepts to be able to explain**

- Why a gap in a sentence is more dangerous than a missing sentence.
- What Bronze being immutable buys here, and why this costs a rebuild rather
  than a re-crawl — the same argument D-097 made and then did not need.
- Why "the answer was right" is not a defence, and what it would have taken to
  notice if it had been wrong.

**Done when:** the count of holed sentences is in `decisions.md` **before** any
rebuild, and afterwards a before/after showing the same question answered from a
chunk that contains its own figure.

---

## Elective pool

Enter only when your eval says this is where you are losing. Organized by
where in the pipeline it acts.

### Indexing

| Technique | Fixes | Cost |
|---|---|---|
| Multi-representation indexing — index a summary or generated questions, return the raw chunk | Query language never matches document language | Medium |
| Metadata enrichment — LLM-extracted entities, dates, topics at index time | Cannot filter on things the source did not label | Medium |
| RAPTOR — recursive cluster-and-summarize into a tree, index every level | "Summarize the whole corpus" questions no single chunk answers | High |
| Proposition indexing — decompose into atomic standalone facts | Chunks carrying several facts, only one relevant | High |
| Late chunking — embed the whole document, then pool token vectors per chunk | Same problem as Phase 12, at no LLM cost. Needs a model exposing token embeddings; OpenAI's does not | Medium; a second embedding vendor |
| Index-time near-duplicate detection | The duplicate problem at its source rather than patched at query time | Low |

### Query understanding

| Technique | Fixes | Cost |
|---|---|---|
| Multi-query expansion — 3-5 paraphrases, retrieve each, fuse | Single-phrasing brittleness | Low, adds latency. **Now a candidate inside queue 32, not a free-standing elective** |
| HyDE — LLM writes a fake answer, embed *that*, search with it | Short queries whose embedding resembles nothing | Low, adds a round trip. **Candidate inside queue 32** |
| Query decomposition — split multi-part questions | "Compare X and Y" where no chunk covers both | Medium |
| Step-back prompting — ask a broader question first, retrieve for both | Overly specific queries that miss the explaining passage | Low. **Candidate inside queue 32**, and the one aimed at the abstraction failures specifically |

### Retrieval

| Technique | Fixes | Cost |
|---|---|---|
| Matryoshka / truncated dimensions | Storage and search cost. You already have this via the `dimensions` param | Low |
| Learned sparse — SPLADE, BM42 | BM25's exact-match rigidity without losing term precision | Medium |
| Multi-vector / late interaction — ColBERT | The precision ceiling of single-vector search | High; storage grows a lot |
| Iterative retrieval — retrieve, reason, retrieve again | Multi-hop where hop 2 depends on hop 1's answer | High latency |
| Graph RAG — entity/relation graph, traversed | Multi-hop and global "what are the themes" questions | Very high build cost |
| Ensemble embeddings — two models, both searched, fused with RRF | Different models fail on different questions; purely additive | Low; doubles index storage |
| Cross-lingual retrieval — ask in German, retrieve English | European history asked in European languages | Medium; a multilingual embedding model |

### Post-retrieval

| Technique | Fixes | Cost |
|---|---|---|
| MMR — maximal marginal relevance | Top 5 results are five near-copies of one passage | Low. **Queue 26 is the cheap version of this and comes first**: a per-article cap is one line and needs no similarity matrix |
| Contextual compression — strip irrelevant sentences from surviving chunks | Wasted tokens, noise diluting the answer | Medium |
| Lost-in-the-middle reordering — strongest chunks first and last | Models demonstrably attend less to the middle of long context | Trivial |
| Adaptive `k` — pass 2 chunks or 15 depending on the score spread | A fixed `k` is wrong in both directions; Phase 7 already holds the score data | Low |

### Generation

| Technique | Fixes | Cost |
|---|---|---|
| Span-level citations — character offsets, not just document ids | "Cites the right doc" is unverifiable; "cites this sentence" is checkable | Medium |
| Structured output — force answer plus citations into a schema | Parsing citations out of prose is fragile | Low |
| CRAG — grade retrieval quality, fall back if poor | Silent failure when the corpus simply lacks the answer | Medium |
| Self-RAG — model decides whether to retrieve, critiques its own draft | Retrieving when unnecessary; ungrounded claims | Medium-high |
| Chain-of-verification — draft, generate checks, verify, revise | Plausible fabrications | High latency |
| Runtime groundedness gate — check every claim against its sources before returning | Phase 6's real defects: a claim losing a qualifier, a figure losing the country it applied to. Faithfulness as a guard, not only a metric | Medium; one extra call per answer |

### Production

| Concern | What it means |
|---|---|
| Semantic caching | Cache answers by query-embedding similarity, not exact string match |
| Incremental indexing | Detect changed documents, re-embed only those. Bronze already makes this possible |
| Index versioning | Blue-green reindex so a bad embedding-model swap cannot take the system down |
| Prompt injection from retrieved content | Your corpus is untrusted input the moment anyone else can write to it |
| Cost and latency budgets | Per-query ceilings, enforced, with alerts |

---

## The tempting ones to resist

**Graph RAG.** Genuinely impressive on multi-hop and global-summary questions,
and genuinely expensive to build and maintain. Most corpora do not need it.
Build it when your eval proves multi-hop is where you are losing — not because
it was on a conference slide.

**Agentic RAG loops.** Latency and cost compound fast and failures become very
hard to debug. A good reranker usually beats a mediocre agent, for a fraction
of the complexity.

**Fine-tuning the embedding model.** Real gains, but it needs labeled
query-document pairs you do not have. It comes after everything above, not
before — and Phase 10's eval data is where those labels would come from.

**Adding five techniques at once.** You will have no idea which one helped.
This is the failure mode the gate rule exists to prevent, and it will be
tempting precisely when you are most excited.

---

## Adding a phase

When your eval surfaces a failure this document does not cover, add a phase
using the same shape:

```markdown
# Phase N — <name>

**Why this phase exists.** <the observed failure, quoted from your eval>

**What gets built** <the change, and only this change>

**Concepts to be able to explain** <what you should know afterwards>

**Done when:** before/after number in decisions.md
```

The document grows from evidence, not from reading lists.
