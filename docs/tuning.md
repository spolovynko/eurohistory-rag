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
| `OVERFETCH` | 4 | `retrieval/search.py` | D-047 | Multiplier on `k` when asking the store, so thinning has spares to draw from |
| `RERANK_TOP_N` | 20 | `retrieval/search.py` | D-072 | How many candidates the cross-encoder scores. Fixed rather than `k × OVERFETCH`, so the eval and the answer path rerank the same pool |
| `reranker_enabled` | `false` default, `true` in `.env` | `core/config.py` | D-069 | Whether reranking runs at all. The one knob here that lives in `.env`, because it is the on/off switch a before/after run needs to flip |
| `reranker_model` | `cross-encoder/ms-marco-MiniLM-L6-v2` | `core/config.py` | D-070, D-071 | Which cross-encoder scores the pool. **Probe any replacement by hand before trusting a run** — see D-071 |
| `RRF_K` | 60 | `retrieval/search.py` | D-076 | The "do not over-trust first place" dial in fusion. A chunk earns `1/(RRF_K + rank)` in each list. At 0, rank 1 is worth double rank 2; at 60 they are nearly equal, so agreement across both searches outweighs topping one |
| `hybrid_enabled` | `false` default | `core/config.py` | D-074 | Whether the BM25 keyword search runs and gets fused in. Lives in `.env` for the same reason as `reranker_enabled`: it is the switch a before/after run flips. **Needs an index built with sparse vectors** — turning it on against a pre-Phase-9 collection finds nothing |
| `SYSTEM_PROMPT` | `system_prompt.md` | `generation/system_prompt.md` | D-054 to D-057 | The standing rules the answering model works under. Not a number, but the single biggest lever on answer quality in this phase |
| `TEMPERATURE` | 0.0 | `generation/client.py` | D-052 | How much the model varies run to run. 0 so the same question gives the same answer, which is what makes Phase 7's before/after comparable |
| `judge_model` | `gpt-4.1-mini` | `core/config.py` | D-079 | Which model grades faithfulness. Changing it changes the measurement, not the system — and **re-run `judge-probe` after**, because a different judge is a different instrument. Defaults to the answering model, so the self-preference bias is present by default and stated rather than hidden |
| `SAMPLE_SEED` / `DEFAULT_COUNT` | 20261005 / 150 | `eval/synthetic.py` | D-078 | Which chunks become synthetic questions, and how many. Changing either regenerates the set and **invalidates every comparison against runs made with the old one** |
| `verify_enabled` | `false` | `core/config.py` | D-084 | Whether the groundedness gate runs — a second model call that checks each answer against its sources before returning it. **Measured and not shipped:** it fires on 5.6% of answers, and of seven revisions one was a real fix and one deleted a sourced fact. Costs 3.4x the latency and double the tokens |
| `verify_model` | `gpt-4.1-mini` | `core/config.py` | D-084 | Which model checks. Defaults to the answering model, so the writer proofreads itself. **Probe any replacement with `scratch_verify_check.py` before a paid run** — the first prompt caught 0 of 3 known defects and no test could see it |
| `VERIFY_PROMPT` | `verify_prompt.md` | `generation/verify_prompt.md` | D-084 | The checker's instructions. Its `# HOW TO CHECK` section is load-bearing: asking for a whole-answer impression caught nothing, asking claim by claim in a `<check>` block caught the Trianon reversal |
| `MAX_OUTPUT_TOKENS` | 800 | `generation/client.py` | D-084 | Shared between writing and checking. Three gate replies were cut off mid-check and fell back to the draft, which is safe but wasted the call. A checker that reasons before answering needs its own ceiling |

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
| `DEFAULT_K` / `MAX_PER_DOCUMENT` / `OVERFETCH` / `RERANK_TOP_N` / `RRF_K` | nothing | free, takes effect next query |
| `hybrid_enabled` | `index` **if the collection predates Phase 9** | free to flip; a rebuild is a few cents |
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
