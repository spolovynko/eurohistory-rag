# Phase 22 — temporal retrieval

Concept notes. The decisions and the numbers are in `docs/decisions.md` under
D-096; this is the explaining.

---

## Why anyone thought a RAG system would be bad at years

**Technical.** A dense retriever turns text into a vector and compares vectors by
cosine similarity. Nothing in that pipeline does arithmetic. "1947" is a token,
"1953" is a token, and the model has no operation that says one is smaller than
the other or that 1949 lies between them. So the expectation was that "between
1947 and 1953" would retrieve on the *words* 1947 and 1953, and a chunk
mentioning 1947 once would beat a chunk covering the whole period.

**Plain.** Imagine a librarian who does not understand numbers at all, but who
has memorised which words tend to appear near which. Ask for books about
1947-1953 and they will fetch books with "1947" printed somewhere, not books
about that stretch of time. They cannot tell you 1950 is inside it.

**And in this corpus that expectation was wrong**, for a reason nobody planned.
Back in Phase 4 the decision was made to paste the article title and section
heading onto the front of every chunk before embedding it, so a chunk saying
"the programme distributed $13.3 billion" would carry "Marshall Plan" with it.
The side effect: Wikipedia writes the period *in the heading*. So the text that
becomes the vector for one particular chunk literally begins

```
Cold War — Renewal of tensions (1979–1985)
```

The librarian does not need to understand numbers, because somebody wrote the
years on the spine and the librarian matches spines. Measured: **87.5% recall@5
on the temporal questions before this phase wrote a line of code.**

---

## The date a chunk mentions versus the period it covers

This is the distinction the whole phase turns on.

**Technical.** `Berlin Blockade § Western response: The Berlin Airlift` mentions
1989 in a closing sentence about the wall. It does not *cover* 1989. A filter
built on mentioned dates would match that section for a question about 1989 and
be wrong. So the period is taken from the most authoritative source available,
in order: the section heading, then the article title, then — only if neither
names a year — the years mentioned in the body.

**Plain.** There is a difference between a book *about* the 1940s and a book
about something else that happens to say "1943" on page 200. The heading is the
publisher's own description of what the section is about, so it is trusted first.
The body is a last resort and it is where the mistakes are.

**And the mistakes are real.** The airlift section came out dated **1800-1949**,
because its text says "a 1800 m-long asphalt runway". A runway length read as a
year. Found by printing the ten widest spans and reading them, which no test
would have caught.

The split over 54,903 chunks:

```
from the body       61.2%   the weakest source carries most of the corpus
no date at all      28.1%
from the heading     6.2%   the only source anyone wrote on purpose
from the title       4.5%
```

**One chunk in nine has a period anybody actually declared.** That is the honest
ceiling on date filtering over this data, and it was not visible before.

---

## Why the filter adds and never subtracts

**Technical.** The obvious design is a pre-filter: search only chunks whose years
overlap the question's. That deletes 28% of the corpus from every dated question
— including all three sections needed by `t-weimar-early-1920s`, none of which
carries a year in its heading or title. So instead the filtered search is a
*third arm*: its results are fused into the existing reciprocal rank fusion
beside the dense list. A chunk that is right on meaning *and* period appears in
two lists and rises. A chunk with no date is scored by the other arms alone and
is never removed.

**Plain.** Rather than throwing away every book without a date on it, we run the
search twice — once normally, once among dated books only — and a book that does
well in both goes to the top. Undated books can still win on the normal search.
Nothing is thrown away.

---

## Why "after the war" resolves to nothing

**Technical.** A date sitting next to "after", "before", "since" or "the end of"
is a reference point, not a period. "What was Germany made to pay after 1918" is
about the 1920s; reading it as the single year 1918 is not a near miss, it is the
wrong answer. How far past the point the question reaches cannot be read off the
words, so the parser returns nothing and the temporal arm does not run. 43 of the
78 evaluation questions take that path.

**Plain.** "After the war" means nothing on its own here, because this corpus
contains three wars anyone might mean. A system that quietly picks one is worse
than one that shrugs, because the wrong pick actively drags the search to the
wrong decade. Shrugging just leaves the search as it was.

---

## The finding that had nothing to do with dates

**Technical.** Qdrant finds nearest neighbours by walking an HNSW graph — a
network where each vector links to a few near ones, so a search hops toward the
answer instead of comparing everything. Apply a filter and most points along the
route vanish, and the walk can strand itself in a region the answer is not in.
Measured: `Cold War § Renewal of tensions (1979–1985)`, a perfect match on both
meaning and period, was **absent from eighty filtered results** while a
brute-force scan of the same filtered set put it **second**. Raising the search
effort eightfold did not find it. Fixed by scanning exactly, which costs nothing
here (7-26 ms against 7-31 ms) because the filter has already made the set small.

**Plain.** The fast search works by following a trail of signposts between
similar books. When the filter removes most of the books, it removes most of the
signposts too, and the search walks into a dead end and reports what it found
there. Checking every remaining book one by one is slower in principle and
faster in practice, because there are not many left.

This was on the roadmap as a *concept to be able to explain*. It arrived as a
bug instead, which is a better way to learn it.

---

## What the phase measured

```
                    before    after
temporal recall@5    87.5%    87.5%     the done-when metric: no change
temporal MRR         0.622    0.629
extended recall@20   91.7%    87.5%     a real regression
golden coverage@5    47.9%    46.5%     a real regression
refusals              7 of 78  7 of 78  unchanged
```

**Gate FAILED, 7 checks. Default off.** One temporal question gained
(`t-eastern-europe-1989`, rank 9 → 4), one lost (`t-1970s-economy`, 5 → 6).

The code, the payload, the tests and the flag all stay, exactly as hybrid search
stayed after D-074. Turning it on is one line and a free payload refresh.

---

## Two mistakes worth more than the result

**A run measured the flag switched off.** `RunConfig` gained `temporal: bool =
False`, the CLI builds that object field by field and was never taught to pass
it, and $0.105 bought a table identical to the one before it. Caught by
`meta.json`, which is the Phase 8 guardrail doing exactly its job. **The default
was the defect** — removing it turned the missing wire into a type error and
`mypy` immediately named a *second* forgotten call site, the page's run button.

**A question was written as unanswerable and was not.** `t-pandemic-2020` was
checked by reading a window around a regex match instead of the section. The
corpus holds Merkel's crisis team, von der Leyen's Schengen decision, Next
Generation EU and Italy's emergency measures. This is the `seveso-1976` mistake
from D-087, repeated inside the phase whose own question file cites it as the
thing not to do — and the identical cause. Corrected after the comparison closed,
never during it.
