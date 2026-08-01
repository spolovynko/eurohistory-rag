"""The Silver text pipeline: raw wikitext in, readable prose out.

Four steps in a fixed order, each owned by its own module. This file is the
only place that knows the order, so a new cleaning rule is added by writing a
module and adding one line here.
"""

import re
from dataclasses import dataclass

import mwparserfromhell

from eurohistory_rag.pipeline.silver.links import drop_non_article_links, link_targets
from eurohistory_rag.pipeline.silver.markup import drop_non_prose
from eurohistory_rag.pipeline.silver.templates import rescue_templates

# Wikitext is full of typographic spaces: &nbsp; between "World War" and "I",
# thin spaces inside numbers, the occasional zero-width. They look like spaces
# and are not, so a tokenizer treats "World War I" as a different string
# depending on which one was used. Flattened to a plain space.
_UNICODE_SPACES = re.compile(r"[\u00a0\u1680\u2000-\u200b\u202f\u205f\u3000]")
_TRAILING_SPACES = re.compile(r"[ \t]+$", re.MULTILINE)
_BLANK_RUNS = re.compile(r"\n{3,}")


@dataclass(frozen=True, slots=True)
class CleanedDocument:
    """One article's prose, and the articles it points at.

    Two fields because they have different destinations: `text` is chunked and
    embedded, `link_targets` is a keyword field that must never reach an
    embedding. See D-030.
    """

    text: str
    link_targets: tuple[str, ...]


def _normalise_whitespace(text: str) -> str:
    """Flatten exotic spaces, drop trailing ones, collapse blank-line runs."""
    text = _UNICODE_SPACES.sub(" ", text)
    text = _TRAILING_SPACES.sub("", text)
    return _BLANK_RUNS.sub("\n\n", text).strip()


def clean_wikitext(wikitext: str) -> CleanedDocument:
    """Turn one article's raw wikitext into the prose Silver stores.

    Pure: no I/O, no configuration, same input to same output. That is what
    makes the cleaning rules testable one at a time and Silver safe to delete
    and rebuild.
    """
    code = mwparserfromhell.parse(wikitext)
    rescue_templates(code)
    drop_non_prose(code)
    drop_non_article_links(code)
    return CleanedDocument(
        text=_normalise_whitespace(code.strip_code()),
        link_targets=tuple(link_targets(code)),
    )
