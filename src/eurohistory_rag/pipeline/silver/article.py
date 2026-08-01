"""What the whole article says about itself, before it is cut up.

Three questions asked of an article as a whole: is it content at all, what
kind of thing is it, and what topics did editors file it under. All three are
answered from the raw wikitext, because the cleaning pipeline deletes the
evidence -- an infobox is a template and a category is a link, and both of
those are things `clean.py` removes.

Decisions: D-031 (infobox), D-032 (categories), D-033 (non-content).
"""

import re
from dataclasses import dataclass

import mwparserfromhell

from eurohistory_rag.pipeline.silver.clean import clean_wikitext

_WHITESPACE = re.compile(r"\s+")
# Editors leave notes inside the template name itself:
# `{{Infobox settlement<!-- see template:infobox settlement -->`. Six articles
# in this corpus do it, and without this the note becomes part of the type.
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def _template_name(raw: str) -> str:
    """A template's name, comments and stray whitespace removed, lowercased."""
    return _WHITESPACE.sub(" ", _HTML_COMMENT.sub("", raw).strip().lower())


# --- is this an article at all? --------------------------------------------

# A page whose job is to point at other pages. It has no subject of its own, so
# a chunk from it is a list of names with no claim in it.
_TITLE_PREFIXES = (
    "list of",
    "lists of",
    "outline of",
    "index of",
    "timeline of",
    "glossary of",
    "bibliography of",
)

# A disambiguation page is a menu, not an article.
_DISAMBIGUATION_TEMPLATES = frozenset(
    {"disambiguation", "disambig", "dab", "hndis", "geodis", "numberdis"}
)


def is_non_content(title: str, wikitext: str) -> bool:
    """True if this article should be dropped before it is ever split.

    Judged on the title and the markup, never on length -- a short article
    about a real subject is content, and the five stub-tagged articles in this
    corpus are kept for exactly that reason.

    Removes 0 of the current 664: wikilink curation and the hand-trim already
    kept them out. It exists for the theme expansion before Phase 5, when
    `curate` re-runs over 8-12 themes and the candidate list gets longer than
    one person reviews carefully.
    """
    lowered = title.strip().lower()
    if lowered.startswith(_TITLE_PREFIXES):
        return True
    if "(disambiguation)" in lowered:
        return True

    # A redirect has no body at all; the API resolves them, so this is a guard
    # against one that slipped through rather than an expected case.
    if wikitext.lstrip().lower().startswith("#redirect"):
        return True

    return any(
        str(template.name).strip().lower() in _DISAMBIGUATION_TEMPLATES
        for template in mwparserfromhell.parse(wikitext).filter_templates()
    )


# --- the infobox -----------------------------------------------------------

# Presentational: filenames, sizes, map pins, coordinates. They are the most
# common fields in the corpus and none of them is a fact about the subject.
SKIP_FIELDS = (
    "image",
    "caption",
    "coordinates",
    "flag",
    "map",
    "logo",
    "alt",
    "width",
    "size",
    "border",
    "pushpin",
    "photo",
    "signature",
    "seal",
    "blank",
    "module",
)


@dataclass(frozen=True, slots=True)
class Infobox:
    """One article's infobox: its type, and its surviving fields.

    `type` is the template name with "infobox" removed -- "treaty", "military
    conflict", "officeholder". It is the single most useful facet in the box,
    because it says what kind of thing the article is about.
    """

    type: str
    fields: dict[str, str]


def extract_infobox(wikitext: str) -> Infobox | None:
    """The first infobox in an article, cleaned, or None if it has none.

    Kept as a type plus a plain key-value map rather than typed columns: 77
    infobox types appear in this corpus and they share almost no field names,
    so normalising "when did this start" across all of them is real work with
    no evidence yet that any query needs it. 77% of articles have one.

    The first box only. A handful of articles carry several -- a country with
    an infobox per era -- and the first is the one at the top of the page.
    """
    for template in mwparserfromhell.parse(wikitext).filter_templates():
        name = _template_name(str(template.name))
        if not name.startswith("infobox"):
            continue

        fields: dict[str, str] = {}
        for param in template.params:
            key = _template_name(str(param.name))
            if key.startswith(SKIP_FIELDS):
                continue
            # Values are wikitext too -- {{start date|...}}, refs, links -- so
            # they go through the same cleaning as the prose, then onto one line.
            value = _WHITESPACE.sub(" ", clean_wikitext(str(param.value)).text).strip()
            if value:
                fields[key] = value

        return Infobox(
            type=name.removeprefix("infobox").strip() or "unknown", fields=fields
        )

    return None


# --- the categories --------------------------------------------------------

_CATEGORY_PREFIX = "category:"


def extract_categories(wikitext: str) -> tuple[str, ...]:
    """The categories one article declares, sorted and deduplicated.

    The only metadata in this corpus assigned deliberately by a person, which
    is what makes it the best candidate for Phase 14's filters. Median 11 per
    article, 6,585 distinct across 664 articles.

    No noise filter, deliberately: maintenance categories such as "Articles
    containing video clips" are added by templates, and templates are never
    expanded here, so they do not appear. Measured, 2 of 6,585.
    """
    names: set[str] = set()
    for link in mwparserfromhell.parse(wikitext).filter_wikilinks():
        title = str(link.title).strip().lstrip(":")
        if title.lower().startswith(_CATEGORY_PREFIX):
            name = title[len(_CATEGORY_PREFIX) :].strip().replace("_", " ")
            if name:
                names.add(name)
    return tuple(sorted(names))
