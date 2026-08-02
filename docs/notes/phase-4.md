# Phase 4 notes — Gold / chunking

Reference for the concepts Phase 4 requires. Written against the state of this
repo on 2026-08-02, with polars 1.43.1.

Everything below is grounded in files that exist here, or in output that was
actually produced. Where a number is quoted, it was measured on this corpus.

---

## What Phase 4 built

| File | Purpose |
|---|---|
| `pipeline/gold/store.py` | the 11-column schema, the `Chunk` type, the write |
| `pipeline/gold/chunk.py` | the sentence splitter, the boundary ladder, `chunk_document()` |
| `pipeline/gold/build.py` | read Silver, chunk every row, write Gold |
| `cli/cli.py` | `eurohistory chunk`, with `--size` and `--overlap` |
| `tests/pipeline/gold/` | 35 tests, no I/O except `tmp_path` |

No dependencies added. `polars` arrived in Phase 2, and everything in
`chunk.py` is the standard library.

Result: **30,362 chunks from 4,782 documents, 9.7 MB, 1.6 seconds to
rebuild.** Chunk length min 82, median 991, max 1,590.

Decisions recorded: **D-036 to D-042**.

---

## Part 1 — why chunk at all

The plan asks for both reasons, because they are genuinely different and only
one of them is the interesting one.

### Reason one: the input limit

An embedding model takes a bounded amount of text. `text-embedding-3-small`
accepts 8,191 tokens, roughly 32,000 characters. Silver's largest row is
96,737 characters. Feed it whole and everything past the cut is silently
dropped and can never be retrieved.

This reason is real but it is not the one that matters here. Most Silver rows
are far under the limit — median 2,789 characters — so if the input limit were
the only problem, chunking would only be needed for the tail.

### Reason two: dilution

An embedding is one fixed-size summary of whatever you feed it. 1,536 numbers,
no matter whether the input was one sentence or one book.

Feed it 6,000 characters covering five topics and you get the average of five
topics: a vector that sits vaguely near all of them and precisely near none.
Retrieval works by *which vector is closest to the question*, so a vector that
is an average is a vector that loses to a focused one every time.

That is why a section that fits comfortably inside the input limit still gets
chunked. The limit says "you must"; dilution says "you should have anyway".

### The one-sentence version

**A chunk is a piece of text small enough to be about one thing.** Every
decision in this phase is an answer to "how small, and where am I allowed to
cut?"

---

## Part 2 — the boundary ladder

**Decision D-036.**

The question is: what is the smallest unit you refuse to cut through?

| Boundary | What it breaks |
|---|---|
| characters | mid-word. `"the Marshall Pl"` / `"an was announced"` |
| words | mid-sentence. `"...Stalin refused to"` / `"attend, and the"` |
| sentences | nothing in the prose, but needs a splitter, and abbreviations break naive ones |
| paragraphs | nothing — except that some paragraphs are bigger than any chunk |

These are not alternatives. They are rungs on a ladder, and the rule is:
**prefer the biggest boundary, fall back only when forced.**

> Fill a chunk with whole paragraphs. If one paragraph alone is too big, split
> it at sentence ends. If one sentence is still too big, cut at a word.

### Why the top rung is free

Silver's text is already paragraph-separated by `\n\n`. A paragraph break is a
boundary the author placed deliberately, so cutting there costs nothing.

Measured on this corpus: **47,844 paragraphs.**

| | chars |
|---|---|
| p25 | 250 |
| median | 496 |
| p75 | 770 |
| p90 | 1,070 |
| p99 | 1,834 |
| max | 10,941 |

### Why a fallback is mandatory, not optional

The largest paragraph is 10,941 characters. No chunk size worth having is that
big, so "never cut inside a paragraph" is a rule that cannot always be kept.
The only open question is what happens when it breaks.

### Why sentences rather than words

At a 1,000-character chunk, **12.4% of paragraphs are oversized** — 5,936 of
them. With a word fallback, all 5,936 get cut mid-sentence. With a sentence
fallback, they are cut cleanly and only a freak 1,000-character sentence falls
through to words.

5,936 ragged chunks is worth twenty lines of code to avoid.

### The sentence splitter, and why it is a regex

`split_sentences()` in `chunk.py`. Proper sentence segmentation needs a model —
`nltk`, `spacy`, `pysbd` — which is a new dependency, a download, and real
weight. This runs on 12% of paragraphs and a mistake costs one slightly ragged
chunk. KISS decided it.

The regex cuts on `.`, `!` or `?` followed by whitespace and something that
could start a sentence. That is wrong for abbreviations, so there is a list of
the ones history prose actually uses (`u.s`, `st`, `no`, `vol`, `gen`, ...).

The shape is worth noting: the regex **over-splits on purpose**, and a second
pass glues back any fragment whose predecessor ended on an abbreviation.

```python
for fragment in _BOUNDARY.split(text):
    if sentences and _ends_in_abbreviation(sentences[-1]):
        sentences[-1] = f"{sentences[-1]} {fragment}"
    else:
        sentences.append(fragment)
```

Expressing "do not split after these words" inside the regex itself is possible
and unreadable. Split-then-repair is the simpler shape.

**Known failure mode:** an unlisted abbreviation, or an initial like
`Ernest R. May`, splits wrongly. Rare, and survivable.

### One grouping function, three rungs

`_pack(pieces, size, joiner)` is used at every rung: words into sentence-sized
runs, sentences into paragraph-sized runs, paragraphs into chunks. Only the
joiner changes.

Writing the greedy loop three times would be three places to fix the same
off-by-one. That is DRY in its real sense — one piece of knowledge, one place —
rather than "these three loops look alike".

Sentences are rejoined with `" "` and paragraphs with `"\n\n"`, deliberately.
If an oversized paragraph is exploded into sentences and rejoined with blank
lines, the chunk comes out as a stack of one-sentence paragraphs: visibly wrong
text.

---

## Part 3 — size, and the token question

**Decision D-037: 1,200 characters of body.**

Measured on the full Silver table, greedy paragraph packing, no overlap:

| size | chunks | median chunk |
|---|---|---|
| 600 | 55,564 | 498 |
| 800 | 42,325 | 664 |
| 1,000 | 34,734 | 807 |
| 1,200 | 29,565 | 937 |
| 1,500 | 23,935 | 1,158 |
| 2,000 | 18,018 | 1,567 |

### The trade-off

- **Smaller** — each vector is about one thing, so retrieval is precise. But a
  chunk may not hold enough to answer: you retrieve the sentence that mentions
  the Marshall Plan without the sentence saying what it did.
- **Larger** — each chunk is self-contained and reads better in the prompt. But
  the vector is an average of more topics, which is the dilution problem
  chunking exists to solve, creeping back in.

1,200 was chosen because it sits where paragraphs actually live in this corpus.
The median chunk lands at 937 characters — two or three whole paragraphs, one
coherent stretch of argument.

### Tokens: where they matter and where they do not

Rule of thumb for English: **~4 characters per token.** So 1,200 characters is
roughly 300 tokens.

| Constraint | Limit | Our number | Binding? |
|---|---|---|---|
| embedding input | 8,191 tokens | ~300 | no, by a factor of 27 |
| generation prompt at k=5 | model context, tens of thousands | ~1,500 | no |

Neither is binding at this size, which is worth knowing precisely because
people assume chunk size is set by the embedding limit. It is not. It is set by
the dilution argument. The token count only starts to matter when `k` grows —
at k=20 the same chunks cost ~6,000 tokens of prompt per question, and that is
both latency and money.

### The gate, and why its two ends are different

The plan requires 10,000–25,000 chunks. Those are not the same kind of limit.

- **The floor is real.** Under 10,000, retrieval looks artificially good
  because there is nothing to confuse it with, and Phase 7 finds nothing to
  fix.
- **The ceiling is soft.** It is about cost and patience. Embedding 30,000
  chunks is a few cents and a few minutes.

1,200 overshoots the ceiling and clears the floor three times over. That is the
right way round.

### An objection worth recording

*"If the top k chunks all get concatenated into one prompt anyway, why not use
small chunks and let the model reassemble the context?"*

It is a good argument and it is half right. Retrieval precision is the thing
that cannot be fixed later; missing context can often be recovered by raising
`k`. Two limits:

1. **Adjacent chunks compete for the same slots.** Split a section into eight
   small chunks and five of them are about roughly the same thing, scoring
   alike. The top-5 comes back as five neighbours from one paragraph — no
   breadth.
2. **Combining only works if both pieces are retrieved.** If the question's
   wording matches chunk A but the answer sits in chunk B, and B alone does not
   look like the question, B never arrives.

The proper fix exists and is deliberately parked: **parent-document
retrieval** — embed small chunks for precision, return the larger surrounding
text to the model. Phases 11+, because it needs Phase 7 evidence that this
corpus actually has the problem.

---

## Part 4 — overlap

**Decision D-038: 150 characters, rounded to whole sentences.**

### What it is for

Chunk boundaries are arbitrary with respect to meaning. A claim can straddle
one:

```
chunk N   ...the conference collapsed in June 1947.
chunk N+1 Molotov walked out over the conditions attached.
```

Neither chunk alone answers *why did Molotov walk out*. Overlap repeats the
tail of each chunk at the head of the next, so a straddling claim lands whole
in at least one of them.

### What it costs — the same cost as D-035

Silver deduplicates on `page_id` because duplicate vectors quietly shrink `k`:
if the same text is embedded twice, both copies score alike and a top-5 comes
back as three views of one passage.

Overlap deliberately manufactures near-duplicates. Too much of it and the `k`
slots fill with repeats instead of distinct evidence. It also costs storage and
embedding calls in proportion.

### Why 150

Median sentence in this corpus is **130 characters**, so 150 is about one
sentence — the smallest useful amount.

It is small because paragraph boundaries are already meaningful cuts. Overlap
mostly exists to repair *bad* boundaries, and only 12% of this corpus gets a
boundary the author did not place. Zero overlap would have been defensible;
150 is cheap insurance on exactly that 12%.

### Two details in the implementation

**Whole sentences, taken from the end while they fit.** A chunk that ends on
one very long sentence carries nothing forward. That is fine — a sentence that
long is already self-contained.

**Taken from the previous *body*, not its finished text.**

```python
_overlap_text(bodies[position - 1], overlap) if position else ""
```

If overlap were read from the previous chunk's assembled text, the carried
sentences would ride forward again into the chunk after that, and the same
sentences would appear three times across the corpus. `bodies[position - 1]` is
the body before its own carried text was prepended, which stops the cascade.
There is a test named for exactly this.

Measured: **25,539 of 30,362 chunks carry overlap.** The rest are first chunks.

---

## Part 5 — what goes in the chunk's text

**Decision D-039.**

First, a distinction that decides everything else:

- **text** — what is sent to the embedding model and becomes the vector. This
  is what retrieval matches on.
- **metadata** — the columns riding alongside: `doc_id`, `title`, `heading`,
  `position`, `revision_id`, `license`. Used for citation and filtering.
  **Never embedded.**

### The problem

Wikipedia prose names its subject once in the lead and then says "the plan",
"it", "the programme". So a chunk cut from the middle of an article often never
states what it is about:

> The programme distributed $13.3 billion over four years...

Ask *"how much did the Marshall Plan cost?"* and that chunk is a weak match —
not because it lacks the answer, but because the subject is absent from the
text the vector was built from.

### The fix

```
Marshall Plan — Negotiations

The programme distributed $13.3 billion over four years...
```

The heading earns its place separately from the title: `Origins`, `Criticism`,
`Aftermath` are question-shaped words that appear nowhere in the body prose.

### Two rules that come with it

**The lead section has an empty heading**, so its prefix is just the title.

**The prefix does not count against the 1,200.** Otherwise a long title
silently shrinks its own article's chunks and sizes stop being comparable.

### The cost, stated honestly

Every chunk of one article shares a prefix, so they are all pulled slightly
toward each other. That is mostly what you want — but it does blur the
difference *between* sections of the same article.

---

## Part 6 — the edge rules

**Decision D-040.**

| Case | Rule | Why |
|---|---|---|
| document shorter than one chunk | one chunk, unpadded | nothing to split. 1,091 of 4,782 documents |
| final chunk under 200 chars of new content | merged into the previous chunk, which may overrun | otherwise it is 200 characters of which 150 is duplicate — a junk vector that still takes a top-5 slot |
| `overlap >= size` | `ValueError` | a caller mistake, not a data case. Clamping would hide the bug |
| the 96,737-char section | no special rule | ~80 chunks, which is correct |

### `chunk_id`

`"{doc_id}:{position}"` — so `30030:1:4`. This inherits `doc_id`'s
instability: it moves if `MIN_SECTION_CHARS` changes, and now also if the chunk
size or overlap changes.

Harmless while Gold is rebuilt whole and nothing outside stores an id. It
becomes a real problem in Phase 5, the moment Qdrant holds them and a re-chunk
silently invalidates every one. **Accepted until then, and it is a decision
owed in Phase 5.**

---

## Part 7 — the Gold table

**Decision D-041.** Eleven columns:

```
chunk_id  doc_id  page_id  position  title  heading  text
themes  revision_id  revision_timestamp  license
```

Silver's `categories`, `infobox`, `infobox_type` and `link_targets` are **not**
carried forward. They are article-level, so carrying them would repeat one
article's metadata across all of its chunks — in a table of 30,362 rows rather
than 4,782. `doc_id` and `page_id` are the join keys back to Silver, so nothing
is lost, only not duplicated.

**The cost arrives in Phase 5.** Whatever is omitted here cannot be filtered on
in Qdrant without a rebuild. Adding a column back costs one rebuild of a cache,
which is the whole reason the medallion split exists.

### Why Parquet

A CSV stores row 1, then row 2 — every field together, all as text. Parquet
stores every `chunk_id` together, then every `title`, then every `text`, each
block compressed on its own.

Measured on this table: **28.8 M characters of text, 9.7 MB on disk** — about a
third of a byte per character, because a column of 30,362 identical licence
strings compresses to almost nothing.

The reasons, in order of how much they actually buy here:

1. **Types survive the round trip.** `revision_timestamp` goes in a datetime
   and comes back a datetime; `themes` goes in a list and comes back a list. In
   CSV everything is text and you invent your own list encoding.
2. **Silver's schema is not expressible in CSV at all** — `infobox` is a list
   of structs.
3. **The schema is enforced at the boundary.** `to_frame()` passes
   `GOLD_SCHEMA`, so a wrong type fails at the write rather than three phases
   later.
4. **Column selection** — Phase 5 needs only `chunk_id` and `text`. *Honest
   caveat:* measured on this file there is no difference, 23 ms either way. At
   9.7 MB the whole file is one gulp. This benefit is real at gigabytes.

What it costs: not readable, not diffable in git, not appendable in place.
Which is why `corpus/registry.csv` is deliberately CSV — 772 titles reviewed by
hand and committed, where being readable matters more than being typed — and
`data/` is Parquet, where nothing is hand-edited.

---

## Part 8 — what reading the output found

**This is the part of the phase that mattered, and no test could have produced
it.**

The first build was 30,321 chunks and all 210 tests passed. A shape scan over
all of them found one dominant problem, and it was the item Phase 3 parked.

### The orphaned subheading

Silver keeps level-2 headings as a column but leaves level-3 subheadings in the
text as bare lines. To the packer those look like tiny paragraphs — and a chunk
very often filled up right after one:

```
...converted his cottage into a Hitler Youth camp.

Refugee status                     <- chunk N ends here
```

```
Einstein returned to Europe in 1932...   <- chunk N+1 starts here
```

Two consequences, and the second is worse:

1. The heading is dead weight at the end of chunk N — two words with nothing
   attached.
2. Chunk N+1 opens into content whose heading is gone. `Refugee status` is
   exactly the phrase someone would search for, and it is now in a different
   vector from the paragraphs about it.

**Measured: 3,268 chunks ended that way — 10.8%.** Another 529 did the same
with headings starting with a digit (`17th century`), so about **12.5% of the
corpus**. And **17 chunks were nothing but a heading** — 39 characters, no
claim, but still a vector that can take a top-5 slot.

### The fix, D-042

A heading belongs with what comes *after* it. So before packing, any paragraph
that is short (≤70 characters) and ends without closing punctuation is joined
to the paragraph below it.

```python
for paragraph in paragraphs:
    if _looks_like_a_heading(paragraph):
        pending.append(paragraph)
        continue
    attached.append("\n".join([*pending, paragraph]))
    pending = []
```

`pending` is a list because `Personal views` / `Political views` appear back to
back.

| | before | after |
|---|---|---|
| chunks ending on an orphaned heading | 3,268 | **82** |
| chunks that are only a heading | 17 | **0** |
| shortest chunk | 39 | 82 |
| total chunks | 30,321 | 30,362 |

**The 82 that remain are correct.** 81 are the last chunk of their document — a
heading with genuinely nothing after it, because Silver's filters removed what
it introduced. Keeping it beats dropping text.

### Why it was fixed in Gold and not Silver

The damage is a packing artefact, not a cleaning one. Silver's output is not
wrong; it just does not distinguish a heading from a short paragraph, and
nothing before Gold needed it to.

### The risk that was checked first

Gluing every short line to the next one could produce an enormous unit if a
section were a list of short lines. Measured before writing the fix:

| run length | count |
|---|---|
| 1 | 5,605 |
| 2 | 264 |
| 3 | 21 |
| 4 | 16 |
| 8 or more | 2 |

Longest run 16. So gluing cannot produce an oversized unit in practice.

### What else the scan found

- Nothing ends mid-word, nothing ends mid-sentence, no chunk contains an
  oversized word. **The ladder works.**
- **389 chunks (1.3%) are list-shaped** — the twin towns, book titles and film
  credits carried over from Phase 3's step 15. Not acted on. Phase 7 will say
  whether they cost anything.

---

## Part 9 — the shape of the code

```
chunk.py
    split_sentences        the middle rung. Public: tested directly, and the
                           overlap logic calls it
    _looks_like_a_heading  short, and no closing punctuation
    _attach_headings       glue a heading to what it introduces
    _pack                  the one grouping rule, used at all three rungs
    _units                 the ladder: text -> pieces that fit
    _overlap_text          the tail to carry forward
    chunk_document         the whole thing, pure
```

`chunk_document(doc: SilverRow, size: int, overlap: int) -> list[Chunk]`

**Pure by design.** No I/O anywhere below `build.py`, which is why 35 tests run
in 0.2 seconds with nothing on disk. It is also why this is the one part of the
project that can be tested exhaustively — the plan says so, and it is right.

**Why the input is a `SilverRow`.** Gold is *defined* as derivable from Silver,
so importing Silver's row type states the dependency honestly. The alternative
— a `Protocol` naming only the nine fields chunking touches — is more correct on
paper and buys nothing: there is one implementation and there always will be.
The bill for that choice is `to_document()` in `build.py`, which rebuilds
fields chunking never reads. At 4,782 rows that is nothing.

**`size` and `overlap` are arguments, not constants read inside.** The
constants `CHUNK_SIZE`, `CHUNK_OVERLAP` are the *production* values and are
used in exactly one place: the CLI defaults. Everything below is parameterised,
so tests can chunk at size 50 and Phase 7 can re-chunk from one command.

### Why the numbers are not in `.env`

`Settings` is for things that differ between machines — the Qdrant URL, the
OpenAI key. Chunk size does not differ between a laptop and a server; it
differs between *experiments*, and it has a written justification in
`decisions.md`.

In `.env` it would be untracked, changeable without a commit, and invisible in
git history — six weeks later you could not tell which value produced the index
you are evaluating. A CLI flag gives the same flexibility while the default
stays in the repo, and the command you ran is in your shell history.

---

## Part 10 — a Python thing that came up: `app` and `@app`

`app = typer.Typer(...)` creates an empty command-line program. It has a name
and a help text and no commands.

`@app.command()` above a function adds one item to that program's menu: "there
is now a command called `chunk`, and when someone types it, call this
function." The command name comes from the function name; each parameter
becomes a flag; the flag's type comes from the type hint. Same trick FastAPI
uses in `api/main.py`.

`@app.callback()` is not a command — it runs *before* whichever command was
chosen, which is why `configure_logging()` lives there.

**The distinction that has now come up three times** (Phase 1's `@lru_cache`,
Phase 2's Typer wiring, here): a decorator takes its own arguments, separate
from the function's.

```python
@app.command()                  # configures the registration
def chunk(size: int = 1200):    # the command's flags
```

`@app.command(name="rechunk")` would register the same function under a
different command name. Nothing to do with what `chunk` receives.

`pyproject.toml`'s `[project.scripts]` points `eurohistory` at `app`, so
`uv run eurohistory chunk` starts the program, `app` looks `chunk` up in its
menu, and calls the function.

---

## Part 11 — a repo problem this phase surfaced

Adding `tests/pipeline/gold/test_build.py` next to the existing
`tests/pipeline/silver/test_build.py` broke **both** pytest and mypy:

```
Duplicate module named "test_build"
```

Without `__init__.py`, Python identifies a test file by its **basename alone**,
so two files called `test_build.py` are the same module and one shadows the
other. This was parked in the Phase 1 handoff as a known hazard; it came due.

Fixed properly rather than by renaming: an empty `__init__.py` in `tests/` and
every subdirectory, so the full path is part of the module name. Renaming to
`test_gold_build.py` would have worked today and broken again at
`tests/pipeline/gold/test_store.py`.

---

## Concepts this phase requires

Against the plan's list:

| Concept | Where |
|---|---|
| why chunk at all — both reasons | Part 1 |
| what overlap is for, and the cost of too much | Part 4 |
| the split boundary, and what each alternative breaks | Part 2 |
| roughly how many tokens, and why it matters twice | Part 3 |
| what happens to a document shorter than one chunk | Part 6 |

---

## Parked out of this phase

- **The 389 list-shaped chunks.** Candidate fixes: more heading names, or a
  shape test. Neither decided. Phase 7 says whether they cost anything.
- **`chunk_id` instability.** A decision owed in Phase 5, when Qdrant starts
  storing ids.
- **`build()` holds every chunk in memory** — about 40 MB here. A ceiling, not
  a design.
- **`MIN_TAIL_CHARS` is a constant, not a parameter**, so tests cannot vary it.
  Accepted: it is a quality floor rather than a tuning knob.
- **Parent-document retrieval** — the proper answer to the small-versus-large
  chunk tension. Phases 11+, gated on Phase 7 evidence.
- **Step 14's hand reading.** Ten chunks were sampled and read; the
  observations were not written down, so the list-shaped chunks and the
  off-theme sections are still unexamined by eye.
