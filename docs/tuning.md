# Tuning knobs

Every number in this project that changes **answer quality** when you change
it, and where it lives.

This file exists because the numbers are deliberately *not* centralised. Each
one sits next to the code it governs, with the comment explaining why it is
that value — `CHUNK_SIZE = 1200` means nothing without D-037's argument beside
it. A central `tuning.py` would strand the number away from its reason, and
would become the file everything imports and nobody owns.

So the code stays local and this file is the index. When you want to change
something, look it up here and edit it in its own module.

---

## Where a value belongs

Three tiers. Getting the tier right is most of the decision.

| Tier | Goes in | Why | Example |
|---|---|---|---|
| Differs **per machine** | `.env` / `Settings` | the deployment decides, not the design | `QDRANT_URL`, `EMBEDDING_MODEL` |
| Differs **per request** | function / CLI / query parameter | a caller legitimately varies it call by call | `k`, `--size`, `--batch-size` |
| Differs **per experiment** | a module constant, used as a default | it is a design decision with a written reason | `CHUNK_SIZE`, `MAX_PER_DOCUMENT` |

**Nothing on this page belongs in `.env`.** A value in `.env` is invisible: it
does not appear in a diff, it is not in the repo, and two machines can silently
disagree about what the corpus is. These are corpus-design decisions, not
machine settings. See D-037 and the Phase 4 session note.

---

## The knobs

Fifteen entries. Changing any of them changes what the system retrieves or
answers — or, for the last two, what the measurement of it says.

| Knob | Value | File | Decision | What it controls |
|---|---|---|---|---|
| `[[theme]]` blocks | 9 themes, 35 seeds | `corpus/seeds.toml` | D-086 | **What the corpus is about.** The largest knob in this table and the one with no default: three themes covered 1914-1945, nine cover 1914-2024. Adding one is `curate` → hand trim → `ingest` → `silver` → `chunk` → `index` |
| `MIN_SEEDS` | 2 | `pipeline/bronze/curate.py` | D-016 | How many seed articles must link a title before it enters the registry. Lower = bigger, noisier corpus. **Assumes the seeds are topically close** — six disparate seeds returned 62 candidates against 232-372 for tighter themes (D-086) |
| `MIN_SECTION_CHARS` | 200 | `pipeline/silver/sections.py` | D-034 | Shortest section that becomes a Silver row. Below this it is usually leftover apparatus, not a claim |
| `CHUNK_SIZE` | 1200 | `pipeline/gold/chunk.py` | D-037 | Characters of body per chunk, prefix excluded. The single biggest lever on retrieval quality |
| `CHUNK_OVERLAP` | 150 | `pipeline/gold/chunk.py` | D-038 | Characters carried from the previous chunk, rounded up to whole sentences |
| `MIN_TAIL_CHARS` | 200 | `pipeline/gold/chunk.py` | D-040 | A final chunk shorter than this is merged backwards instead of standing alone |
| `DEFAULT_K` | 5 | `retrieval/search.py` | D-047 | How many results a search returns |
| `MAX_PER_DOCUMENT` | 2 | `retrieval/search.py` | D-047 | Most chunks allowed from any one section, so overlapping neighbours cannot fill the list |
| `max_per_article` | unset (no cap) | `core/config.py` | D-082, D-100 | Most chunks allowed from any one **article**, across all its sections. Measured twice and shipped off both times: it buys distinct articles at 5 and costs coverage@5 at every value. Setting it to 2 is the only arm that fixes `versailles-vs-trianon`, at the price of ten other questions |
| `OVERFETCH` | 4 | `retrieval/search.py` | D-047 | Multiplier on `k` when asking the store, so thinning has spares to draw from |
| `RERANK_TOP_N` | 20 | `retrieval/search.py` | D-072 | How many candidates the cross-encoder scores. Fixed rather than `k × OVERFETCH`, so the eval and the answer path rerank the same pool |
| `reranker_enabled` | `false` default, `true` in `.env` | `core/config.py` | D-069 | Whether reranking runs at all. The one knob here that lives in `.env`, because it is the on/off switch a before/after run needs to flip |
| `reranker_model` | `cross-encoder/ms-marco-MiniLM-L6-v2` | `core/config.py` | D-070, D-071 | Which cross-encoder scores the pool. **Probe any replacement by hand before trusting a run** — see D-071 |
| `warm_start` | `true` default, `false` in the tests | `core/config.py` | D-099 | Whether the reranker is read into memory during startup instead of inside the first request. **The only flag in this file that is on by default**, because it cannot change an answer — the same model gives the same scores whenever it was loaded, so there is no comparison a forgotten flag could contaminate. Turning it off restores the 6.5 s first question. The test suite switches it off, or 653 offline tests would read 88 MB off disk |
| `RRF_K` | 60 | `retrieval/search.py` | D-076 | The "do not over-trust first place" dial in fusion. A chunk earns `1/(RRF_K + rank)` in each list. At 0, rank 1 is worth double rank 2; at 60 they are nearly equal, so agreement across both searches outweighs topping one |
| `temporal_enabled` | `false` default | `core/config.py` | D-096 | Whether the year-overlap arm runs and gets fused in. **Needs payloads carrying `year_start` / `year_end`** — run `eurohistory index --payload-only` after a Gold rebuild, which is free. Off after the D-096 verdict: measured no recall@5 gain on the suite it was built for and cost recall@20 elsewhere |
| `ERAS` | 10 named periods | `retrieval/temporal.py` | D-096 | Which years "the interwar years", "the Cold War", "the early Cold War" and the rest mean. Every row is a judgement somebody could argue with; the Cold War's start date has a literature of its own. Only consulted when no year or decade is stated |
| `_DECADE_PARTS` | early 0-3, mid 4-6, late 6-9 | `retrieval/temporal.py` | D-096 | Which slice of a decade "early", "mid" and "late" mean. Early and late are four years and overlap the middle, which is the permissive direction |
| `_DIRECTIONAL` | 12 words | `retrieval/temporal.py` | D-096 | Words that make a date a reference point rather than a period — "after 1918" is not the year 1918. A question containing one resolves to no period at all unless it states an explicit range or decade. 43 of 78 evaluation questions take this path |
| `HEADING` | `"Infobox"` | `pipeline/gold/infobox.py` | D-097 | What the infobox chunk calls itself, and so what a reader sees as the source name of a fact taken from a box. Every article with a box gets one chunk per `CHUNK_SIZE` of fields — 1,421 chunks over 988 articles |
| `SKIP_FIELDS` | 16 prefixes | `pipeline/silver/article.py` | D-031, D-097 | Infobox fields dropped as presentational — images, captions, map pins. Written in Phase 3 when the box was read only for its type; **it now decides what is retrievable**, so a fact behind one of these prefixes cannot be found |
| `hybrid_enabled` | `false` default | `core/config.py` | D-074 | Whether the BM25 keyword search runs and gets fused in. Lives in `.env` for the same reason as `reranker_enabled`: it is the switch a before/after run flips. **Needs an index built with sparse vectors** — turning it on against a pre-Phase-9 collection finds nothing |
| `SYSTEM_PROMPT` | `system_prompt.md` | `generation/system_prompt.md` | D-054 to D-057 | The standing rules the answering model works under. Not a number, but the single biggest lever on answer quality in this phase |
| `TEMPERATURE` | 0.0 | `generation/client.py` | D-052 | How much the model varies run to run. 0 so the same question gives the same answer, which is what makes Phase 7's before/after comparable |
| `judge_model` | `gpt-4.1-mini` | `core/config.py` | D-079 | Which model grades faithfulness. Changing it changes the measurement, not the system — and **re-run `judge-probe` after**, because a different judge is a different instrument. Defaults to the answering model, so the self-preference bias is present by default and stated rather than hidden |
| `SAMPLE_SEED` / `DEFAULT_COUNT` | 20261005 / 150 | `eval/synthetic.py` | D-078 | Which chunks become synthetic questions, and how many. Changing either regenerates the set and **invalidates every comparison against runs made with the old one** |
| `verify_enabled` | `false` | `core/config.py` | D-084 | Whether the groundedness gate runs — a second model call that checks each answer against its sources before returning it. **Measured and not shipped:** it fires on 5.6% of answers, and of seven revisions one was a real fix and one deleted a sourced fact. Costs 3.4x the latency and double the tokens |
| `verify_model` | `gpt-4.1-mini` | `core/config.py` | D-084 | Which model checks. Defaults to the answering model, so the writer proofreads itself. **Probe any replacement with `scratch_verify_check.py` before a paid run** — the first prompt caught 0 of 3 known defects and no test could see it |
| `VERIFY_PROMPT` | `verify_prompt.md` | `generation/verify_prompt.md` | D-084 | The checker's instructions. Its `# HOW TO CHECK` section is load-bearing: asking for a whole-answer impression caught nothing, asking claim by claim in a `<check>` block caught the Trianon reversal |
| `MAX_OUTPUT_TOKENS` | 800 | `generation/client.py` | D-084 | Shared between writing and checking. Three gate replies were cut off mid-check and fell back to the draft, which is safe but wasted the call. A checker that reasons before answering needs its own ceiling |
| `conversation_enabled` | `true` | `core/config.py` | D-098 | Whether a follow-up is rewritten into a standalone question before it is embedded. **The one flag here that defaults on**, because a question carrying no history never reaches the rewriter -- measured at 0 of 92 single-turn questions changing a chunk. Set it false to reproduce the "before" half of D-098 |
| `rewrite_model` | `gpt-4.1-mini` | `core/config.py` | D-098 | Which model rewrites the follow-up. A second model call before every multi-turn search: median `search_ms` on the conversation suite went 467 -> 1,247 ms, and stayed at 468 ms on every single-turn question |
| `REWRITE_PROMPT` | `rewrite_prompt.md` | `generation/rewrite_prompt.md` | D-098 | The rewriter's instructions. Its load-bearing rule is the *negative* one -- leave a question that already stands alone exactly as written. It was disobeyed on 2 of 3 controls, benignly both times, and that is the thing to watch when editing this file |
| `HISTORY_TURNS` | 2 | `generation/rewrite.py` | D-098 | How many previous exchanges the rewriter sees. Older turns are dropped rather than summarised: a summary is a second call whose mistakes are invisible, a dropped turn fails in the open as an unresolved pronoun |
| `ANSWER_CHARS` | 600 | `generation/rewrite.py` | D-098 | How much of each previous answer the rewriter is shown. An answer states its subject early, and a follow-up points at a name |
| `MAX_QUESTION_CHARS` | 300 | `generation/rewrite.py` | D-098 | Longer than this and the rewrite is rejected and the typed question used instead. The failure it guards is the model answering rather than rewriting; the longest question in `questions.toml` is 118 characters |
| `SSE_TYPE` | `text/event-stream` | `api/main.py` | D-095 | The `Accept` value that makes `POST /ask` hand the answer over as it is written instead of in one blob. Not a number and not really tunable -- listed because it is the whole of the streaming switch, and because a client that never sends it gets the pre-Phase-21 behaviour unchanged |

### How to change one

**The three chunking knobs** are exposed as CLI flags, so an experiment needs
no code edit:

```bash
uv run eurohistory chunk --size 800 --overlap 100
uv run eurohistory index
```

Re-chunking changes every `chunk_id`, so `index` must be re-run and it rebuilds
the collection whole. That is by design — see D-046.

**The four retrieval knobs** are constructor arguments with these constants as
defaults, so an experiment constructs the service differently:

```python
SearchService(embedder, store, k=10, max_per_document=1, overfetch=3, rerank_top_n=50)
```

That is how Phase 7's eval runner will sweep them: no editing, no env vars.

**The two reranker settings are the exception on this page** — they live in
`.env`, which everything above says these values should not. The reason is that
`reranker_enabled` is the switch a before/after run has to flip between two
otherwise identical runs, and `reranker_model` names a downloaded artefact that
genuinely does differ per machine. `RunMeta.reranker` records both into every
run directory, which is what stops an invisible `.env` value from producing an
unattributable result — and it caught exactly that on its first use.

**`MIN_SEEDS` and `MIN_SECTION_CHARS`** have no flag. Changing either means
editing the constant and rebuilding from that layer down — `MIN_SEEDS` also
requires re-curating and re-ingesting, which is the only expensive one here.

### What a change costs

**One embedding pass is $0.26 and 12 minutes** at the nine-theme corpus (54,903
chunks, 52.1 M characters). It was $0.14 at three themes; budget it as scaling
with the corpus, not as a fixed cost.

| Change | Rebuild needed | Rough cost |
|---|---|---|
| A `[[theme]]` block | `curate` → hand trim → `ingest` → `silver` → `chunk` → `index` | ~20 min of reading to trim the candidates, then ~20 min of machine time and one embedding pass. The fetch itself is free and took 22 s for 618 articles |
| `MIN_SEEDS` | `curate` → `ingest` → `silver` → `chunk` → `index` | hours; a full Wikipedia fetch |
| `MIN_SECTION_CHARS` | `silver` → `chunk` → `index` | ~5 min + an embedding pass |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` / `MIN_TAIL_CHARS` | `chunk` → `index` | seconds + an embedding pass |
| `DEFAULT_K` / `MAX_PER_DOCUMENT` / `max_per_article` / `OVERFETCH` / `RERANK_TOP_N` / `RRF_K` | nothing | free, takes effect next query |
| `hybrid_enabled` | `index` **if the collection predates Phase 9** | free to flip; a rebuild is a few cents |
| `temporal_enabled` | `chunk` then `index --payload-only` **if the payloads predate Phase 22** | free to flip; the payload refresh is free too — no vector is re-embedded |
| `HEADING`, `SKIP_FIELDS` | `chunk` then `index --resume` | ~$0.008 — resume skips every batch already stored and pays only for the infobox chunks. A full `index` would be $0.26 **and** would move every cosine score in the fourth decimal, which is exactly what a before/after cannot afford |
| `ERAS` / `_DECADE_PARTS` / `_DIRECTIONAL` | nothing | free, takes effect next query |
| `reranker_enabled` / `reranker_model` | nothing | free; a new model downloads once, then ~1 s per query |
| `judge_model` | nothing; re-run `judge` on the affected runs | a few cents per run, and a `judge-probe` first |
| `SAMPLE_SEED` / `DEFAULT_COUNT` | `synthesize`, then `evaluate --questions` | a few cents to write, a few more to run |

The embedding pass over ~30,000 chunks is a few cents and a few minutes. Only
Bronze is expensive to rebuild, which is the whole point of the medallion
layout.

---

## The gate's thresholds — knobs with a rule attached

`eval/gate.py` holds the numbers that decide whether a run counts as a
regression. They are knobs in the sense that they are constants you can edit,
and **not** knobs in the sense that matters: every one of them was measured, and
widening one because a build went red is how a gate stops meaning anything.

| Constant | Value | Where it came from |
|---|---|---|
| `TOP_SCORE_FLOOR` | 0.001 | 35 of 1,200 chunk slots moved their cosine score by up to 0.0006 across three identical runs; the embedding API is not bit-exact (D-088) |
| `LATENCY_NOISE_MS` | 900 | the p50 spread inside a thirty-question suite over three identical runs. **Reported, never gated** — it is mostly the model vendor's load (D-089 verdict) |
| `UNSUPPORTED_FLOOR` | 4 | D-088. Reported only |
| `FAITHFULNESS_FLOOR` | 0.007 | D-088. Reported only |
| `FULLY_FAITHFUL_FLOOR` | 2 | D-088. Reported only |
| `CLAIMS_FLOOR` | 35 | D-088. Reported only |
| `COMPARABILITY_FIELDS` | 10 fields of `meta.json` | anything that changes what a number means. Adding a field to `RunMeta` that affects results means adding it here too |

**Changing any of them costs nothing to run and invalidates the comparison it
was measured for.** A floor is only meaningful against the question set, prompt,
answering model and judge it was measured on — re-measure before editing, the
way Phase 16 re-measured D-085's floor for the sixty-question set.

---

## The run button's numbers — Phase 20

Four constants sit behind the one control in this system that spends money.
None of them changes what an evaluation measures; all four change what it costs
to press by accident.

| Constant | File | What changing it costs |
|---|---|---|
| `LOOPBACK` | `api/main.py` | **the whole access control.** There is no authentication anywhere in this system, so widening this list makes `$0.08` a click available to anything that can reach the port. Narrow is the only safe direction |
| `MIN_PREDICTION` = 10 | `api/static/experiment.js`, mirrored by `StartRequest`'s `min_length` | how short a prediction may be. Both ends must move together — the page's copy only decides when the button lights up, and the server's is the one that refuses |
| `POLL_MS` = 2000 | `api/static/experiment.js` | how often the page asks what the run is doing. Free; a hundred and twenty status reads over four minutes is nothing. Lower it and the bar is smoother, raise it and a finished run sits unnoticed for longer |
| `PRICES`, `FALLBACK_TOKENS` | `eval/cost.py` | the accuracy of the number shown before the spend. A stale price quotes the wrong figure with full confidence — quoted $0.08 against $0.0803 actual on the run that proved it (D-094) |

`PRICES` is the one that goes stale on its own, because OpenAI moves prices and
nothing here notices. `test_every_selectable_model_has_a_price` catches a model
added without one; nothing catches a price that simply became wrong.

---

## Not knobs — leave these alone

These are constants too, but they are **not** yours to tune. They encode a
limit imposed from outside, or a performance choice that does not affect what
comes back.

| Constant | File | Why it is fixed |
|---|---|---|
| `MAX_TITLES_PER_REQUEST` = 50 | `pipeline/bronze/wikipedia.py` | Wikipedia's documented cap |
| `RETRY_STATUS_CODES` | `pipeline/bronze/wikipedia.py` | which HTTP failures are worth retrying |
| `API_URL` | `pipeline/bronze/wikipedia.py` | the MediaWiki endpoint |
| `LICENSE` = `CC BY-SA 4.0` | `pipeline/bronze/store.py` | Wikipedia's licence, not a choice |
| `MAX_TEXTS_PER_REQUEST` = 256 | `retrieval/embedding.py` | sits inside OpenAI's input and token caps |
| `MAX_RETRIES` = 5 | `retrieval/embedding.py`, `generation/client.py` | handed to the OpenAI SDK's own backoff |
| `MAX_OUTPUT_TOKENS` = 800 | `generation/client.py` | a ceiling, not a target. The prompt asks for six sentences, so an answer near this limit means the style rules were ignored |
| `CITATION` regex | `generation/service.py` | must match the marker format the prompt asks for. Change both or neither |
| `DEFAULT_BATCH_SIZE` = 200 | `pipeline/index/build.py` | speed vs cost-of-a-failed-batch; changes nothing about results |
| `NAMESPACE` | `retrieval/vectorstore.py` | **never change it** — every stored point id derives from it, so a new namespace orphans the whole collection |
| `KEEP`, `DROP_TAGS`, `DROP_HEADINGS`, `SKIP_FIELDS` | `pipeline/silver/` | cleaning rules, not numbers. Each has its own decision entry |
| `_`-prefixed regexes and constants | throughout | module-private implementation detail |

The `_` prefix is the general signal: a leading underscore means the value is
internal to its module and nothing outside should read or change it.

---

## Adding a knob

When a new number appears and you are unsure:

1. **Does it differ per machine?** → `Settings` and `.env.example`.
2. **Would a caller vary it call by call?** → a parameter with a default.
3. **Is it a design decision you would have to defend?** → a module constant
   with a comment giving the reason, a `decisions.md` entry, and a row in the
   table above.
4. **None of the above?** → an implementation detail. Prefix it with `_` and
   leave it where it is. It does not belong on this page.


---

## Tracing has no knob, and that is the decision

Phase 28 added per-stage timing to `retrieval/search.py` and
`generation/service.py`. It is **always on** and there is no setting for it,
which is why it does not appear in the table above.

The argument for a switch is that instrumentation costs something. Measured: it
costs eight spans of two `time.perf_counter()` readings, on the order of a
microsecond against a four-second query, and `search_ms` moved 472.9 -> 487.0 ms
between runs — network variance on one embedding call, an order of magnitude
larger than anything the spans could contribute.

The argument against a switch is stronger and it is Phase 8's: **a flag that
can be off is a flag that can be off during the measurement.** An instrument
nobody can accidentally disable is worth more than a microsecond. D-101.


---

## Prompt caching has no knob either, and the prompt's length is the knob

There is nothing to switch on. OpenAI caches any shared prompt prefix
automatically on `gpt-4o` and newer, and `PRICES` in `eval/cost.py` now carries
the cached rate — $0.10 per million against $0.40 on `gpt-4.1-mini`. What decides
whether this project ever gets that discount is not a setting at all. It is **how
long `system_prompt.md` is.**

**Measured in Phase 29, four times over: the shared prefix must exceed ~2,048
tokens before anything caches.** `system_prompt.md` is ~1,600, so 105 of 106
answering calls in a full eval cached exactly nothing, and the run's cached share
was 0.9%. A padded prefix of ~2,100 tokens cached 1,920 on its second call. Grants
arrive in 128-token blocks, floored inside the shared prefix, which is why a hit
is 1,920 rather than a round 2,100.

**What this means for anyone editing the prompt.** Adding ~450 tokens to
`system_prompt.md` would cross the threshold and start the discount, worth
**$0.0004 per question** — four hundredths of a cent, against a prompt change that
can move an answer. D-103 says no. But the direction matters the other way too:
**a future prompt that grows past ~2,048 tokens for its own reasons gets the
discount for free**, and the `spend:` line on every run summary is where that
would show up.

**The one rule that is not negotiable:** the static part of the prompt stays
first. `messages.py` sends the system message, then the sources, then the
question, and a cache can only ever reuse a *prefix* — so anything variable moved
above the instructions would take the cacheable run down to zero. It has been in
the right order since Phase 6 and Phase 29 deliberately changed nothing about it.

---

## The refusal test is a closed list, and that is the decision

Phase 27 replaced `metrics.REFUSAL` — one string — with `REFUSAL_OPENERS`, three
phrases read only in the answer's **first sentence**. It is not a setting and it
does not belong in the table above: it is a definition, and changing it changes
what every published refusal figure in `decisions.md` means.

**Change it only together with `system_prompt.md`.** The list is the prompt's
own wording. Rule 3 says a refusal opens "Not in the sources"; rule 2 says a
partial answer *ends* with "The sources do not cover". The metric reads position
because the prompt writes position, and editing one without the other silently
decouples them.

**The list is closed on purpose.** A wider regex would quietly absorb wordings
nobody has read, and the whole failure this phase fixed was a metric nobody had
checked against a real answer. Instead, `tests/eval/test_refusal.py` runs a
deliberately wider hand-written net over every run on disk and fails when it
finds a first-sentence refusal the list misses. **Adding a phrase is therefore a
build failure first and an edit second, which is the right order.** D-102.

The knob that does not exist for the same reason: there is no threshold, no
tolerance and no "probably a refusal" score. A refusal either opens by declining
or it does not.

---

## The two cost ceilings — Phase 30

Both are **per-machine, in `.env`**, and that is the one placement decision this
phase made. A ceiling that varies per request would be set by the caller, and a
limit the caller chooses is not a limit. A module constant would be wrong for
the opposite reason: a laptop and a server want different numbers and neither is
a design decision.

| Knob | Default | What it does |
|---|---|---|
| `MAX_RUN_DOLLARS` | `0.50` | Refuses one evaluation whose **quote** exceeds it, before the run directory exists. |
| `MAX_DAY_DOLLARS` | `1.00` | Refuses the **next model call** once today's recorded spend reaches it. |

**Zero or less means no limit**, so a machine that wants none says so in `.env`
rather than by editing code.

### What the defaults are calibrated against

`$0.50` is about three and a half runs of the current 106 questions at the
measured `$0.1364`. Checked against the real quote: 106 questions pass at
`$0.1364`, 300 pass at `$0.3860`, **500 are refused at `$0.6434`**. A ceiling
that fires during ordinary work gets raised until it means nothing, so the
ordinary thing has to pass comfortably and a question set that has quietly
tripled has to fail.

`$1.00` is about seven and a half such runs. Measured by replaying the
`2026-08-10T1413Z` token counts call by call: **it stops after 779 calls at
`$1.0010`, an overshoot of exactly one call.**

### The day ceiling can stop a run halfway, and that is deliberate

It is checked before every call, not once before a run. Replayed, run 8 is
stopped at its 37th question. A run killed that way **writes no
`records.jsonl`**, exactly like a cancelled one — so it never appears as a run
and nothing half-measured gets compared against a baseline. Its `prediction.txt`
stays on disk, which is the same trace a cancelled run leaves.

The alternative — check once, then let a started run finish — was rejected
because it makes the daily ceiling advisory: one run that begins under the limit
could end arbitrarily far over it.

### Where the day's total lives, and the one weakness

`data/spend/YYYY-MM-DD.jsonl`, one line per call, appended and never rewritten.
UTC, so the day a ceiling covers is the day the run directories are named after.

**This is the first thing under `data/` that cannot be rebuilt from Bronze.**
Silver, Gold and the Qdrant collection are caches; a record of money already
spent is not. Deleting `data/spend/` starts the day over, and nothing detects
that. It stays gitignored because what one machine spent is not a fact about
this project. The honest summary: the ledger stops an accident, not a person
who wants to spend more.

**Second weakness, written down rather than discovered.** One process. Two
uvicorn workers get two ledgers over one file; the appends still land, so the
total stays right, but the read-then-refuse decision is no longer indivisible.
Same limitation `api/jobs.py` already documents for `EvalJob`.

### What this does not do

It is not authentication. There is still none anywhere in this system, and a cap
is not a substitute for one — `LOOPBACK` in `api/main.py` is what keeps a run
from being started by anyone but this machine, and it is an origin check, not an
identity. A ceiling limits the damage of a loop; it does nothing about who is
looping.
