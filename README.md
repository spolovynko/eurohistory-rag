# eurohistory-rag

A retrieval-augmented generation system over 20th- and 21st-century European
history, built from English Wikipedia. Ask it a question in plain language; it
finds the relevant passages and answers from them, with citations that link to
the exact article revision it read.

Built from scratch — no LangChain, no LlamaIndex — one measured phase at a time.

---

## Does it work?

106 hand-written questions with hand-written ground truth. Newest run,
[`2026-08-11T0635Z`](eval/runs/2026-08-11T0635Z):

| | |
|---|---|
| Right source in the top 5 (`recall@5`) | **85.9%** |
| Right source in the top 20 (`recall@20`) | **97.8%** |
| Answers with a broken or missing citation | **0** |
| Questions it correctly refused to answer | **11 of 106** |
| Cost per question | **$0.0013** |

Reproduce every one of those numbers, offline and free:

```bash
uv run eurohistory rescore eval/runs/2026-08-11T0635Z
```

**[Read the evidence →](docs/evidence.md)** — including the numbers that are
weak, the one question it has never been able to answer, and the four checks the
most recent change *failed*.

---

## What is unusual about this repository

Most of the value here is not the pipeline — it is the record of how each
decision was measured.

- **[`docs/decisions.md`](docs/decisions.md)** — every decision from D-001 to
  D-108, each with the reason it was made. From Phase 8 onward, every one
  states what a good, bad and *impossible* result would be **before the command
  runs**, then records what actually happened. Several are negative results.
- **A regression tool whose job is to fail.** `eurohistory gate` compares two
  saved runs and exits non-zero on any regression. The most recent change failed
  it on four checks and shipped anyway, with the reasoning written down.
- **31 evaluation runs kept on disk**, with full transcripts — every question,
  every chunk retrieved, every answer.

A worked example of what that discipline catches: Phase 32 set out to add a
well-known retrieval technique (HyDE). It was built, measured, and **lost** — to
switching an existing component off, which turned out to have been quietly
costing 29 points of recall on reworded questions since Phase 8. Both the
technique and the result are in [D-108](docs/decisions.md).

---

## Quick start

```bash
uv sync                 # install
cp .env.example .env    # add your OpenAI key
docker compose up -d    # Qdrant
uv run eurohistory index    # build the index (~$0.26, one time)
uv run uvicorn eurohistory_rag.api.main:app --reload
```

Then open `http://127.0.0.1:8000`.

**[Full operator guide →](docs/operating.md)** — prerequisites, what each stage
costs, the spend ceiling, every command, the switches that change answers.

---

## How it works

```
Wikipedia -> bronze/ -> silver/ -> gold/ -> Qdrant     (offline build)
question -> embed -> search -> thin -> prompt -> answer  (per query)
```

**[Architecture →](docs/architecture.md)** — the two paths, why only one layer
of the data is irreplaceable, what an embedding is actually doing, and where it
breaks.

---

## Development

```bash
uv run pytest           # 839 tests — no network, no Docker, no API key
uv run ruff check .
uv run mypy src tests   # strict
```

CI runs all of it on every push, plus a test that pins the scoring code to the
figures already published — so the metrics cannot quietly start reporting
something different about runs that were already measured.

---

## Documents

| File | Read it when |
|---|---|
| [`docs/evidence.md`](docs/evidence.md) | You want to know whether it works, and how to check |
| [`docs/operating.md`](docs/operating.md) | You need to run it |
| [`docs/architecture.md`](docs/architecture.md) | You want to know how it works |
| [`docs/decisions.md`](docs/decisions.md) | You want to know *why* something is the way it is |
| [`docs/tuning.md`](docs/tuning.md) | You are changing a number that affects answer quality |
| [`docs/roadmap.md`](docs/roadmap.md) | You want to know what is next and what was rejected |
