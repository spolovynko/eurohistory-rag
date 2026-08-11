# How it works

Two paths through this system, and they share almost nothing. Understanding
that split is most of understanding the codebase.

- **The build path** runs offline, occasionally, and turns Wikipedia into a
  searchable index.
- **The query path** runs on every question, in milliseconds, and never touches
  the build code.

`api/` must never import `pipeline/`. The web process answers questions; it has
no business dragging the batch build stack in with it. Anything both sides need
lives in `retrieval/` or `core/`.

---

## The build path

```
seeds.toml  ->  registry.csv  ->  bronze/  ->  silver/  ->  gold/  ->  Qdrant
   themes       article list      raw wiki    cleaned     chunks     vectors
```

This is a **medallion layout**, and the reason for it is one rule: **only
`bronze/` is irreplaceable.** It holds the raw wikitext exactly as fetched, with
the revision id. Everything downstream is a cache that can be deleted and
rebuilt for free.

Plain: we keep the original photocopies in a drawer and never write on them.
Everything else — the tidied version, the cut-up version, the searchable version
— can be made again from the drawer. That is what makes it cheap to change our
minds about how to cut the text up, which we have done several times.

| Stage | What happens |
|---|---|
| `bronze/` | Raw wikitext, immutable, append-only, one Parquet file per batch |
| `silver/` | Templates and markup stripped, deduplicated, typed |
| `gold/` | Split into ~1,000-character chunks on paragraph boundaries, with overlap |
| Qdrant | Each chunk embedded to 1,536 dimensions, plus a sparse keyword vector |

Each chunk carries the **revision id** of the article it came from, so a
citation links to the exact version that was indexed rather than to whatever the
page says today. Wikipedia changes; a citation that cannot be checked is not a
citation.

---

## The query path

```
question -> [rewrite] -> embed -> vector search -> [fuse] -> [rerank] -> thin -> prompt -> answer
```

Square brackets are stages that are off or conditional. On the current
configuration the live path is: embed, search, thin, prompt, answer.

**`thin`** is the stage people do not expect. Chunks overlap, so neighbouring
chunks from the same section score almost identically and would otherwise fill
all five slots with one page. Thinning caps how many chunks any one section can
contribute. It only ever removes, never reorders.

**`rewrite`** runs only on follow-up questions in a conversation. "When did it
come down?" has no subject, so the vector built from it is a vector of nothing
in particular. A model call turns it back into a standalone question before
anything is embedded. It lifted follow-up recall@5 from 46.2% to 92.3%.

**`rerank`** is a local cross-encoder that rescores the top 20 against the
question. **It is currently off.** It was on from Phase 8 to Phase 32, when
measurement showed it was costing paraphrased questions 29 points of recall@5
while no longer helping the comparison questions it was kept for. See
[D-108](decisions.md).

---

## Why a vector search finds anything at all

An **embedding** turns a piece of text into a list of 1,536 numbers, positioned
so that texts about similar things end up near each other. Searching means
turning the question into the same kind of list and finding the chunks closest
to it.

Plain: imagine every paragraph in the encyclopedia placed somewhere in a very
large warehouse, arranged by subject rather than alphabetically. Ask a question,
work out where in the warehouse that question belongs, and look at what is on
the nearby shelves. Nothing is being *understood*; things about the same subject
are simply stored near each other.

**Where that breaks, measured here rather than assumed:**

- It scores *what a text is about*, not *what it asks*. "Why did the money
  become worthless" and "how was the hyperinflation ended" are near neighbours
  even though one asks the cause and the other the cure. This is why the
  paraphrased questions are the hardest suite.
- It is bad at numbers. "1916" and "1915" sit almost on top of each other,
  because a vector has no concept of a year. Discovered here by removing the
  reranker and watching the 1915 section outrank the 1916 one.

---

## Answering

The retrieved chunks are numbered and put in the prompt, and the model is
required to cite them by number. Three rules are enforced in code rather than
trusted to the prompt:

1. **A citation marker that does not correspond to a supplied source is an
   error**, counted in every run. It is currently 0.
2. **An answer with no citation at all is an error**, counted separately. Also
   0.
3. **"I don't know" is a valid answer** and is scored as a pass on the 14
   questions the corpus genuinely cannot answer.

The third is the one that is easy to skip and dangerous to skip. A system
graded only on the questions it can answer will learn to answer everything.

---

## Layout

```
src/eurohistory_rag/
├── api/          the web layer — imports retrieval/, never pipeline/
├── cli/          the command line — the pipeline's trigger
├── core/         startup concerns only: config, logging, spend ledger
├── eval/         the measurement — questions, runner, metrics, gate, sweep
├── generation/   prompt, model client, answer service — the /ask path
├── pipeline/     bronze/ silver/ gold/ index/ — the offline build
└── retrieval/    embedding, vector store, search — the query path
```

## Stack

| Concern | Tool |
|---|---|
| Python + deps | `uv` |
| Config | `pydantic-settings` |
| Data frames | `polars` |
| Storage | Parquet |
| Web API | `fastapi` + `uvicorn` |
| Wikitext parsing | `mwparserfromhell` |
| Embeddings | `openai` — `text-embedding-3-small`, 1536 dims |
| Generation | `openai` — `gpt-4.1-mini` |
| Vector store | Qdrant |
| CLI | `typer` |
| Lint / types / tests | `ruff`, `mypy --strict`, `pytest` |

**No LangChain and no LlamaIndex, deliberately.** They hide exactly the
mechanics this project exists to make visible. Every stage above is a function
you can read in one sitting.
