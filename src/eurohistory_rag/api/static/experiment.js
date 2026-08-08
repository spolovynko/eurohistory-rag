// --- the run button ---
//
// The one control on this page that spends money. Everything here exists to
// make that fact impossible to miss and impossible to trigger carelessly:
// the price is shown before the button is live, the preconditions are checked
// before the four minutes start, and the confirm stays disabled until a
// prediction has been typed.
//
// The prediction is the point. Phases 8 and 15 both recorded predictions that
// missed, and both were honest only because somebody chose to be. Here the
// interface holds the rule instead.

import { chosen, fillControls, options } from "./controls.js";
import { el, getJSON, setStatus } from "./dom.js";
import { refreshRuns } from "./evaluation.js";

const panel = document.getElementById("runner");
const prediction = document.getElementById("prediction");
const baselinePicker = document.getElementById("run-baseline");
const checkList = document.getElementById("run-checks");
const costLine = document.getElementById("run-cost");
const startButton = document.getElementById("run-start");
const cancelButton = document.getElementById("run-cancel");
const progress = document.getElementById("run-progress");
const bar = document.getElementById("run-bar");
const line = document.getElementById("run-line");
const verdict = document.getElementById("run-verdict");
const evalStatus = document.getElementById("eval-status");

const nodes = {
  model: document.getElementById("run-model"),
  reranker: document.getElementById("run-reranker"),
  hybrid: document.getElementById("run-hybrid"),
  k: document.getElementById("run-k"),
};

// Matches the server's floor. A one-word prediction satisfies "not empty" and
// predicts nothing, so the shortest thing that can carry a direction and a
// number is what both ends require.
const MIN_PREDICTION = 10;

// How often the page asks what the run is doing. Two seconds against a
// four-minute job: often enough that the bar never looks frozen, rare enough
// that a hundred and twenty status reads are not the load on the process.
const POLL_MS = 2000;

let plan = null;
let polling = null;

// A progress bar for a four-minute job is a decision about failure, not about
// reassurance. Nobody watches it for four minutes; they glance at it to find
// out whether the thing is dead. So it says which question, not a percentage
// alone, and it keeps saying it right up to the verdict.
function drawProgress(status) {
  const running = status.state === "running";
  progress.hidden = status.state === "idle";
  cancelButton.hidden = !running;
  startButton.disabled = running || !ready();

  const done = status.completed;
  bar.style.width =
    status.total ? Math.round((100 * done) / status.total) + "%" : "0%";

  if (running) {
    line.textContent =
      "Question " + done + " of " + status.total +
      (status.current ? " — " + status.current : "") +
      ".  Started " + status.started_at + ". Closing this page will not stop it.";
  } else if (status.state === "done") {
    line.textContent =
      "Finished. Wrote " + status.run_id + " after " + status.total + " questions.";
  } else if (status.state === "cancelled") {
    line.textContent =
      "Cancelled after " + done + " of " + status.total +
      " questions. No records were written, so this is not a run — only its " +
      "prediction is on disk.";
  } else if (status.state === "failed") {
    line.textContent = "The run failed: " + status.error;
  }

  if (status.gate_report) {
    verdict.textContent =
      (status.gate_passed ? "GATE PASSED" : "GATE FAILED") +
      " against " + status.baseline + "\n\n" + status.gate_report;
    verdict.hidden = false;
    verdict.dataset.passed = status.gate_passed ? "yes" : "no";
  }
}

function ready() {
  return Boolean(
    plan && plan.ready && prediction.value.trim().length >= MIN_PREDICTION,
  );
}

function refreshStart() {
  startButton.disabled = !ready();
}

function drawPlan(data) {
  plan = data;
  checkList.replaceChildren();
  for (const check of data.preconditions) {
    const item = el("li", null, check.name + " — " + check.detail);
    item.dataset.ok = check.ok ? "yes" : "no";
    checkList.append(item);
  }
  costLine.textContent =
    "About $" + data.dollars.toFixed(2) + " for " + data.questions +
    " questions, and about four minutes.  (" + data.basis + ")";
  refreshStart();
}

async function loadPlan() {
  try {
    drawPlan(await getJSON("/eval/plan?model=" + encodeURIComponent(nodes.model.value)));
  } catch (error) {
    costLine.textContent = "Could not price a run: " + error.message;
    plan = null;
    refreshStart();
  }
}

async function poll() {
  const status = await getJSON("/eval/run");
  drawProgress(status);
  if (status.state !== "running" && polling) {
    clearInterval(polling);
    polling = null;
    // The run list is stale the moment a run finishes, and the whole reason
    // for the button is to look at what it produced.
    if (status.state === "done") await refreshRuns();
  }
}

function watch() {
  if (!polling) polling = setInterval(() => poll().catch(() => {}), POLL_MS);
}

async function start() {
  startButton.disabled = true;
  setStatus(evalStatus, "");
  verdict.hidden = true;

  const response = await fetch("/eval/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      prediction: prediction.value.trim(),
      // Echoed back from the quote. If the question file changed since the
      // price was shown, the server refuses rather than spending a different
      // amount than the one that was agreed to.
      questions: plan.questions,
      baseline: baselinePicker.value || null,
      ...chosen(nodes),
    }),
  });

  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    setStatus(evalStatus, detail.detail || "Could not start the run.", "error");
    refreshStart();
    return;
  }
  drawProgress(await response.json());
  watch();
}

async function loadBaselines() {
  const runs = await getJSON("/runs");
  baselinePicker.replaceChildren();
  const none = el("option", null, "nothing — do not gate this run");
  none.value = "";
  baselinePicker.append(none);
  for (const run of runs) {
    const option = el("option", null, run.run_id + "  ·  " + run.questions + " questions");
    option.value = run.run_id;
    baselinePicker.append(option);
  }
  // The newest run, because a phase is nearly always compared with the one
  // before it and choosing that by hand every time is a step that gets skipped.
  if (runs.length) baselinePicker.value = runs[0].run_id;
}

export async function openRunner() {
  const opts = await options();
  fillControls(nodes, opts);
  await Promise.all([loadBaselines(), loadPlan()]);
  // Asked once on open, so a run started in another tab -- or before this page
  // was reloaded -- shows up here rather than looking like nothing happened.
  const status = await getJSON("/eval/run");
  drawProgress(status);
  if (status.state === "running") {
    panel.open = true;
    watch();
  }
}

prediction.addEventListener("input", refreshStart);
nodes.model.addEventListener("change", loadPlan);
startButton.addEventListener("click", () => {
  start().catch((error) =>
    setStatus(evalStatus, "Could not start the run: " + error.message, "error"),
  );
});
cancelButton.addEventListener("click", async () => {
  cancelButton.disabled = true;
  try {
    drawProgress(await (await fetch("/eval/run", { method: "DELETE" })).json());
  } finally {
    cancelButton.disabled = false;
  }
});
