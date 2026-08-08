# Phase 18 — the front end

Concept reference for the phase that gave this system a face. Decisions and
numbers live in `decisions.md` under D-090; this file is the explanations.

---

## Why this phase had no eval failure behind it

Every other phase from 9 onward starts by quoting a number that is worse than it
should be. This one cannot, and the reason is mechanical rather than an excuse.

The eval runner imports `SearchService` and `GenerationService` and calls them
as Python objects (`eval/run.py:92`). It has never made an HTTP request in its
life. So a page that talks to `/ask` sits on the far side of a boundary the
measuring instrument does not cross — it cannot improve a number and it cannot
break one.

**In plain words:** the ruler measures the engine. This phase built the
dashboard. Putting a dashboard in front of an engine does not change how fast it
goes, and measuring the engine again would only prove that we did not touch it.

So the evidence became the promise instead: `git diff` over `retrieval/`,
`generation/` and `pipeline/` must come back empty. It did. That is checkable by
a computer, costs nothing, and is a stronger claim than a $0.08 A/A run.

---

## Why one HTML file and not a framework

The roadmap offered two shapes: templates inside the API, or a separate
front-end project. A third was chosen — one static file, served by the API,
which the browser fills in by calling `/ask`.

| | Cost | Bought |
|---|---|---|
| One static file | Throwaway the day it needs components | No dependency, no build step, no second process, no CORS |
| Jinja2 templates | A dependency and a template language | Server-rendered HTML — for a page with one changing region |
| Separate project | A toolchain, a second thing to run and deploy | What a real product looks like |

**In plain words:** a template engine is a machine for printing a page with the
answers already filled in. But we do not know the answer until four seconds
after the question is asked, so the page would have to be printed twice — once
empty, once full. Easier to print it once and let the browser write into it.

The file sits next to `main.py` and is loaded with `importlib.resources`, the
same way `system_prompt.md` sits next to `messages.py`. Same reasoning: it is
text, it is edited far more often than the code serving it, and it diffs better
as a file than as a Python string.

---

## Why the sources are the product

Phase 6 built inline `[n]` markers and a citation list so a reader could check a
claim. A UI that hid them would throw that away and look better for it — fewer
things on screen is the whole brief.

They stayed, and each one carries four things: which article, which section, how
strongly it matched, and **the exact passage the model was given**, folded into a
`<details>` element so it is quiet until asked for.

That last one is the unusual part. Most systems show you a link. This shows you
the paragraph the answer was written from, so a claim can be checked without
leaving the page — the same thing `transcript.txt` does for the eval, for a
person who is not running an eval.

**In plain words:** an answer you cannot check is a rumour with good typography.

The Wikipedia link is an `oldid` URL — the article *at the revision that was
indexed*, not as it reads today. Wikipedia changes; a citation that drifts is
not a citation.

---

## The two ways this can fail, and why they must not look alike

| | What actually happened | What the reader is told |
|---|---|---|
| **Refusal** | The corpus was searched, chunks came back, and the model said the passages do not cover it | *"No source in the corpus covers this. The answer below is a refusal, not a failure."* |
| **503** | Qdrant or OpenAI is down. Nothing was searched | *"The system is unreachable... Nothing was asked of the corpus."* |

Both were produced against the real system, the second by stopping the container.

**In plain words:** "I looked and it isn't there" and "I couldn't get to the
shelf" are different sentences, and a reader who cannot tell them apart learns
the wrong thing about the corpus. The first is the system working. Only the
second is broken.

The colours differ too, but the wording is the load-bearing part.

---

## What a person actually experiences as slow

The eval reports p50 3,822 ms over sixty questions. In the browser, four
questions took 9.7, 3.3, 8.9 and 4.8 seconds.

Two separate things are in those numbers.

**A median is not an experience.** The fifteenth-fastest of thirty questions is
a statistic about a suite. A person asks one question and waits for that one.

**The first question of a session pays a toll nobody had measured.** The
cross-encoder reranker is built lazily, so the first request after the server
starts loads a 487 MB model from disk. The eval never sees this: it loads once
and then asks sixty questions, so the cost is amortised into invisibility. A
person opens the page and asks exactly one question first — the expensive one.

**In plain words:** the shop's opening time is not counted in how long it takes
to serve the tenth customer. It is the whole of the first customer's wait.

This is Phase 19's problem now. Streaming makes the first word arrive sooner; it
cannot make a model load faster.

---

## Why nothing may bypass `/ask`

The page makes exactly one network call, and a test asserts it:

```python
FETCH = re.compile(r"fetch\(\s*\"([^\"]+)\"")
assert FETCH.findall(PAGE) == ["/ask"]
```

If the page ever grew its own endpoint — a faster one, a simpler one, one that
skipped the reranker — then the eval and the page would be measuring different
systems, and every number in `decisions.md` would quietly stop describing the
thing people use.

**In plain words:** you cannot grade one recipe and serve another.

---

## The bit that is not code

Nothing from the server is ever written into the page as markup. Answers and
chunks are built as text nodes and real elements; `innerHTML` appears nowhere
and a test asserts that too.

The corpus is Wikipedia — other people's text, fetched over the network. Text
that becomes markup becomes something the browser will run. The safe habit is
free here, so it is not negotiable.

**In plain words:** paste the letter into the frame; never let the letter
rewrite the frame.

---

## The stale-bytes trap

`PAGE` is read once, when the module is imported:

```python
PAGE = files("eurohistory_rag.api").joinpath("page.html").read_text(encoding="utf-8")
```

That is right for production — a file that never changes while the server runs
should not be read from disk on every request. It is a trap during development,
because editing the page changes nothing until the process restarts, and the
server keeps serving the old bytes with no warning of any kind.

It caught me. A one-line fix to the source ordering was declared verified on the
strength of a run that listed its sources 1, 2, 5 — which was simply an answer
whose citations were already in order, from a server still running the unfixed
page. **A passing observation is not evidence for a change that was not
running.** That is Phase 8's dead reranker, at one hundredth of the scale.

Two things closed it. `--reload` in `.claude/launch.json`, so the server
restarts when the page is edited. And a proper proof: `window.fetch` stubbed in
the browser to hand the page sources in the order 5, 2, 3, which the shipped
code rendered as 2, 3, 5.

**In plain words:** the kitchen printed the menu once when it opened. Rewriting
the menu on the noticeboard did not change the one already printed, and the
waiter kept reading from the printed copy — while I watched a table order the
dishes in the right order by chance and concluded the new menu was working.

The same stub proved two things that had never actually happened in a browser:
a citation marker with no source behind it stays as plain text rather than
becoming a link to nowhere, and a passage containing `<b>` is displayed as those
characters rather than turned into bold text. Both were written on purpose in
Phase 18 and neither had ever been executed until they were forced.

---

## Colour with a job

The instruction was "more colour, keep it minimalistic", and those pull against
each other unless the colour is doing something. So it was given one thing to do:

**A citation and its source wear the same hue.** `[3]` in the answer is amber;
the third source card has an amber bar, an amber number and an amber score.

Why that is not decoration: `k` is 5, and Phase 7 measured **1.1 distinct
articles per five slots** on easy questions. So the sources list is routinely
five entries from two or three articles, with titles that differ by one word.
The Prague Spring question returned these five:

```
1  Prague Spring
2  Alexander Dubček — Prague Spring
3  Prague Spring — Aftermath
4  Warsaw Pact invasion of Czechoslovakia — Background
5  Prague Spring — Aftermath
```

Two of the five carry the same title. Finding the card for `[3]` by reading is
genuinely fiddly; finding the amber one is instant.

**In plain words:** five near-identical labels are hard to tell apart, five
colours are not. That is the whole argument, and it is why the colour is on the
citations rather than sprinkled around the page.

The hue is chosen in CSS, never in JavaScript:

```css
[data-hue="3"] { --c: var(--c3); }
```

The script sets `data-hue` and nothing else. Colour values live in one place,
and the dark theme swaps all six at once — saturated mid-tones on paper,
pastels on near-black, because a dark indigo bar on a dark card is not visible.

## The invisible-heading trap

The gradient title works by painting a gradient behind the text and clipping it
to the letter shapes, with the text itself set to transparent. If the clipping
does not apply — an older browser, an odd rendering mode — the text stays
transparent and **the title vanishes**.

So it is opt-in:

```css
@supports ((background-clip: text) or (-webkit-background-clip: text)) { ... }
```

Without support, the heading is plain ink. **In plain words:** do not remove the
ink until you are certain the stencil works.

---

## The evaluation tab

Two views, one page, switched by the address bar: `#ask` and `#eval`. They are
links rather than buttons, so a view can be bookmarked and the back button
works.

**What it shows, and why each part is there.**

| Part | The question it answers |
|---|---|
| Run picker | Which run am I looking at? Fifteen exist. |
| Condition chips | What was true when it ran — chunks, `k`, model, reranker. Phase 8 shipped a run whose reranker was off and nobody noticed. |
| Suite picker | The golden thirty alone, the extended thirty alone, or all sixty. Phase 15 kept them separable on purpose. |
| Six cards | Was it found, was it found early, what did it cost. |
| By-kind table | The overall number hides that easy questions carry it up and paraphrased ones carry it down. |
| The strip | One square per question. |

**The strip is the part worth building.** Sixty squares, coloured by what
happened: found in the top 5, found but ranked below 5, never found, or no
answer key. Hovering one names the question and the rank.

Scoring all sixty of `2026-08-06T1832Z` it reads 33 / 13 / 2 / 12, and the
thirteen near-misses sit at ranks 7, 8, 7, 19, 8, 10, 9, 16, 16, 7, 7, 8, 9.
**Ten of the thirteen are between 7 and 10.**

**In plain words:** "recall@5 is 68.8%" tells you a third of the questions
failed. It does not tell you they failed *narrowly* — that the right passage was
sitting at number seven when the system only looks at the first five. Thirteen
amber squares tell you that at a glance, and "the ranking is nearly right" is a
completely different problem from "the corpus does not have it".

## Why the page cannot start an evaluation

There is no button for it and there is no endpoint for it.

A run costs about $0.08 and four minutes. That is not the reason. The reason is
that every phase in this project writes down what it expects to see *before* the
command runs — and a run produced by clicking a button is a run nobody predicted
the result of, which teaches nothing and can be quietly repeated until a
flattering number appears.

**In plain words:** you write down your guess, then you look. A button that
skips the writing-down turns an experiment into a slot machine.

## What the metrics page had to get right

Its numbers had to equal the numbers in `decisions.md`. The golden thirty come
back recall@5 75.0%, recall@20 100.0%, coverage@5 47.9%, MRR 0.54 — the figures
five separate runs have published.

That check matters more than it sounds. A metrics view computing its own
slightly different numbers would be a second instrument disagreeing with the
first, and the honest response to that is to trust neither. It shares
`metrics.py` with `evaluate`, `rescore` and `gate` for exactly this reason: one
definition of recall, four things reading it.
