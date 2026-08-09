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
const thread = document.getElementById("thread");
const newChat = document.getElementById("new-chat");
const rewrittenLine = document.getElementById("rewritten");
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

// --- the conversation -------------------------------------------------------
//
// The thread lives here, in the page, and is sent back with every question.
// The server keeps nothing: this tab already holds what it is displaying, and a
// server-side copy would need session ids and eviction in a system with no
// authentication in it anywhere. D-098.

// How many completed exchanges travel with a question. The rewriter reads the
// last two; sending a few more costs a few hundred bytes and means the cap is
// the server's decision rather than this file's.
const HISTORY_SENT = 6;

let history = [];
// The exchange currently on screen, waiting to be pushed up into the thread
// when the next question is asked. Null before the first answer.
let onScreen = null;

function archive() {
  if (!onScreen) return;
  const turn = el("article", "turn");
  turn.append(el("p", "asked", onScreen.question));
  if (onScreen.standalone) {
    turn.append(el("p", "rewritten", "understood as: " + onScreen.standalone));
  }
  turn.append(el("div", "said", onScreen.answer));
  thread.append(turn);
  onScreen = null;
  newChat.hidden = false;
}

newChat.addEventListener("click", () => {
  history = [];
  onScreen = null;
  thread.replaceChildren();
  newChat.hidden = true;
  clearAnswer();
  setStatus(statusLine, "");
  box.focus();
});

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
  rewrittenLine.hidden = true;
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

// Read a server-sent event stream and hand each event to `handle`.
//
// Hand-parsed rather than via EventSource, which only does GET and a question
// has no business in a URL. The format is small enough to be worth the twenty
// lines: events are separated by a blank line, and each is a named kind and one
// line of JSON.
async function readEvents(body, handle) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let split;
    while ((split = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, split);
      buffer = buffer.slice(split + 2);
      const name = block.match(/^event: (.*)$/m);
      const data = block.match(/^data: (.*)$/m);
      if (name && data) handle(name[1], JSON.parse(data[1]));
    }
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = box.value.trim();
  if (!question) return;

  // Emptied here rather than left for editing. On a one-shot page keeping the
  // question was convenient; with a thread it means the next question is typed
  // onto the end of the last one, which is what happened the first time this
  // was tried in a browser.
  box.value = "";
  archive();
  clearAnswer();
  submit.disabled = true;
  const started = performance.now();
  let firstWordAt = null;
  // When the passages landed. Its own clock because it is a different question
  // from "when did the answer start": retrieval finishing late and the model
  // starting late are different faults, and until Phase 25 the page reported
  // only the second one.
  let sourcesAt = null;
  setStatus(statusLine, "Searching the corpus…");

  try {
    const response = await fetch("/ask", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        // The one line that chooses the streamed shape of the same endpoint.
        Accept: "text/event-stream",
      },
      body: JSON.stringify({
        question: question,
        history: history.slice(-HISTORY_SENT),
        ...chosen(nodes),
      }),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      const error = new Error(detail.detail || "Request failed.");
      error.status = response.status;
      throw error;
    }

    let text = "";
    let failed = false;

    await readEvents(response.body, (name, data) => {
      if (name === "sources") {
        sourcesAt = performance.now();
        // Retrieval is done and generation has not started. These are the
        // passages the model is being shown, numbered as it sees them, and
        // they are on screen roughly three seconds before the answer is.
        sourcesHeading.textContent = "Passages found";
        sourcesHeading.hidden = data.length === 0;
        data.forEach((hit, index) => renderSource({ ...hit, n: index + 1 }));
        setStatus(statusLine, "Writing the answer…");
        return;
      }
      if (name === "token") {
        if (firstWordAt === null) {
          firstWordAt = performance.now();
          setStatus(statusLine, "");
        }
        text += data;
        // Plain text while it arrives. A [1] cannot become a link until the
        // answer is finished, because until then nobody knows which markers
        // the model kept.
        answerBox.textContent = text;
        return;
      }
      if (name === "error") {
        // The 200 went out with the first byte, so this is the only way a
        // failure can reach the page. It must not look like a short answer.
        failed = true;
        clearAnswer();
        setStatus(statusLine, data, "error");
        return;
      }
      if (name === "done") finish(data, started, sourcesAt, firstWordAt, question);
    });

    if (!failed && firstWordAt === null) {
      setStatus(statusLine, "The model sent nothing back.", "error");
    }
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

// The end of a stream: markers become links, the passages the answer ignored
// come off the list, and the two clocks are reported.
function finish(data, started, sourcesAt, firstWordAt, question) {
  const cited = new Set(data.sources.map((s) => s.n));
  answerBox.replaceChildren();
  renderAnswer(data.answer, cited);

  // Only when the conversation changed the question. A reader who sees the
  // wrong subject here knows immediately why the answer is about the wrong
  // thing, which is the one failure this change can introduce.
  rewrittenLine.textContent = "understood as: " + data.standalone;
  rewrittenLine.hidden = !data.standalone;

  history.push({ user: question, assistant: data.answer });
  onScreen = { question: question, answer: data.answer, standalone: data.standalone };

  for (const item of [...sourceList.children]) {
    if (!cited.has(Number(item.id.replace("source-", "")))) item.remove();
  }
  sourcesHeading.textContent = "Sources";
  sourcesHeading.hidden = cited.size === 0;

  if (cited.size === 0) {
    // Not an error. The corpus was asked and had nothing, which is the
    // behaviour Phase 6 built on purpose.
    setStatus(statusLine, "No source in the corpus covers this. The answer above is a refusal, not a failure.", "refusal");
  }

  // What produced this answer, stated on the answer, and what it cost in the
  // three numbers a reader feels: when the passages appeared, when the words
  // started, and when they stopped. Phase 8 shipped a measurement whose
  // reranker was off unnoticed.
  const used = data.configuration;
  const total = (performance.now() - started) / 1000;
  footer.textContent = [
    used.model,
    "reranker " + (used.reranker ? used.reranker.split("/").pop() : "off"),
    "hybrid " + (used.hybrid ? "on" : "off"),
    "k " + used.k,
    "passages " + ((sourcesAt - started) / 1000).toFixed(1) + " s",
    "first word " + ((firstWordAt - started) / 1000).toFixed(1) + " s",
    "done " + total.toFixed(1) + " s",
    data.license,
  ].join("  ·  ");
  footer.hidden = false;
}


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
