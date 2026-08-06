# Phase 15 — questions that match the corpus

Short, because the code is small. The concepts here are about **what ground
truth is and what it is not**, and the phase found out the hard way.

---

## What this phase did

Phase 14 grew the corpus 81% and not one retrieval number moved, because all
thirty questions were about the third of the corpus that existed before. This
phase wrote thirty more, covering the six themes that were added, and made the
eval report every run **three ways** — the old thirty alone, the new thirty
alone, and all sixty.

Cost: **$0.25** — two evaluation runs and one faithfulness run.

---

## Idea 1 — a control is a thing that must not change

The old thirty were left **byte-identical**. Not "mostly unchanged", not
"tidied up" — the same bytes, so that this run can be laid next to
`2026-08-06T1331Z` and any difference has exactly one possible cause.

They reproduced to three significant figures, twice, on two separate runs:
recall@5 75.0%, recall@20 100.0%, coverage@5 47.9%, MRR 0.54, top-1 0.655.

That is worth more than it sounds. It says retrieval in this system is
**perfectly repeatable** — same question, same corpus, same list, every time.
Generation is not: the answers differed between the two runs. So any future
claim about a retrieval change is a real claim, and any claim about a small
generation change needs a noise floor first, which is Phase 16.

**In plain words.** If you want to know whether a new pair of glasses helps, you
read the same eye chart. Changing the chart at the same time as the glasses
tells you nothing. Half the chart here is nailed down forever, and it read
exactly the same twice — which also proves the chart itself is stable.

---

## Idea 2 — ground truth written by sampling is not ground truth

This is the finding of the phase and it is a failure, not a success.

The answer key for each question is a list of section ids: "these are the
sections that should come back". `recall@5` asks whether any of them appeared
in the top five. Write the key by reading the corpus and listing the sections
that answer the question, and it looks airtight.

It is not, and the reason is arithmetic. In the old 664-article corpus most
topics had **one** article. In today's 1,274-article corpus most topics have
**three or four**. So a key that names the sections you happened to read is a
*sample* of the correct answers, and every correct section you did not list is
counted as a miss.

The extended thirty scored **recall@5 62.5%** against the golden thirty's
**75.0%**. Read the results and most of that gap is the key, not retrieval:

| Question | Key named | What came back at rank 1-5 |
|---|---|---|
| `why-life-got-better-fast` | Post–WWII economic expansion | `Italian economic miracle`, `Wirtschaftswunder`, `Trente Glorieuses`, `West Germany — Economy` |
| `travel-without-showing-papers` | Schengen **Area** | Schengen **Agreement**, `European single market — Four freedoms` |
| `care-from-cradle-to-grave` | NHS, Post-war consensus | `Clement Attlee — Prime Minister`, `Welfare state — By country` |
| `country-came-apart` | Breakup of Yugoslavia §2, §3 | Breakup of Yugoslavia §0, `Yugoslavia — Breakup` |
| `empires-let-go` | Decolonisation of Africa §2, §5 | `British Empire — Decolonisation and decline`, `Decolonization — By area` |

In **six of the seven** questions that scored zero coverage, the top result was
either the same article at a different section or a different article covering
the same material. Those are right answers scored as wrong.

The mechanism is specific and avoidable: the 608 candidate articles were listed
by filtering to the six *new* themes. `British Empire`, `Wirtschaftswunder`,
`Trente Glorieuses` and `Schengen Agreement` all sit in older themes, so they
were never on the list they should have been chosen from.

**The keys were left exactly as written.** Broadening them after seeing which
questions failed would be fitting the answer key to the run, and the number
would stop meaning anything. The defect is measured, written down, and is the
first item Phase 16 inherits.

**In plain words.** Marking an exam with an answer sheet that lists one correct
answer when there are four. The student writes a different correct answer and
gets a zero. The student is fine; the answer sheet is wrong. And you do not fix
it by looking at what the students wrote.

---

## Idea 3 — the rule you wrote against a mistake will not stop you making it

Three phases in a row produced "unanswerable" questions the corpus answered
perfectly well. Phase 15's own roadmap section says, in bold:

> Questions come from reading the corpus, never from guessing it.

Six candidate unanswerable questions were checked by searching all 8,894 Silver
sections. Three were killed by the check — the 1972 Munich massacre, the 2004
Madrid bombings, the 2017 Catalan referendum — because the corpus answers each.
That is the rule working.

Then `danish-cartoons` shipped anyway, and the corpus answered it at rank 1
with a fully grounded, cited answer covering the editorial rationale, the
February 2006 protests, a bomb threat and the 2008 Islamabad embassy bombing.

The cause is exact and it is worth more than the rule: the search returned five
hits and **each was judged from a 200-character window around the match**
instead of by opening the section. `Blasphemy — By religion` is 10,602
characters. The window showed a passing mention. The section held six
paragraphs.

Searching is not reading. A regex tells you *where* to look, and then you have
to look.

---

## Idea 4 — a metric that measures the wording, not the behaviour

`seveso-1976` replaced `danish-cartoons` and answered:

> The sources do not cover what happened at the Seveso chemical plant in Italy
> or how the people living nearby were affected. They mention the Seveso
> chemical accident as an ecological disaster [1]. However, no specific details
> about the event or its impact on local residents are provided.

That is a perfect refusal — it declines, reports the one thing the corpus does
say, cites it, and stops. It scored as a **non-refusal**, because `metrics.py`
detects a refusal by looking for the literal string `not in the sources`, and
the model wrote `The sources do not cover`.

So the true refusal rate on the extended six is **6 of 6**, reported as 5 of 6.

This is the second time this exact metric has lied. Phase 7's first baseline
reported 0% refusals because the phrase had been *guessed* rather than read out
of the prompt. It was fixed by reading the prompt; it is wrong again because
the prompt has two ways of declining and the metric knows one of them.

**Not fixed here, deliberately.** One change at a time: this phase changed the
question set, and redefining "refusal" would change a number published across
six earlier runs at the same moment. Parked for Phase 16 or 17, where it is a
free `rescore` away.

**In plain words.** The test asks "did the machine say *I don't know*?" and
checks by searching for those exact words. The machine said "I have no
information on that", which is the same thing, and the test marked it wrong.

---

## What the new set is, in one table

| | golden (Phase 7) | extended (Phase 15) |
|---|---|---|
| Written from | a 664-article corpus, 1914-1945 | a 1,274-article corpus, 1945-2024 |
| easy / multi / paraphrase / unanswerable | 8 / 8 / 8 / 6 | 8 / 8 / 8 / 6 |
| Unanswerable spread | five British, one out of domain | France, Germany, Belgium, Italy, Finland, one out of domain |
| Status | frozen forever, the control | the measurement |

The `suite` field is what makes this work. It lives on the question, is carried
into every saved record, and defaults to `"golden"` — so the original thirty
did not have to be edited to acquire it, which is what kept them byte-identical.

---

## What did not change

No retrieval code, no generation code, no prompt. `SearchService` and
`GenerationService` are identical to the run being reproduced, which is why the
control reproducing exactly means what it means.
