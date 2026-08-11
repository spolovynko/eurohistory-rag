# Running it

What you need, what it costs, and the order things happen in.

---

## Prerequisites

| | |
|---|---|
| Python | 3.12+, managed by [`uv`](https://docs.astral.sh/uv/) |
| Docker | For Qdrant, the vector database |
| OpenAI API key | Embeddings and generation |
| Disk | ~2 GB for the corpus, the index and the reranker weights |

```bash
uv sync                 # create .venv and install from uv.lock
cp .env.example .env    # then put your key in it
docker compose up -d    # Qdrant on localhost:6333
```

**`uv sync` downloads PyTorch**, which is a few hundred megabytes, because the
optional reranker runs locally rather than as a paid API. It is switched off by
default (see below) but the dependency is not optional.

---

## What it costs

| Step | Cost | Notes |
|---|---|---|
| `curate`, `ingest`, `silver`, `chunk` | **$0.00** | Wikipedia's API is free; be polite with the user agent |
| `index` | **~$0.26** | Embeds 56,324 chunks once |
| A question on `/ask` | **~$0.0013** | About a tenth of a cent |
| A full evaluation run | **~$0.14** | 106 questions, end to end |
| `judge` over a saved run | **~$0.10** | More model calls than the run itself |

There is a **daily spend ceiling** enforced before any call is made, set by
`MAX_DAY_DOLLARS`, plus a per-run ceiling. A run that would exceed it is refused
before it starts rather than halfway through. The ledger lives in `data/spend/`,
and it is the one thing under `data/` that cannot be rebuilt.

---

## Building the corpus

These run in order. Only the last one costs money.

```bash
uv run eurohistory curate    # seeds.toml -> corpus/registry.csv  (then review it by hand)
uv run eurohistory ingest    # registry   -> data/bronze/   (resumable, safe to re-run)
uv run eurohistory silver    # bronze     -> data/silver/   (full rebuild)
uv run eurohistory chunk     # silver     -> data/gold/     (full rebuild)
uv run eurohistory index     # gold       -> Qdrant         (costs ~$0.26, needs Docker)
```

**Only `data/bronze/` is irreplaceable.** Silver, Gold and the Qdrant collection
are caches — delete and rebuild them freely. That is the point of the layout,
and it is what makes experimenting with chunking cheap.

`curate` produces a *draft* list of articles. It is meant to be read and edited
before `ingest` runs; the committed `corpus/registry.csv` is the reviewed
version.

---

## Serving it

```bash
uv run uvicorn eurohistory_rag.api.main:app --reload
```

| Route | What it is |
|---|---|
| `/` | The page — ask a question, see the answer with its sources |
| `/ask` | The answer endpoint, streaming |
| `/search` | Retrieval only, no generation, no cost |
| `/health` | Is the process up |
| `/ready` | Can it actually serve a search — checks Qdrant and the collection |
| `/runs` | Every evaluation run on disk, scored |
| `/eval/plan` | What a run would cost, and whether it could work |
| `/docs` | OpenAPI schema, generated from the handlers' type hints |

`/ready` is the one to point a load balancer at. `/health` only says the process
is alive, which it is even with the database down.

**One gotcha:** the CSS and JS are read once at import, and `--reload` only
watches Python files. Edit a stylesheet and you will keep being served the old
one until you restart.

---

## Evaluating it

```bash
uv run eurohistory evaluate            # 106 questions -> eval/runs/<id>/   (~$0.14)
uv run eurohistory rescore <run-dir>   # recompute metrics offline, free
uv run eurohistory gate <before> <after> --changed <field>   # regression check, free
uv run eurohistory sweep --baseline <run-dir>                # many retrieval settings, ~free
uv run eurohistory judge-probe                               # test the judge before trusting it
uv run eurohistory judge <run-dir>                           # faithfulness scoring (~$0.10)
uv run eurohistory trace <run-dir>                           # where a run's time went, free
```

**`judge-probe` before `judge`, always.** An unvalidated judge produces a number
nobody should act on.

`gate` requires you to name what you changed on purpose — `--changed reranker` —
and fails if the thing you named did not actually differ between the two runs.
That is how a run that measured nothing gets caught.

`sweep` is the cheap instrument: retrieval is deterministic, so a dozen
configurations cost one embedding per question instead of a dozen full runs. Its
first row is a control that must reproduce a run already on disk; if it does
not, nothing below it means anything and it says so.

---

## The switches that change answers

Full list with reasoning in [`tuning.md`](tuning.md). The three that matter:

| Setting | Default | Effect |
|---|---|---|
| `RERANKER_ENABLED` | `false` | A local cross-encoder reorders the top 20. **Turned off in Phase 32** — it cost paraphrased questions 29 points of recall@5. It still helps questions that name a specific year. |
| `HYBRID_ENABLED` | `false` | Adds BM25 keyword search, fused with the vector search. Needs an index built with sparse vectors. |
| `WARM_START` | `true` | Loads the reranker during startup instead of inside the first request. The only flag here that is on by default, because it cannot change an answer — only who waits. |

---

## Development

```bash
uv run pytest           # 839 tests, no network, no Docker, no key
uv run ruff check .     # lint
uv run ruff format .    # format
uv run mypy src tests   # types, strict
```

CI runs all four on every push. It deliberately does **not** run the evaluation:
that needs a populated database, a key and real money. What it runs instead is
`tests/eval/test_baseline_pinned.py`, which catches the failure the eval cannot
— the scoring code silently changing what it reports about runs already
published.
