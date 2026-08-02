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

Eight numbers. Changing any of them changes what the system retrieves or
answers.

| Knob | Value | File | Decision | What it controls |
|---|---|---|---|---|
| `MIN_SEEDS` | 2 | `pipeline/bronze/curate.py` | D-016 | How many seed articles must link a title before it enters the registry. Lower = bigger, noisier corpus |
| `MIN_SECTION_CHARS` | 200 | `pipeline/silver/sections.py` | D-034 | Shortest section that becomes a Silver row. Below this it is usually leftover apparatus, not a claim |
| `CHUNK_SIZE` | 1200 | `pipeline/gold/chunk.py` | D-037 | Characters of body per chunk, prefix excluded. The single biggest lever on retrieval quality |
| `CHUNK_OVERLAP` | 150 | `pipeline/gold/chunk.py` | D-038 | Characters carried from the previous chunk, rounded up to whole sentences |
| `MIN_TAIL_CHARS` | 200 | `pipeline/gold/chunk.py` | D-040 | A final chunk shorter than this is merged backwards instead of standing alone |
| `DEFAULT_K` | 5 | `retrieval/search.py` | D-047 | How many results a search returns |
| `MAX_PER_DOCUMENT` | 2 | `retrieval/search.py` | D-047 | Most chunks allowed from any one section, so overlapping neighbours cannot fill the list |
| `OVERFETCH` | 4 | `retrieval/search.py` | D-047 | Multiplier on `k` when asking the store, so thinning has spares to draw from |

### How to change one

**The three chunking knobs** are exposed as CLI flags, so an experiment needs
no code edit:

```bash
uv run eurohistory chunk --size 800 --overlap 100
uv run eurohistory index
```

Re-chunking changes every `chunk_id`, so `index` must be re-run and it rebuilds
the collection whole. That is by design — see D-046.

**The three retrieval knobs** are constructor arguments with these constants as
defaults, so an experiment constructs the service differently:

```python
SearchService(embedder, store, k=10, max_per_document=1, overfetch=3)
```

That is how Phase 7's eval runner will sweep them: no editing, no env vars.

**`MIN_SEEDS` and `MIN_SECTION_CHARS`** have no flag. Changing either means
editing the constant and rebuilding from that layer down — `MIN_SEEDS` also
requires re-curating and re-ingesting, which is the only expensive one here.

### What a change costs

| Change | Rebuild needed | Rough cost |
|---|---|---|
| `MIN_SEEDS` | `curate` → `ingest` → `silver` → `chunk` → `index` | hours; a full Wikipedia fetch |
| `MIN_SECTION_CHARS` | `silver` → `chunk` → `index` | ~2 min + an embedding pass |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` / `MIN_TAIL_CHARS` | `chunk` → `index` | seconds + an embedding pass |
| `DEFAULT_K` / `MAX_PER_DOCUMENT` / `OVERFETCH` | nothing | free, takes effect next query |

The embedding pass over ~30,000 chunks is a few cents and a few minutes. Only
Bronze is expensive to rebuild, which is the whole point of the medallion
layout.

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
| `MAX_RETRIES` = 5 | `retrieval/embedding.py` | handed to the OpenAI SDK's own backoff |
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
