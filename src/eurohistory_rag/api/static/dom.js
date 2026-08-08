// Shared DOM helpers. Nothing here knows about a view.
//
// Everything is built as elements and text nodes. The corpus is other
// people's text; text that becomes markup becomes something the browser
// will run.

export function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export async function getJSON(url) {
  const response = await fetch(url);
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    const error = new Error(detail.detail || "Request failed.");
    error.status = response.status;
    throw error;
  }
  return response.json();
}

// Which line of status a view is showing, and in what register: the pending
// pulse, a refusal, or a failure. Shared because both views have one.
export function setStatus(node, text, kind) {
  node.textContent = text;
  node.hidden = !text;
  if (kind) node.dataset.kind = kind;
  else delete node.dataset.kind;
}
