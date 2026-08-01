"""Wikitext in, readable prose out.

A pipeline: four steps in a fixed order, every one applied to every input.
Each step only ever removes or replaces markup, so the order is the only
coupling between them, and this file is the only place that knows it.

The rules themselves are decisions, recorded as D-027 (templates), D-029
(footnotes and tables) and D-030 (wikilinks).
"""

import re
from dataclasses import dataclass

import mwparserfromhell
from mwparserfromhell.nodes import Template
from mwparserfromhell.wikicode import Wikicode

from eurohistory_rag.pipeline.wikitext import normalise_target

_WHITESPACE = re.compile(r"\s+")
_UNICODE_SPACES = re.compile(r"[\u00a0\u1680\u2000-\u200b\u202f\u205f\u3000]")
_TRAILING_SPACES = re.compile(r"[ \t]+$", re.MULTILINE)
_BLANK_RUNS = re.compile(r"\n{3,}")


# --- step 1: templates -----------------------------------------------------
#
# 676 distinct template names appear in a 9% sample of Bronze, so a deny-list
# is unmaintainable. The rule points the other way: a template is deleted
# unless it is named here. Two lists, because kept templates come in two
# shapes -- text in a known position, or a wrapper whose every positional
# parameter is content.

KEEP: dict[str, tuple[int, ...]] = {
    "lang": (2,),  # {{lang|de|Reichstag}} -> Reichstag
    "convert": (1, 2),  # {{convert|50|km}}     -> 50 km
    "flag": (1,),  # {{flag|France}}       -> France
    "flagcountry": (1,),
}

# The date entries are here because they were the biggest hole in the first
# version: {{start date and age|28 June 1919}} was deleted, and with it the
# signing date of the Treaty of Versailles.
KEEP_ALL = frozenset(
    {
        "birth date",
        "birth date and age",
        "death date",
        "death date and age",
        "start date",
        "start date and age",
        "end date",
        "end date and age",
        "dts",
        "plainlist",
        "ubl",
        "unbulleted list",
        "hlist",
        "collapsible list",
        "native name",
        "nowrap",
        "nobold",
        "small",
    }
)


def _flatten(template: Template) -> str | None:
    """The prose a kept template stands for, or None if it is not kept.

    None and "" mean different things: None is "not on either list, leave it
    for strip_code", "" is "kept but its parameters were empty".
    """
    name = _WHITESPACE.sub(" ", str(template.name).strip().lower())

    if name in KEEP_ALL:
        return " ".join(
            str(param.value).strip()
            for param in template.params
            if param.showkey is False and str(param.value).strip()
        )

    positions = KEEP.get(name)
    if positions is None:
        return None
    return " ".join(
        str(template.get(i).value).strip() for i in positions if template.has(i)
    )


def rescue_templates(code: Wikicode) -> None:
    """Put back the text of allow-listed templates; leave the rest to be stripped.

    This step only ever adds text, so a mistake in KEEP can lose a word but can
    never leak citation parameters into the prose.
    """
    # Innermost first. filter_templates() yields an outer template before the
    # ones nested inside it, and replacing the outer one re-parses its text --
    # which resurrects an inner {{lang}} as a fresh node this loop has already
    # passed, so it never gets rescued and strip_code eats it.
    for template in reversed(code.filter_templates()):
        text = _flatten(template)
        if text is not None:
            code.replace(template, text)


# --- step 2: footnotes and tables ------------------------------------------

# Removed with their contents. Everything else -- <i>, <b>, <li>, <small> --
# wraps text that reads fine once the tag itself is stripped.
DROP_TAGS = frozenset({"ref", "table"})


def drop_non_prose(code: Wikicode) -> None:
    """Delete footnotes and tables, contents included.

    strip_code() keeps what is inside a <ref>, which would drop a book citation
    into the middle of the sentence that cited it. A flattened table keeps its
    numbers and loses the headers that gave them meaning. Neither reads as
    prose, and prose is all Silver is for.
    """
    # Innermost first, so a <ref> inside a table is gone before the table is
    # removed out from under it.
    for tag in reversed(code.filter_tags()):
        if str(tag.tag).strip().lower() in DROP_TAGS:
            code.remove(tag)


# --- step 3: wikilinks -----------------------------------------------------


def drop_non_article_links(code: Wikicode) -> None:
    """Delete File, Image and Category links, image captions included.

    Article links are left alone: stripping turns them into their display text,
    which is what a reader sees. Without this step strip_code() would emit
    `thumb|right|250px|The signing in 1919` verbatim.
    """
    for link in reversed(code.filter_wikilinks()):
        if normalise_target(str(link.title)) is None:
            code.remove(link)


def link_targets(code: Wikicode) -> list[str]:
    """The distinct articles this text links to, sorted.

    Never prose, so it never enters chunk text. A target is an editor asserting
    that this text is about that entity, which makes it a keyword field for
    hybrid search and a facet for metadata filtering.
    """
    return sorted(
        {
            target
            for link in code.filter_wikilinks()
            if (target := normalise_target(str(link.title))) is not None
        }
    )


# --- step 4: whitespace, and the pipeline itself ---------------------------


@dataclass(frozen=True, slots=True)
class CleanedDocument:
    """Prose, and the articles it points at.

    Two fields because they have different destinations: `text` is chunked and
    embedded, `link_targets` is a keyword field that must never reach an
    embedding.
    """

    text: str
    link_targets: tuple[str, ...]


def _normalise_whitespace(text: str) -> str:
    """Flatten exotic spaces, drop trailing ones, collapse blank-line runs.

    Wikitext is full of typographic spaces -- &nbsp; between "World War" and
    "I", thin spaces inside numbers. They look like spaces and are not, so a
    tokenizer sees a different string depending on which one was used.
    """
    text = _UNICODE_SPACES.sub(" ", text)
    text = _TRAILING_SPACES.sub("", text)
    return _BLANK_RUNS.sub("\n\n", text).strip()


def clean_wikitext(wikitext: str) -> CleanedDocument:
    """Turn one piece of wikitext into the prose Silver stores.

    Pure: no I/O, no configuration, same input to same output. That is what
    makes the rules testable one at a time and Silver safe to delete and
    rebuild.
    """
    code = mwparserfromhell.parse(wikitext)
    rescue_templates(code)
    drop_non_prose(code)
    drop_non_article_links(code)
    return CleanedDocument(
        text=_normalise_whitespace(code.strip_code()),
        link_targets=tuple(link_targets(code)),
    )
