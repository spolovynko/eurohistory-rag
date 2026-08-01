"""Markup that is not prose: footnotes and tables.

Both survive strip_code(), and both survive it badly. A <ref>'s contents land
in the middle of the sentence that cited them; a table flattens into loose
fragments with the columns that gave them meaning gone. Silver exists to
produce prose, so neither is worth keeping. See D-029.
"""

from mwparserfromhell.wikicode import Wikicode

# Removed with their contents. Everything else -- <i>, <b>, <li>, <small> --
# wraps text that reads fine once the tag itself is stripped.
DROP_TAGS = frozenset({"ref", "table"})


def drop_non_prose(code: Wikicode) -> None:
    """Delete footnotes and tables from an article, contents included.

    Mutates `code`. Measured over the full corpus: 59.6 M chars to 41.9 M,
    so this is the single largest cut Silver makes.
    """
    # Innermost first, so a <ref> inside a table is gone before the table is
    # removed out from under it.
    for tag in reversed(code.filter_tags()):
        if str(tag.tag).strip().lower() in DROP_TAGS:
            code.remove(tag)
