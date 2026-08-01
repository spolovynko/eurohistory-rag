# Phase 3 notes — Silver

Reference for the concepts Phase 3 requires. Written against the state of this
repo on 2026-08-01, with polars 1.43.1, mwparserfromhell 0.7.2.

Everything below is grounded in files that exist here, or in output that was
actually produced. Where a number is quoted, it was measured on this corpus.

---

## What Phase 3 built

| File | Purpose |
|---|---|
| `pipeline/wikitext.py` | shared with Bronze: is this link an article, what is it called |
| `pipeline/silver/clean.py` | the cleaning pipeline — markup in, prose out |
| `pipeline/silver/article.py` | the three article-level questions |
| `pipeline/silver/sections.py` | split at level-2 headings, decide what becomes a row |
| `pipeline/silver/store.py` | the 14-column schema and the write |
| `pipeline/silver/build.py` | read Bronze, dedup, transform, write |
| `cli/cli.py` | `eurohistory silver` |
| `tests/pipeline/silver/` | 79 tests, no I/O except `tmp_path` |

No dependencies added. `polars` and `mwparserfromhell` both arrived in Phase 2.

Result: **4,782 rows from 664 articles, 26.3 M characters of prose, 11 MB, 99
seconds to rebuild.** All four gates green.

---

## Part 1 — the problem Phase 3 exists to solve

Bronze holds raw wikitext, which is a markup language, not text. One sentence
as it sits in Bronze:

```
The [[Treaty of Versailles|treaty]] was signed{{sfn|Tucker|2005|p=429}} in 1919.
```

The same sentence as Silver stores it:

```
The treaty was signed in 1919.
```

Everything in this phase is a decision about which of those brackets survives.

**Why this is not a `strip()`.** `mwparserfromhell` will happily flatten the
whole article in one call, and the result is wrong in three different ways at
once — footnotes land mid-sentence, image sizes appear as prose, and the words
inside `{{lang|de|Reichstag}}` vanish. Each of those needed a separate rule,
and each rule is a decision recorded in `decisions.md`.

**Why it matters downstream.** Silver's only customer is a chunk that becomes a
vector and then gets pasted verbatim into a prompt. Junk in a chunk does three
things at once: it dilutes the embedding, it wastes prompt tokens, and it gives
the model text it may cite as if it were content. Once hybrid search arrives in
Phase 8, junk also becomes matchable — `"Smith 2010 4"` is three real tokens to
BM25.

---

## Part 2 — the order of operations

This is the part that is easy to get backwards, and everything else follows
from it.

```
one bronze row (raw wikitext, ~90,000 chars)
   │
   ├─ 1. read the article-level facts    article.py
   │     infobox, categories, is-this-junk
   │
   ├─ 2. cut into sections               sections.py
   │     level-2 headings; apparatus dropped by name
   │
   ├─ 3. clean each section              clean.py   (once per section)
   │     templates -> footnotes/tables -> links -> strip -> whitespace
   │
   └─ 4. assemble                        build.py
         article-level fields copied onto every section row
```

**Why step 1 comes first.** The cleaner deletes the evidence. An infobox is a
template, and the template rule deletes templates. A category is a link, and
the link rule deletes non-article links. Clean first and there is nothing left
to extract.

**Why step 3 runs per section, not per article.** Not for correctness — the
output would be identical. It is because a section is the unit being kept or
dropped, and the minimum-length rule is applied to cleaned text, so each
section has to be cleaned before it can be judged.

`pipeline/wikitext.py` is not a step. It answers one question — "is this link
pointing at a real article, and what is it called" — for `clean.py` here and
for `bronze/curate.py` over in Phase 2. Same knowledge, one place.

---

## Part 3 — the template rule, and what an allow-list costs

**The measurement that decided it:** 676 distinct template names in a 9% sample
of Bronze. A deny-list of citation templates is out of date the moment an
editor invents one.

Three options were on the table:

```python
s = "The {{lang|de|Reichstag}} met in {{convert|50|km}} of Berlin.{{sfn|Smith|2010|p=4}}"

strip_code(keep_template_params=True)  # "The de Reichstag met in 50 km of Berlin.Smith 2010 4"
strip_code()                           # "The  met in  of Berlin."
ours                                   # "The Reichstag met in 50 km of Berlin."
```

The middle one is the library default and it is why the plan calls `strip_code`
a blunt instrument. Ours is the middle one plus a named allow-list, put back
before the strip runs.

Two lists, because kept templates come in two shapes:

| | Shape | Example |
|---|---|---|
| `KEEP` | text at known positions | `lang` takes position 2 |
| `KEEP_ALL` | every positional parameter is content | `{{ubl\|France\|Britain}}` |

**One implementation detail that is load-bearing.** `rescue_templates` iterates
`reversed(code.filter_templates())` — innermost first. `filter_templates()`
yields an outer template before the ones nested inside it, and replacing the
outer one re-parses its text, which resurrects an inner `{{lang}}` as a fresh
node the loop has already passed. The first draft had this bug and produced
`" cordiale"` from `{{nowrap|{{lang|fr|Entente}} cordiale}}`. Nesting is the
normal case in wikitext, not an edge case.

**What the allow-list costs, and it was paid immediately.** The rule is silent:
a template nobody listed disappears leaving no trace of having existed. The
first version of `KEEP` deleted `{{start date and age|28 June 1919}}` and with
it the signing date of the Treaty of Versailles — plus 88 death dates, 87 birth
dates, and most `commander`/`combatant` infobox fields. None of that was
visible until an infobox extractor existed to notice the empty fields.

**The lesson worth carrying:** a silent rule needs a downstream consumer before
you can see what it broke. Reading the output is the only detector.

---

## Part 4 — footnotes and tables

`strip_code()` does **not** remove `<ref>` content. It keeps the text inside:

```
"Text.<ref>Smith, Europe, p. 4.</ref> More."   ->   "Text.Smith, Europe, p. 4. More."
```

Refs are **29% of this corpus**, so that is the same failure as
`keep_template_params`, at nine times the scale. They are removed explicitly,
with their contents, before the strip.

Tables are 3%, and flattening one gives:

```
"Year Event 1919 Versailles"
```

The numbers survive and the column headers that gave them meaning do not, which
is worse than dropping the table — the figures stay readable and stop being
true.

**A wrinkle worth knowing.** In `Treaty of Versailles` the ref rule removes only
162 characters from the Background section, while the final strip removes 2,056.
That is not the rule underperforming: this article cites with `{{sfn}}`
templates rather than `<ref>` tags, so its citations are deleted by the template
rule instead. Both routes end in the same place. Which rule does the work
depends on the article's citation style.

---

## Part 5 — wikilinks, and why hybrid search sharpens the choice

**The measurement:** 29,617 article links, of which 69% are plain `[[X]]` — the
target and the visible words are the same string. The decision only affects the
other 31%.

| | Result |
|---|---|
| display text | "…was elected **President** in 1925" |
| target | "…was elected **President of Germany (1919-1945)** in 1925" |
| both | every piped link doubles |

Display text won. The target carries a disambiguator that wrecks the sentence,
and every downstream technique consumes chunk text, so no later phase benefits
from the damage.

**The known cost:** `[[Treaty of Versailles|the treaty]]` becomes "the treaty".
That sentence is now unfindable by a keyword search for *Versailles*, even
though it is about Versailles.

**Why hybrid search cuts both ways here.** BM25 matches literal words, dense
retrieval matches meaning. So keeping parameters is *worse* under hybrid —
citation junk becomes matchable. But losing "Versailles" is *also* worse under
hybrid — dense retrieval can sometimes recover it from context, BM25 cannot.
The fix for the second is the `link_targets` column: the targets are kept out
of the prose, where Phase 8 can index them without an embedding ever seeing
them. Median 226 distinct targets per document.

**File links are a separate problem.** `strip_code` emits their parameters
verbatim:

```
[[File:Versailles.jpg|thumb|right|250px|The signing in 1919]]
   ->  "thumb|right|250px|The signing in 1919"
```

So they are deleted, captions included — the image is not in the corpus, so a
caption left behind describes something the reader cannot see.

---

## Part 6 — what one Silver row is

The decision was: one row per **level-2 section**, not one row per article.

```
Treaty of Versailles  (175,653 chars of wikitext)  ->  8 rows

30030:0  (lead)                      3,089 chars
30030:1  Background                  6,214
30030:2  Negotiations               11,227
30030:3  Treaty content and signing 12,580
30030:4  Reactions                  17,806
30030:5  Implementation              8,210
30030:6  Violations                 11,688
30030:7  Historical assessments     15,339
```

Three reasons, in order of weight:

1. **It is the natural chunk boundary.** A chunk spanning "Background" into
   "Terms of the treaty" is one vector for two topics and retrieves well for
   neither. Section rows make that boundary structural rather than something
   Phase 4 has to remember.
2. **It is the granularity a citation needs.** "Treaty of Versailles §
   Reparations" is checkable. The article is 87,000 characters of prose.
3. **Flat rows can be read by hand.** The phase's done-when requires reading
   ten documents; a nested list column defeats that.

The lead section is identified by an empty `heading`, so it needs no flag of
its own. `position` is the order among *surviving* sections, so it is
contiguous.

Level-3 headings stay inside their parent as plain lines. Splitting deeper is
Phase 4's job.

**Two filters decide what becomes a row.** By heading name — 19 apparatus names
including variants like "Notes and references", which matching is exact enough
to need spelled out. Then by length — under 200 characters of cleaned text.

The 200 was measured, not chosen. Below it:

```
 17  Nuremberg § Notes and references          "Notes\n\nReferences"
 31  Wilhelm II § Arms, orders and decorations "German honours\n\nForeign honours"
 33  Kansas City § Sister cities               "Kansas City has 15 sister cities:"
```

Above it, immediately:

```
235  Kingdom of Serbia § Culture   "The Kingdom of Serbia participated in the
                                    International Exhibition of Art of 1911..."
```

The junk below the line is all the same junk: sections whose entire content was
a table that got deleted, leaving the subheadings behind.

---

## Part 7 — the structured metadata

Two article-level extractions, both read before the article is cut up.

**Infoboxes.** 77% of articles have one, and there are **77 distinct types**
sharing almost no field names. So it is stored as a type plus a plain key-value
map rather than typed columns:

```
Treaty of Versailles  ->  type "treaty"
                          date_signed      = "28 June 1919"
                          location_signed  = "Hall of Mirrors in the Palace of
                                              Versailles, Versailles, France"
                          date_effective   = "10 January 1920"
```

Normalising "when did this start" across 77 types is a day of work justified by
no evidence — Phase 7 has not run, so no query has failed for want of a real
date column. Silver rebuilds in 99 seconds, so deferring costs nothing.

Field *values* are wikitext too, so they go through the same cleaning as the
prose. Presentational fields (`image`, `caption`, `coordinates`, `flag*`) are
dropped: they are the three commonest fields in the corpus and none is a fact
about the subject.

**Categories.** Median 11 per article, 6,585 distinct. These are the only
metadata in the corpus a human assigned on purpose:

```
Treaties concluded in 1919 · World War I treaties · Arms control treaties
Paris Peace Conference (1919-1920) · Peace treaties of Germany · June 1919
```

**No noise filter, and that is a measurement not an oversight.** Maintenance
categories like "Articles containing video clips" are added by *templates*, and
templates are never expanded here — so only hand-typed categories appear. Two
of 6,585 looked like maintenance. KISS vetoed the guard.

---

## Part 8 — deduplication, and why duplicate vectors matter

Bronze holds one row per `(page_id, theme)`. 772 rows, 664 articles:

```
in 1 theme    586
in 2 themes    60
in 3 themes    18
same page twice within one theme   12 rows
```

The last 12 are the known `_map_final_to_requested` limitation from Phase 2 —
two registry titles resolving to the same article. D-021 predicted both cases
and said Silver would handle them.

**Why this is a retrieval problem, not a tidiness problem.** If `Adolf Hitler`
survives as three rows, every section of it is embedded three times. A query
returns three identical chunks in its top 5, leaving two slots for everything
else. **Duplicate vectors quietly shrink `k`.**

So Silver keys on `(page_id, position)` and `theme` becomes `themes`, a list.
Nothing is lost — Qdrant filters a list field the same way it filters a scalar.
The cost is that anything grouping by theme must explode the list first.

---

## Part 9 — schema enforcement, and why Silver overwrites

The 14 columns are declared in `store.py` and passed to `pl.DataFrame(...,
schema=SILVER_SCHEMA)`, so dtypes are **declared, not inferred**. That is what
`schema enforcement` buys over a dict of lists: an empty build types identically
to a full one, and a column that should be `List(Utf8)` cannot silently become
`List(Null)` because the first batch happened to be empty.

```
doc_id  page_id  position  title  heading  text  themes  link_targets
categories  infobox_type  infobox  revision_id  revision_timestamp  license
```

`infobox_type` is the only nullable column — null for the 23% with no box. An
empty field list would not say the same thing.

`infobox` is `List(Struct{key, value})`. It is the part of the schema most
likely to break on a Parquet round trip, which is why there is a test for
exactly that.

**Silver overwrites; Bronze appends.** Bronze is append-only because
re-downloading costs a network round trip, so a crash mid-run must leave every
written file complete. A Silver rebuild costs 99 seconds of CPU, so there is
nothing to resume and nothing to protect — one file, written whole. That
asymmetry *is* the medallion idea: only Bronze is irreplaceable.

---

## Part 10 — what reading ten rows found

The phase's done-when says to read ten Silver documents by hand. It earned its
place.

**A bug no test would have caught.** `Thuringia` came out with

```
infobox_type = "settlement<!-- see template:infobox settlement... -->"
```

Editors write HTML comments inside the template name. Six articles affected;
78 distinct infobox types collapsed to 75 once stripped. Every summary query —
row counts, null counts, length distributions — was green throughout.

**Three things still open,** carried in `progress.md`:

1. **List-shaped sections survive both filters.** `Ian Kershaw § Works` is
   2,474 characters of book titles; `Oryol § International cooperation` is a
   twin-towns list; `Kiel mutiny § Films` is film credits. They clear 200
   characters and their headings are not apparatus, so they become rows holding
   no claim. Candidate fixes: more heading names, or a shape test — mostly
   short lines, few sentences.
2. **On-theme articles carry off-theme sections.** `Belgrade § Sport and
   recreation`, `Munich § Etymology`, `Oder § Navigation`. Phase 7 will say
   whether they actually hurt.
3. **Level-3 subheadings are bare lines.** A section starts `"Etymology\n\nMunich
   was a tiny 10th-century..."`. Fine at the top of a chunk, odd mid-chunk.
   Parked for Phase 4.

---

## Part 11 — two refactors, and why they happened

**`data_ingestion/` became `pipeline/`.** Bronze, Silver, Gold and the indexer
are all stages of one offline pipeline triggered by the CLI; "ingestion" stopped
describing chunking and would have been actively wrong for embedding. The
`Embedder` was deliberately reserved for `core/`, because the API needs it at
query time — if it lived in `pipeline/`, answering a search would mean importing
the batch pipeline, and that dependency direction is backwards.

**Nine Silver modules became four.** One file per rule made each decision
reviewable while it was being made. Once the decisions were made, the split was
costing more than it bought: three 20-line rules in one 150-line file are easier
to hold in your head than four files. KISS applied on purpose, and `CLAUDE.md`
says it outranks the rest.

**One pattern note.** The cleaning chain looks like chain-of-responsibility and
is not. In that pattern, handlers opt out and one of them stops the chain. Here
every step always runs, in a fixed order, and none can stop the others — that is
**pipes and filters**, and the Python-native form of it is calling the functions
in order inside one function. Wrapping them in handler classes with `set_next()`
would add three classes and change no behaviour.

---

## Concepts checklist

The plan's Phase 3 list, with where each is answered:

| Concept | Where |
|---|---|
| What each cleaning step removes, with an example | Parts 3-5 |
| Why the prose ratio is ~40-50%, and what the other half was | Parts 3-4: refs 29%, tables 3%, templates the rest |
| The dedup key, and why exact-content hashing is not enough | Part 8 |
| What was decided about wikilinks, and why | Part 5 |
| Why Silver is safe to delete | Part 9 |
| What schema enforcement buys over a dict | Part 9 |

---

## Numbers, in one place

| | |
|---|---|
| Bronze in | 772 rows, 664 articles, 59.6 M chars wikitext |
| Silver out | 4,782 rows, 664 articles, 26.3 M chars prose, 11 MB |
| Prose ratio | 44% of wikitext survives |
| Build time | 99 seconds |
| Refs / tables | 29% / 3% of the corpus |
| Distinct template names (9% sample) | 676 |
| Infobox coverage | 77% of articles, 77 distinct types |
| Categories | median 11 per article, 6,585 distinct |
| Link targets | median 226 per document |
| Row length | min 200, median 2,789, p75 6,407, max 96,737 |
| Sections dropped by the 200-char rule | 2.4% |
| Tests | 79 new, 180 total |

**For Phase 4:** 26.3 M characters at 1,000-char chunks is ~26,000 chunks, just
over the plan's 25,000 ceiling. The 96,737-character row alone would be ~97
chunks.
