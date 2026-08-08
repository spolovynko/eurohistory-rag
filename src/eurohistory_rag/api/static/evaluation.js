// --- the evaluation view ---
//
// Reads saved runs through /runs and scores them. Exports the one function
// routing needs, so that opening the tab is what triggers the first read.

import { el, getJSON, setStatus } from "./dom.js";

const runPicker = document.getElementById("run-picker");
const suitePicker = document.getElementById("suite-picker");
const evalStatus = document.getElementById("eval-status");
const conditions = document.getElementById("conditions");
const cards = document.getElementById("cards");
const tableHeading = document.getElementById("table-heading");
const kindsTable = document.getElementById("kinds");
const stripHeading = document.getElementById("strip-heading");
const strip = document.getElementById("strip");
const legend = document.getElementById("legend");
const evalNote = document.getElementById("eval-note");

let loadedRun = null;
let runsListed = false;

const pct = (v) => (v === null ? null : (v * 100).toFixed(1) + "%");

// The six metric cards, in the order they answer questions about a run:
// was it found at all, was it found early, and what did it cost.
// Each card explains itself on hover, twice: the exact definition, then the
// same thing in ordinary words. Both live here rather than in the panel below,
// which no longer repeats them.
const CARDS = [
  { label: "recall@5", hue: "1",
    exact: "Of the questions that have a correct answer on file, how often at least one correct passage appeared in the five the model was shown.",
    plain: "Did the right page make it into the handful it actually read?",
    of: (s) => pct(s.recall_at_5), fill: (s) => s.recall_at_5 },
  { label: "recall@20", hue: "2",
    exact: "The same, but looking twenty deep instead of five.",
    plain: "If we let it look further down the pile, is the right page there at all?",
    of: (s) => pct(s.recall_at_20), fill: (s) => s.recall_at_20 },
  { label: "coverage@5", hue: "3",
    exact: "Of every passage that should have come back, the fraction that did. A question needing three sections and getting one scores 33%, even though recall counts it as a hit.",
    plain: "It found a right answer. Did it find all of them?",
    of: (s) => pct(s.coverage_at_5), fill: (s) => s.coverage_at_5 },
  { label: "MRR", hue: "5",
    exact: "Mean reciprocal rank. Position of the first correct passage as a score: rank 1 is 1.00, rank 2 is 0.50, rank 4 is 0.25.",
    plain: "Not just whether the right page was there, but how near the top it sat.",
    of: (s) => (s.mrr === null ? null : s.mrr.toFixed(2)), fill: (s) => s.mrr },
  { label: "refusals", hue: "4",
    exact: "How often the system declined to answer rather than inventing something. Some questions are unanswerable on purpose.",
    plain: "Saying “I don’t know” when it genuinely does not know is the behaviour being tested, not a failure.",
    of: (s) => pct(s.refusal_rate), fill: (s) => s.refusal_rate },
  { label: "p50", hue: "6",
    exact: "The middle question’s total time — half were faster, half slower. Reported, never used to pass or fail: three identical runs moved it by 893 ms on their own.",
    plain: "A typical wait. It wobbles too much to prove anything.",
    of: (s) => Math.round(s.p50_total_ms) + " ms",
    fill: (s) => Math.min(1, s.p50_total_ms / 10000) },
];

// Label, how to read the cell, whether the cell carries a bar, and the
// description shown on hovering the column heading.
const COLUMNS = [
  ["kind", (s) => s.kind, false, "what sort of question: literal, spanning two articles, reworded, or unanswerable on purpose"],
  ["n", (s) => String(s.questions), false, "how many questions of this sort"],
  ["r@5", (s) => pct(s.recall_at_5), true, "recall@5 — how often the right passage was among the five it read"],
  ["r@20", (s) => pct(s.recall_at_20), false, "recall@20 — how often it was there at all, looking twenty deep"],
  ["cov@5", (s) => pct(s.coverage_at_5), false, "coverage@5 — of every passage that should have come back, how many did"],
  ["MRR", (s) => (s.mrr === null ? null : s.mrr.toFixed(2)), false, "how near the top the first right passage sat (1.00 = first place)"],
  ["arts", (s) => s.mean_distinct_articles_at_5.toFixed(1), false, "how many different articles the five passages came from — five slots holding one article three times do the work of three"],
  ["refuse", (s) => pct(s.refusal_rate), false, "how often it declined instead of inventing an answer"],
  ["p50 ms", (s) => String(Math.round(s.p50_total_ms)), false, "the middle question's wait; too wobbly to prove anything"],
];

const OUTCOMES = [
  ["hit", "found in the top 5"],
  ["deep", "found, but ranked below 5"],
  ["miss", "never found"],
  ["none", "no answer key — the refusal cases"],
];

// A model or reranker is published as a full path. The last segment is the
// name a person recognises; the whole thing stays available on hover.
function shortName(identifier) {
  return identifier.split("/").pop();
}

function renderConditions(meta, questions) {
  conditions.replaceChildren();
  const facts = [
    ["run", meta.run_id, null],
    ["questions", String(questions), null],
    ["chunks", meta.points.toLocaleString("en"), null],
    ["k", String(meta.k), null],
    ["answering model", shortName(meta.generation_model), meta.generation_model],
    ["reranker", meta.reranker ? shortName(meta.reranker) : "off", meta.reranker],
    ["hybrid search", meta.hybrid || "off", meta.hybrid],
  ];
  for (const [name, value, full] of facts) {
    const fact = el("div", "fact");
    const shown = el("span", "v", value);
    // The last two are switches, and a run with one flipped is not comparable
    // to a run without it. They are shown as lit or unlit, not as text to read.
    if (name === "reranker" || name === "hybrid search") {
      shown.classList.add("state");
      shown.dataset.on = full ? "yes" : "no";
    }
    if (full && full !== value) shown.title = full;
    fact.append(el("span", "k", name), shown);
    conditions.append(fact);
  }
}

function renderCards(row) {
  cards.replaceChildren();
  for (const spec of CARDS) {
    const value = spec.of(row);
    const card = el("div", "card");
    card.dataset.hue = spec.hue;
    // Focusable so the description is reachable without a mouse: a hover-only
    // explanation does not exist for anyone using a keyboard or a phone.
    card.tabIndex = 0;
    card.append(el("span", "label", spec.label));

    const shown = el("span", "value", value === null ? "n/a" : value);
    if (value === null) shown.classList.add("na");
    card.append(shown);

    const hint = el("div", "hint");
    hint.append(el("span", "exact", spec.exact), el("span", "plain", spec.plain));
    card.append(hint);

    const meter = el("div", "meter");
    const fill = el("i");
    fill.style.width = Math.round(100 * Math.max(0, Math.min(1, spec.fill(row) ?? 0))) + "%";
    meter.append(fill);
    card.append(meter);
    cards.append(card);
  }
}

function renderTable(rows) {
  kindsTable.replaceChildren();
  const head = el("thead");
  const headRow = el("tr");
  for (const [name, , , hint] of COLUMNS) {
    const cell = el("th", null, name);
    cell.title = hint;
    headRow.append(cell);
  }
  head.append(headRow);

  const body = el("tbody");
  for (const row of rows) {
    const tr = el("tr");
    for (const [, read, withBar] of COLUMNS) {
      const value = read(row);
      const td = el("td");
      if (value === null) {
        td.append(el("span", "na", "n/a"));
      } else {
        if (withBar) {
          const bar = el("span", "bar");
          const fill = el("i");
          fill.style.width = Math.round(100 * (row.recall_at_5 ?? 0)) + "%";
          bar.append(fill);
          td.append(bar);
        }
        td.append(value);
      }
      tr.append(td);
    }
    body.append(tr);
  }
  kindsTable.append(head, body);
}

function outcomeOf(question) {
  if (!question.scored) return "none";
  if (question.hit_at_5) return "hit";
  return question.first_hit_rank === null ? "miss" : "deep";
}

function renderStrip(questions) {
  strip.replaceChildren();
  for (const question of questions) {
    const cell = el("li");
    cell.dataset.outcome = outcomeOf(question);
    cell.title =
      question.question_id +
      " · " + question.kind +
      (question.scored
        ? " · first hit at rank " + (question.first_hit_rank ?? "never")
        : " · no answer key") +
      " · " + Math.round(question.total_ms) + " ms";
    strip.append(cell);
  }

  legend.replaceChildren();
  for (const [outcome, text] of OUTCOMES) {
    const item = el("li");
    const swatch = el("span", "swatch");
    swatch.dataset.outcome = outcome;
    item.append(swatch, text);
    legend.append(item);
  }
  legend.hidden = false;
}

function showSuite() {
  if (!loadedRun) return;
  const suite = suitePicker.value;
  const rows = loadedRun.suites[suite] || [];
  const overall = rows[rows.length - 1];
  if (!overall) return;

  renderCards(overall);
  renderTable(rows);
  renderStrip(
    loadedRun.questions.filter((q) => suite === "all" || q.suite === suite),
  );
  tableHeading.hidden = false;
  kindsTable.hidden = false;
  stripHeading.hidden = false;

  evalNote.textContent =
    "Read from eval/runs/ on disk. Nothing on this page can start an evaluation — " +
    "that costs money and belongs at a terminal.";
  evalNote.hidden = false;
}

async function loadRun(runId) {
  setStatus(evalStatus, "Reading " + runId + "…");
  try {
    loadedRun = await getJSON("/runs/" + encodeURIComponent(runId));
    setStatus(evalStatus, "");

    suitePicker.replaceChildren();
    for (const suite of Object.keys(loadedRun.suites).sort()) {
      const option = el("option", null, suite === "all" ? "all questions" : suite + " only");
      option.value = suite;
      suitePicker.append(option);
    }
    suitePicker.value = loadedRun.suites.golden ? "golden" : "all";

    renderConditions(loadedRun.meta, loadedRun.questions.length);
    showSuite();
  } catch (error) {
    setStatus(evalStatus, "Could not read that run: " + error.message, "error");
  }
}

export async function listRuns() {
  if (runsListed) return;
  runsListed = true;
  setStatus(evalStatus, "Looking for saved runs…");
  try {
    const runs = await getJSON("/runs");
    if (runs.length === 0) {
      setStatus(evalStatus, "No runs on disk yet. `uv run eurohistory evaluate` writes one.", "refusal");
      return;
    }
    runPicker.replaceChildren();
    for (const run of runs) {
      const option = el(
        "option",
        null,
        run.run_id + "  ·  " + run.questions + " questions  ·  " + run.points.toLocaleString("en") + " chunks",
      );
      option.value = run.run_id;
      runPicker.append(option);
    }
    setStatus(evalStatus, "");
    await loadRun(runs[0].run_id);
  } catch (error) {
    runsListed = false;
    setStatus(evalStatus, "Could not list runs: " + error.message, "error");
  }
}

runPicker.addEventListener("change", () => loadRun(runPicker.value));
suitePicker.addEventListener("change", showSuite);

