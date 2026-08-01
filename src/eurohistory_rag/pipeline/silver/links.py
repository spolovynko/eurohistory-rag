"""Wikilinks: keep what the reader sees, record what the document points at.

Two jobs that look like one. The prose keeps a link's display text and loses
its target -- `[[Treaty of Versailles|the treaty]]` becomes "the treaty", which
reads correctly and is unfindable by a keyword search for Versailles. The
targets are therefore kept separately, out of the prose, where Phase 8 can use
them without an embedding ever seeing them. See D-030.
"""

from mwparserfromhell.wikicode import Wikicode

from eurohistory_rag.pipeline.wikitext import normalise_target


def drop_non_article_links(code: Wikicode) -> None:
    """Delete links that are not to articles: File, Image, Category and friends.

    Mutates `code`. Image captions go with them -- the image is not in the
    corpus, so a caption left in the prose describes something the reader
    cannot see. strip_code() would otherwise emit `thumb|right|250px|...`
    verbatim, which is the reason this cannot simply be left alone.
    """
    for link in reversed(code.filter_wikilinks()):
        if normalise_target(str(link.title)) is None:
            code.remove(link)


def link_targets(code: Wikicode) -> list[str]:
    """The distinct articles this document links to, sorted.

    Not prose, so it never enters chunk text: a target is an editor's assertion
    that this document is about that entity, which makes it a keyword field for
    hybrid search and a facet for metadata filtering. Call after
    drop_non_article_links, so the list describes the text that survived.
    """
    return sorted(
        {
            target
            for link in code.filter_wikilinks()
            if (target := normalise_target(str(link.title))) is not None
        }
    )
