# Phase 19 — the knobs

Concept reference. Decisions and numbers live in `decisions.md` under D-092.

---

## What "per-request" means, and why it is not a second endpoint

`POST /ask` gained three optional fields — `hybrid`, `reranker`, `model` — on
top of the `k` it always had. Leave them out and the request behaves exactly as
it did before they existed.

The alternative was a second endpoint, and it is forbidden for the reason
D-090 gave: the eval runner and the page must run the same code, or the numbers
stop describing the thing people use.

**In plain words:** the kitchen has one recipe. You can ask for it without salt,
but you cannot order from a different kitchen and still be told it was graded.

---

## Why these were restart-only until now

`get_settings()` is cached, and `api/dependencies.py` cached the built services
on top of it. So the configuration was read once, baked into an object, and
reused until the process died.

The fix is not to stop caching. It is to cache **by cost** instead of by
"the one":

| Thing | Cost to build | Now |
|---|---|---|
| Qdrant connection | expensive | one, shared |
| A reranker's weights | ~487 MB from disk | one per name, kept |
| An OpenAI client | small | one per model, kept |
| `SearchService` | nothing — it holds references | built per request |

**In plain words:** the ovens stay hot and shared. Only the order slip is
written fresh each time.

---

## The prediction that was wrong in the good direction

D-091 said this phase would have to modify `retrieval/` and `generation/`. It
modified neither.

`SearchService.__init__` already took `hybrid` and `reranker`;
`OpenAIGenerator.__init__` already took `model`. Phases 8 and 9 built them that
way so a single experiment could be switched on and off. Eleven phases later the
same seams turned out to be a control panel, and the API layer only had to pass
different values.

**In plain words:** the light switches were already wired into the walls. This
phase put a panel by the door.

That is the payoff of a rule that felt fussy when it was written: *add behaviour
by adding, not by editing what works.*

---

## `null` and `""` are different requests

One field, two meanings, and they cannot be merged:

| Sent | Means |
|---|---|
| field absent, or `null` | use whatever this server is configured with |
| `""` | switch reranking **off** for this request |
| `"cross-encoder/…"` | use this one |

Merge them and "off" becomes unreachable from the page.

---

## Why the allow-list exists

`model` and `reranker` arrive from a browser. A model name passed to OpenAI
unchecked is a way to bill this account for whatever somebody types; a reranker
name passed to HuggingFace unchecked reads half a gigabyte off the network on a
stranger's say-so. Both are checked against a list in `Settings`, and anything
else is refused before a single call is made.

Every model on that list was called once and verified to answer. `gpt-5-mini`
was tried and left off: it spends its budget on reasoning tokens and returned an
empty answer under the same cap the others answered within.

---

## The broken model that stayed on the menu

`BAAI/bge-reranker-base` is the value in `config.py` and Phase 8 measured it
ranking "Treaty of Rome" above East German emigration for a Berlin Wall
question, and giving two unrelated documents an identical 0.000.

It is still selectable, marked `⚠ measured broken`, with the finding on hover.
Hiding it would make the documented default unreproducible from the page —
someone reading `config.py` would find a setting the interface denies exists.

**In plain words:** you do not remove the wonky chair from the room. You put a
sign on it.

---

## What the answer now says about itself

Every answer carries the configuration that produced it, and the footer prints
it:

```
gpt-4.1-nano · reranker ms-marco-MiniLM-L6-v2 · hybrid on · k 5 · 1.6 s
```

Phase 8 shipped a whole measurement whose reranker was switched off, and it was
caught only because a metadata field had been added twenty minutes earlier. An
answer that cannot say what produced it is that same failure, standing in front
of a person instead of sitting in a run directory.

---

## What flipping hybrid actually costs

Measured, not guessed. Same sixty questions, same corpus, one switch:

```
golden   recall@5    75.0%  ->  70.8%
golden   recall@20  100.0%  ->  91.7%
extended recall@5    62.5%  ->  62.5%
extended coverage@5  38.9%  ->  39.6%
```

**Phase 9 measured 75.0% → 70.8% on a corpus 81% smaller. This run measured
75.0% → 70.8%.** The same number, eleven phases and 24,541 chunks later.

The damage sits entirely in the 1914-1945 questions. The 1945-2024 questions
came through level, and coverage there was the single metric that rose.

**In plain words:** keyword search does not add passages here so much as elbow
others out of the queue. On the newer material — full of treaty names, acronyms
and dates — it at least stops doing harm.

**Nothing was switched on.** The default is unchanged; the phase's product is
that the switch exists and now has a price tag on it.
