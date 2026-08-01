"""Split an article into the rows Silver stores: one per level-2 section.

A section is the unit because it is where a topic starts and stops. Chunking a
whole article produces chunks that straddle two subjects and answer neither,
and a citation to an 87,000-character article is not a citation. See D-030.

This module is also where a section is judged worth keeping at all -- by its
heading, then by its length. See D-034.
"""

from dataclasses import dataclass

import mwparserfromhell

from eurohistory_rag.pipeline.silver.clean import clean_wikitext

# Apparatus, not content. Present in nearly every article and near-empty once
# refs are gone. The variants are here because matching is exact: "Notes and
# references" survived the first version of this list and reached Silver as
# the two words "Notes References".
DROP_HEADINGS = frozenset(
    {
        "references",
        "references and notes",
        "references and sources",
        "notes",
        "notes and references",
        "notes and citations",
        "explanatory notes",
        "footnotes",
        "citations",
        "citations and notes",
        "sources",
        "sources and references",
        "general references",
        "works cited",
        "bibliography",
        "further reading",
        "see also",
        "external links",
        "external link",
    }
)

# Below this, what survives cleaning is not a claim. Measured: sections under
# 200 characters are almost all leftover subheadings from a table that was
# deleted -- "German honours / Foreign honours" -- while the shortest sections
# above it are real, if brief. See D-034.
MIN_SECTION_CHARS = 200


@dataclass(frozen=True, slots=True)
class Section:
    """One section of one article: the text, where it sits, what it points at.

    `heading` is empty for the lead -- the summary paragraphs before the first
    heading. That is also how the lead is identified; it needs no flag of its
    own. `position` is the order among sections that survived filtering.
    """

    position: int
    heading: str
    text: str
    link_targets: tuple[str, ...]


def split_sections(
    wikitext: str, *, min_chars: int = MIN_SECTION_CHARS
) -> list[Section]:
    """Split one article into cleaned sections worth keeping.

    Splits at level 2 only. Deeper headings stay inside their parent section as
    plain lines, which keeps the row count sane and leaves the fine-grained
    splitting to Phase 4 where it belongs.
    """
    sections: list[Section] = []

    for raw in mwparserfromhell.parse(wikitext).get_sections(
        levels=[2], include_lead=True
    ):
        node = mwparserfromhell.parse(str(raw))
        headings = node.filter_headings()

        heading = ""
        if headings and headings[0].level == 2:
            # The heading is a column, so it does not also belong in the body.
            heading = str(headings[0].title.strip_code()).strip()
            node.remove(headings[0])

        if heading.lower() in DROP_HEADINGS:
            continue

        cleaned = clean_wikitext(str(node))
        if len(cleaned.text) < min_chars:
            continue

        sections.append(
            Section(
                position=len(sections),
                heading=heading,
                text=cleaned.text,
                link_targets=cleaned.link_targets,
            )
        )

    return sections
