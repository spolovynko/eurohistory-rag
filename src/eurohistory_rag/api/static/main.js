// --- routing, and the entry point ---
//
// The two views are real links rather than buttons, so a view can be linked
// to and the back button works. #source-N stays on the ask view.

import "./ask.js";
import { listRuns } from "./evaluation.js";

function route() {
  const wantsEval = location.hash.startsWith("#eval");
  document.body.dataset.view = wantsEval ? "eval" : "ask";
  document.getElementById("view-ask").hidden = wantsEval;
  document.getElementById("view-eval").hidden = !wantsEval;
  document.getElementById("tab-ask").setAttribute("aria-current", wantsEval ? "false" : "page");
  document.getElementById("tab-eval").setAttribute("aria-current", wantsEval ? "page" : "false");
  if (wantsEval) listRuns();
}

window.addEventListener("hashchange", route);
route();
