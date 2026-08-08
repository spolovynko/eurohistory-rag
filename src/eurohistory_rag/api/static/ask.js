// --- the ask view ---
//
// Owns the question box, the settings row, the answer and its sources.
// Imported for its side effects: it wires its own listeners on load.

import { chosen, fillControls, options } from "./controls.js";
import { el, setStatus } from "./dom.js";

const form = document.getElementById("ask");
const box = document.getElementById("question");
const submit = document.getElementById("submit");
const statusLine = document.getElementById("status");
const answerBox = document.getElementById("answer");
const sourcesHeading = document.getElementById("sources-heading");
const sourceList = document.getElementById("sources");
const footer = document.getElementById("footer");

// The controls describe what /ask will be asked for. Read from the server so
// the page cannot offer a model the server would refuse.
const nodes = {
  model: document.getElementById("model-picker"),
  reranker: document.getElementById("reranker-picker"),
  hybrid: document.getElementById("hybrid-toggle"),
  k: document.getElementById("k-picker"),
};

const MARKER = /\[(\d+)\]/g;
const HUES = 6;

// Which of the six hues a citation wears. k is 5, so in practice n never wraps;
// the modulo is there so a larger k cannot produce a colourless card.
function hue(n) {
  return String(((n - 1) % HUES) + 1);
}

function clearAnswer() {
  answerBox.replaceChildren();
  sourceList.replaceChildren();
  sourcesHeading.hidden = true;
  footer.hidden = true;
}

function renderAnswer(text, cited) {
  let at = 0;
  for (const match of text.matchAll(MARKER)) {
    answerBox.append(text.slice(at, match.index));
    const n = Number(match[1]);
    if (cited.has(n)) {
      const link = el("a", null, match[1]);
      link.href = "#source-" + n;
      link.dataset.hue = hue(n);
      link.title = "Jump to source " + n;
      answerBox.append(link);
    } else {
      // A marker with no source behind it stays visible as plain text rather
      // than becoming a link to nowhere.
      answerBox.append(match[0]);
    }
    at = match.index + match[0].length;
  }
  answerBox.append(text.slice(at));
}

function renderSource(source) {
  const item = el("li");
  item.id = "source-" + source.n;
  item.dataset.hue = hue(source.n);

  const line = el("p", "cite");
  const marker = el("span", "n", String(source.n));

  const link = el("a", null, source.source);
  link.href = source.url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.title = "Wikipedia, at the revision this corpus indexed";

  line.append(marker, link, el("span", "score", source.score.toFixed(3)));

  const fold = el("details");
  fold.append(
    el("summary", null, "the passage the model was given"),
    el("blockquote", null, source.text),
  );

  item.append(line, fold);
  sourceList.append(item);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = box.value.trim();
  if (!question) return;

  clearAnswer();
  submit.disabled = true;
  const started = performance.now();
  setStatus(statusLine, "Searching the corpus and writing an answer… a few seconds.");

  try {
    const response = await fetch("/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: question, ...chosen(nodes) }),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      const error = new Error(detail.detail || "Request failed.");
      error.status = response.status;
      throw error;
    }
    const data = await response.json();
    const seconds = ((performance.now() - started) / 1000).toFixed(1);

    if (data.sources.length === 0) {
      // Not an error. The corpus was asked and had nothing, which is the
      // behaviour Phase 6 built on purpose.
      setStatus(statusLine, "No source in the corpus covers this. The answer below is a refusal, not a failure.", "refusal");
    } else {
      setStatus(statusLine, "");
    }

    renderAnswer(data.answer, new Set(data.sources.map((s) => s.n)));
    // /ask returns sources in the order the answer first mentions them, so a
    // list can read 5, 2, 3, 4. Numbered things are looked up by their number.
    for (const source of [...data.sources].sort((a, b) => a.n - b.n)) {
      renderSource(source);
    }
    sourcesHeading.hidden = data.sources.length === 0;

    // What produced this answer, stated on the answer. Phase 8 shipped a
    // measurement whose reranker was off and nobody noticed.
    const used = data.configuration;
    footer.textContent = [
      used.model,
      "reranker " + (used.reranker ? used.reranker.split("/").pop() : "off"),
      "hybrid " + (used.hybrid ? "on" : "off"),
      "k " + used.k,
      seconds + " s",
      data.license,
    ].join("  ·  ");
    footer.hidden = false;
  } catch (error) {
    setStatus(
      statusLine,
      error.status === 503
        ? "The system is unreachable — the search index or the model is down. Nothing was asked of the corpus. Try again shortly."
        : "Something went wrong talking to the server: " + error.message,
      "error",
    );
  } finally {
    submit.disabled = false;
  }
});


options()
  .then((opts) => fillControls(nodes, opts))
  .catch((error) => {
    // The controls are useless if the server never said what it accepts, and
    // a silently-empty dropdown is worse than a stated failure.
    setStatus(
      statusLine,
      "Could not read this server's settings: " + error.message,
      "error",
    );
  });
