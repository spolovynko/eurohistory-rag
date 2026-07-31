# Phase 2 notes — Bronze

Reference for the concepts Phase 2 requires. Written against the state of this
repo on 2026-07-31, with httpx 0.28.1, polars 1.43.1, mwparserfromhell 0.7.2,
typer 0.27.0, pydantic 2.13.4.

Everything below is grounded in files that exist here, or in output that was
actually produced. Where a number is quoted, it was measured.

---

## What Phase 2 built

| File | Purpose |
|---|---|
| `corpus/seeds.toml` | 13 hand-picked survey articles, 3 themes |
| `corpus/registry.csv` | 772 curated candidate titles, generated then reviewed |
| `data_ingestion/registry.py` | reads both corpus files, validates them |
| `data_ingestion/wikipedia.py` | the MediaWiki client: fetch, parse, retry |
| `data_ingestion/curate.py` | wikilink extraction and the >=2-seed rule |
| `data_ingestion/bronze.py` | the Bronze schema, Parquet write, resume keys |
| `data_ingestion/ingest.py` | the fetch loop |
| `cli/cli.py` | `eurohistory curate` and `eurohistory ingest` |
| `tests/data_ingestion/` | 93 tests, no network |

Dependencies added: `httpx` (dev → runtime), `typer`, `mwparserfromhell`,
`polars`, `tzdata`.

Result: 772 rows, 664 unique articles, 59.6 M characters of wikitext, 25 MB on
disk. All four gates green.

---

## Part 1 — why ingestion is two commands

`curate` and `ingest` are separate programs with separate lifecycles.

```
seeds.toml       13 titles      hand-written       input to curate
     │
     │  curate: fetch each seed, extract its body wikilinks,
     │          keep titles linked by 2+ seeds in the same theme
     ▼
registry.csv    772 titles      generated, then    input to ingest
                                trimmed by hand
     │
     │  ingest: fetch wikitext for every title, 50 at a time
     ▼
data/bronze/
```

**`ingest` never calls `curate` and never reads `seeds.toml`.** That is the
whole point. If ingestion started by traversing Wikipedia, "what is in my
corpus" would be a question you could only answer by re-running a network call
against a wiki that had changed since. Freezing the list into a committed CSV
makes the corpus diffable, reviewable, and reproducible — the same reasoning as
committing `uv.lock`.

### Why seeds rather than categories

Measured, not assumed. The first ten members of `Category:Cold War` include
`Abo Elementary School` and `Bas 60`, a Swedish airbase designation. Four of ten
are junk.

A wikilink in an article's body is an editorial judgment that this topic is
relevant to that one. There are millions of those judgments already made. Seeds
turn 800 decisions into 13.

**One hop only.** `Treaty of Rome` links to `Colosseum`; recursing would reach
`Roman Empire` and then ancient history, which is the category-noise problem
arriving by a different route.

### What the >=2 rule actually did

Theme 1, four seeds:

```
World War I                   689 links
Aftermath of World War I      578 links
Treaty of Versailles          440 links
Paris Peace Conference        324 links

unique titles across seeds   1689
linked by 2+ seeds            249
linked by 3+ seeds             73
```

Survivors at count 4: `League of Nations`, `Treaty of Trianon`, `Fourteen
Points`, `Central Powers`, `Armistice of 11 November 1918`, `Austria-Hungary`.

Dropped at count 1: `1,000,000,000`, `1918 flu pandemic`, `1918 United States
Senate elections`.

**No `List of…`, `Outline of…` or disambiguation pages survived** — the
frequency filter removed them without needing a rule about them.

What it did *not* remove: `Shandong`, `German New Guinea`, `The New York Times`,
all at count 4. WWI was global and the themes are European, so geography is the
noise the rule cannot see. That is what the hand review is for.

---

## Part 2 — the MediaWiki API

### The request

```
GET https://en.wikipedia.org/w/api.php
    ?action=query          the read module, as opposed to edit/login/parse
    &prop=revisions        give me revision data for each page
    &rvslots=main          the article body; MediaWiki 1.32 made a revision
                           hold several content slots
    &rvprop=content|ids|timestamp
    &titles=A|B|C          pipe-separated, up to 50
    &redirects=1           follow redirects rather than returning the stub
    &format=json
    &formatversion=2       `pages` as a list, real booleans
```

**A descriptive `User-Agent` with a contact address is mandatory** under
Wikimedia policy. `WikipediaClient.__init__` rejects an empty one rather than
defaulting, because a default would appear to work while getting throttled.

### The response, and the three shapes in it

Real output, `titles=treaty_of_rome|Great War|Nonexistent Article Zzqq`:

```json
{
  "batchcomplete": true,
  "query": {
    "normalized": [{"from": "treaty_of_rome", "to": "Treaty of rome"}],
    "redirects":  [{"from": "Great War", "to": "World War I"},
                   {"from": "Treaty of rome", "to": "Treaty of Rome"}],
    "pages": [
      {"ns": 0, "title": "Nonexistent Article Zzqq", "missing": true},
      {"pageid": 78006, "ns": 0, "title": "Treaty of Rome",
       "revisions": [{"revid": 1311520265, "parentid": 1302008621,
                      "timestamp": "2025-09-15T14:58:25Z",
                      "slots": {"main": {"contentmodel": "wikitext",
                                         "content": "{{Short description|..."}}}]},
      {"pageid": 4764461, "ns": 0, "title": "World War I", "revisions": [...]}
    ]
  }
}
```

Four things this settles:

1. **The content is five levels down**, at
   `query.pages[i].revisions[0].slots.main.content`, and every level can be
   absent.
2. **A missing page has no `pageid` and no `revisions` key at all** — not an
   empty list, the key is simply not there. That is why the wire models carry
   `Field(default_factory=list)`.
3. **Titles are rewritten twice, by two different mechanisms.** Normalisation
   fixed the underscore and capitalised only the *first* letter, giving
   `Treaty of rome`; a redirect then fixed `rome` → `Rome`.

   ```
   treaty_of_rome ──normalized──▶ Treaty of rome ──redirects──▶ Treaty of Rome
   Great War      ─────────────── redirects ──────────────────▶ World War I
   ```

4. **The pages come back in the API's order, not yours.** Requested Treaty of
   Rome, Great War, Nonexistent; received Nonexistent, Treaty of Rome, World War
   I. Zipping the request against the response positionally would attribute the
   wrong wikitext to the wrong registry entry.

Point 3 and point 4 together are why `_map_final_to_requested` exists: replay
both rename maps for each requested title, build a dict pointing from the final
title back to yours. The `seen` set in its loop is cycle protection — redirect
loops exist on the wiki and would otherwise hang an 800-article run.

### Why two layers of types

```
JSON  ──validate──▶  _WireResponse / _Query / _Page / _WireRevision / _Slot
                              │
                              │  flatten and rename
                              ▼
                     Revision  (a plain frozen dataclass)
```

The `_`-prefixed models are a transcription of Wikimedia's format —
`revid`, `pageid`, `slots`. They exist so an unexpected shape becomes a
`ValidationError` naming the field, rather than a `KeyError` forty lines later.
**The API's vocabulary stops at this module's edge**: rename `revid` upstream
and one line changes here, nothing downstream notices.

`Revision` is a `@dataclass`, not a `BaseModel`, because validating twice pays
for the same check twice — it is built from data checked three lines earlier.

### Strict about what you produce, lenient about what you accept

Same library, opposite settings, and the deciding question is always **who owns
the format**:

| | Setting | Why |
|---|---|---|
| `seeds.toml`, `registry.csv`, `.env` | `extra="forbid"` | your files, so an unknown key is your typo |
| the API response | `extra="ignore"` (the default) | Wikimedia's format, and they add fields without asking |

The real response carries `batchcomplete`, `ns`, `parentid`, `contentmodel`,
`contentformat` — none of which are modelled. Forbidding them would break the
client the day Wikimedia ships a feature.

### Retries: three outcomes, not two

`raise_for_status()` treats every failure identically. This does not:

| What happened | Response | Why |
|---|---|---|
| 429, 500, 502, 503, 504 | sleep, retry | busy or throttling; it passes |
| dropped connection, DNS, timeout | sleep, retry | the network, not you |
| 400, 403, 404 | **raise immediately** | the request is wrong; retrying reaches the same answer |

Backoff is exponential — 1, 2, 4, 8 seconds. If the server is returning 503
because it is overloaded, a fixed interval is part of the problem.

`Retry-After` overrides the local backoff when present, because the server knows
its own rate-limit window and you are guessing. Verified against a mock
transport:

```
200 first try                    slept=[]
429, 429, then 200               slept=[1.0, 2.0]
429 + Retry-After: 7             slept=[7.0]
503 x5, retries exhausted        WikipediaError, slept=[1.0, 2.0, 4.0, 8.0]
404, not retried                 WikipediaError, slept=[]
dropped conn, max_retries=2      WikipediaError, slept=[1.0, 2.0]
```

**What retries do not fix:** a killed process. That is resumability, and it is
solved by writing to disk as you go — see Part 4.

---

## Part 3 — what wikitext actually is

One Bronze row, `Treaty of Rome`, 19,146 characters. Counted:

| | in 19,146 chars |
|---|---|
| `{{template}}` openings | 40 |
| `[[wikilink]]` openings | 112 |
| `<ref>` tags | 23 |
| `==` section headings | 5 |
| `[[Category:...]]` | 11 |

And this is a *small* article — `World War I` is 213,527 characters, eleven
times larger.

Every Phase 3 decision is visible in the first thirty lines:

```
{{Short description|1957 founding treaty of the European Economic Community}}
{{more citations needed|date = March 2013}}          ← maintenance, zero content
{{Use dmy dates|date=May 2018}}
{{Infobox Treaty                                     ← STRUCTURED DATA, extract
| date_signed         = 25 March 1957
| location_signed     = [[Capitoline Hill]] in [[Rome]], [[Italy]]
| date_effective      = 1 January 1958
}}
{{Politics of the European Union}}                   ← navbox transclusion

The '''Treaty of Rome''' ... signed by [[Belgium]],
[[French Fourth Republic|France]], ...               ← PIPED LINK: display
                                                        "France", target
                                                        "French Fourth Republic"
```

and further down:

```
==Signing===                                         ← malformed: 2 on the left,
                                                        3 on the right. Live on
                                                        Wikipedia right now.
[[File:Traité CEE signatures.jpg|thumb|The signature page on the original
 Treaty of Rome]]                                    ← the caption is real prose
...blank pages.<ref>{{cite web|url=https://www.bbc.co.uk/...}}</ref>
                                                     ← 23 of these, mid-sentence
{| class="wikitable"                                 ← a table of signatories
! Signatories !! For </tr>
```

The malformed heading is why `mwparserfromhell` exists rather than a regex:
wikitext has no clean grammar and real articles are inconsistent.

Strip all of the above and roughly 40–50% survives as prose. That is where the
other half goes.

---

## Part 4 — the Bronze layer

### The schema

| column | type | answers |
|---|---|---|
| `page_id` | Int64 | which article — **the primary key** |
| `title` | Utf8 | what Wikipedia calls it now |
| `requested_title` | Utf8 | what the registry asked for |
| `theme` | Utf8 | which theme brought it in |
| `revision_id` | Int64 | **which version** — the reproducibility pin |
| `revision_timestamp` | Datetime UTC | how old is the article |
| `wikitext` | Utf8 | the payload |
| `fetched_at` | Datetime UTC | how stale is my copy |
| `license` | Utf8 | `"CC BY-SA 4.0"`, constant |

**Why `page_id` and not `title`.** Pages get renamed; ids never change and are
never reused. A corpus keyed on title silently forks the day an editor moves an
article.

**Why `revision_id` matters.** It is the version pin. Observed in the data:
`World War I` was last edited at 07:14 UTC and fetched at 08:57 — the copy was
already 1.7 hours old at the moment of writing. Without the revision id,
"I ingested World War I" is not a reproducible statement.

**Why both timestamps.** `revision_timestamp` is Wikipedia's; `fetched_at` is
ours. Different questions, and a refresh cycle needs both.

**Why `license` is a constant.** The action API does not return it per page, but
CC BY-SA requires attribution. Recorded rather than assumed.

### Why Parquet, not JSONL

Measured: 403 KB of wikitext wrote to 144 KB of Parquet — roughly **2.8×**
compression, same data.

The bigger win is columnar layout. `ingested_keys()` reads only `theme` and
`requested_title`:

```python
pl.scan_parquet(root / "**" / "*.parquet").select("theme", "requested_title")
```

The wikitext never leaves disk. That is what makes the resume check nearly free
across 772 rows averaging ~77 KB each.

JSONL is the defensible alternative — easier to inspect with `head` — and it
costs the columnar read plus roughly triple the disk.

### Partitioning, and one file per batch

```
data/bronze/
└── ingest_date=2026-07-31/
    ├── part-4916cda3faba.parquet
    ├── part-92ad78c96b1b.parquet
    └── ... 18 more
```

`ingest_date=` is the Hive convention: the directory name encodes a column, and
readers can skip whole directories without opening files. It answers "what did
this run produce", which is what a refresh cycle needs.

**A new file per batch is what makes "append-only" true rather than
aspirational.** Nothing already written is ever reopened, so a crash mid-run
leaves every completed file intact and readable.

Theme was rejected as the partition key: it is already a column, and Silver
filters on it cheaply.

### Idempotency

```python
done = bronze.ingested_keys(root)                        # (theme, requested_title)
todo = [e for e in entries if (e.theme, e.title) not in done]
```

Keyed on `requested_title`, not `title`, because the registry holds
`Great War` and Bronze holds `World War I` — the comparison must match the
registry's spelling.

Verified across three real runs:

```
run 1   767 written                    (interrupted before finishing)
run 2     5 written, 767 skipped       resumed exactly where it stopped
run 3     0 written, 772 skipped       no new files created
```

One consequence worth knowing: a title Wikipedia has no page for is retried on
every run, because it never reached Bronze and so never enters the skip set.

---

## Part 5 — testing without a network

93 tests in `tests/data_ingestion/`, none of which touch the internet.

**`httpx.MockTransport`** replaces the entire transport layer with a Python
function returning canned responses. That is how a 503 gets tested — Wikipedia
will not produce one on request.

```python
def handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(429, headers={"Retry-After": "7"})

WikipediaClient("test/1.0", transport=httpx.MockTransport(handler))
```

**`Protocol` for the seam**, not an abstract base class:

```python
class RevisionSource(Protocol):
    def fetch_batch(self, titles: Sequence[str]) -> FetchResult: ...
```

`WikipediaClient` satisfies it with no inheritance and no registration — mypy
checks the *shape*. `curate` and `ingest` are typed against the Protocol, so a
test passes a ten-line fake. This is dependency inversion in its Python form,
and interface segregation too: neither caller needs `close()` or `__enter__`, so
the Protocol does not mention them.

**`monkeypatch.setattr(time, "sleep", delays.append)`** turns the backoff into
an assertion. `assert no_sleep == [1.0, 2.0, 4.0]` proves the doubling without
waiting seven seconds.

---

## Part 6 — sizing, and what it means for Phase 4

Measured on the real corpus:

```
772 rows, 664 unique articles
59.6 M characters of wikitext
prose at 45%: 26.8 M characters

   600 chars/chunk  →  44,700 chunks
   800             →  33,500
  1000             →  26,800
  1500             →  17,900
```

The plan's target is 10,000–25,000 chunks. **Three themes already clear the
floor comfortably**, which reverses the plan's Phase 4 instruction to expand to
8–12 themes before Phase 5. Chunk size is now a lever against having *too many*
chunks, not too few.

`docs/plan.md` says "measure after Phase 3 rather than trusting either number" —
this is that measurement arriving one phase early, and it says the corpus is
already the right size.

---

## Part 7 — things worth remembering

**`tomllib.load` needs binary mode.** TOML mandates UTF-8, so the library
decodes the bytes itself rather than trusting the locale encoding. Text mode
raises `TypeError`. On Windows the locale encoding is cp1252, which would mangle
any accented title.

**`[[theme]]` with double brackets is TOML's array of tables.** Each block
appends to a list; order is preserved. Single brackets would make the second
block a duplicate-key error.

**`csv` needs `newline=""`.** Without it, Windows writes a blank line between
every row.

**Windows has no timezone database.** `zoneinfo` cannot resolve `"UTC"`, so
polars panics converting a `Datetime("us", "UTC")` row back to Python. `tzdata`
is a pure-data package that supplies it. This was found by the plan's own
done-when — "load one row back and print its raw wikitext" — and by nothing
else: every aggregate query worked fine.

**Typer collapses a single-command app.** With exactly one `@app.command()`,
`eurohistory curate` reads `curate` as a stray argument. An `@app.callback()`
forces group mode regardless of the command count.

**`itertools.batched` is stdlib in 3.12.** No helper needed.

**`frozenset` for module constants, `set` for things you build up.** Immutable
means a caller cannot mutate a shared constant, and it is hashable.

**Two `Counter` habits.** `most_common()` returns pairs sorted by count, and
dicts preserve insertion order — so a comprehension over it stays sorted.
`slugs.count(s)` inside a comprehension is O(n²), which is irrelevant at 12
themes and would not be at 10,000.
