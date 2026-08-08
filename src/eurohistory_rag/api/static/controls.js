// --- the settings row, wherever it appears ---
//
// Two views now carry the same four knobs: the ask view, where they change one
// answer, and the evaluation view, where they change what an experiment
// measures. The lists behind them are the same lists, and they must stay the
// same -- a page offering k=15 in one place and k=10 in the other would be two
// different claims about what this server accepts.
//
// This is the kind of duplication worth removing: not code that happens to look
// alike, but knowledge that has to change together.

import { el, getJSON } from "./dom.js";

// How many passages the model is shown. A short list rather than a free number:
// the ceiling is 50, and a page offering 50 invites someone to pay for fifty
// chunks of prompt to answer a one-line question. Phase 6 measured what k
// costs on money, latency and quality, and the third is not linear.
const K_CHOICES = [3, 5, 8, 10, 15];

// Phase 8 measured this one ranking "Treaty of Rome" above East German
// emigration for a Berlin Wall question, and gave two unrelated documents an
// identical 0.000. It stays on the menu because it is the value in config.py,
// so hiding it would make the default unreproducible -- but nobody should pick
// it without being told.
const BROKEN_RERANKER = "BAAI/bge-reranker-base";

const BROKEN_NOTE =
  "Phase 8 measured this model ranking unrelated passages above correct ones. " +
  "Kept because it is the default in config.py.";

let cached = null;

// Asked for once per page load. Both views want the same answer and the server
// gives the same one; two requests would only be two chances to disagree.
export async function options() {
  if (!cached) cached = await getJSON("/options");
  return cached;
}

// Fill one set of four controls from what the server said it accepts.
export function fillControls(nodes, opts) {
  const { model, reranker, hybrid, k } = nodes;

  model.replaceChildren();
  for (const name of opts.models) {
    const choice = el("option", null, name);
    choice.value = name;
    model.append(choice);
  }
  model.value = opts.defaults.model;

  reranker.replaceChildren();
  const off = el("option", null, "off");
  off.value = "";
  reranker.append(off);
  for (const name of opts.rerankers) {
    const short = name.split("/").pop();
    const broken = name === BROKEN_RERANKER;
    const choice = el("option", null, broken ? short + "  ⚠ measured broken" : short);
    choice.value = name;
    choice.title = broken ? BROKEN_NOTE : name;
    reranker.append(choice);
  }
  reranker.value = opts.defaults.reranker || "";

  hybrid.checked = opts.defaults.hybrid;

  k.replaceChildren();
  for (const value of K_CHOICES.filter((choice) => choice <= opts.max_k)) {
    const choice = el("option", null, String(value));
    choice.value = String(value);
    k.append(choice);
  }
  k.value = String(opts.defaults.k);
}

// What those four controls currently say, in the shape both /ask and
// /eval/run take. "" on the reranker means switch it off; null would mean
// "leave the server's default alone", and those are different requests.
export function chosen(nodes) {
  return {
    model: nodes.model.value,
    reranker: nodes.reranker.value,
    hybrid: nodes.hybrid.checked,
    k: Number(nodes.k.value),
  };
}
