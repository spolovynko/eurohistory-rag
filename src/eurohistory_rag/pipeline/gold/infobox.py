"""The article's infobox, turned into something retrieval can return.

Silver keeps every infobox field (D-031) and Gold has always dropped them
(D-041), so a figure Wikipedia states only in the box -- an area, the date a
treaty entered into force, a casualty total -- exists in this system and cannot
be retrieved. 715 such figures were counted before this module was written.

This is the whole fix: one extra chunk per article, holding the box as text, in
the same pool as everything else. There is no separate store and no router --
see D-097 for why the obvious structured-lookup design was turned down.
"""

from collections.abc import Iterator

from eurohistory_rag.pipeline.gold.store import Chunk
from eurohistory_rag.pipeline.silver.store import SilverRow

# What the chunk announces itself as. The same shape as the prose prefix from
# D-040 -- "{title} -- {heading}" -- because the reader of an answer sees this
# string as the source name and should not have to learn a second format.
HEADING = "Infobox"


def _lines(row: SilverRow) -> Iterator[str]:
    """Each surviving field as `key: value`, in the order the editor wrote it.

    Order is left alone deliberately. A box is written top-down with the
    identifying fields first, and reordering it by any rule we invented would
    put our judgement of what matters ahead of the article's.
    """
    for key, value in row.infobox:
        yield f"{key}: {value}"


def infobox_chunks(row: SilverRow, size: int) -> list[Chunk]:
    """The article's infobox as one or more chunks, or nothing if it has none.

    Split at field boundaries when the box is longer than one chunk, which 361
    of the 988 boxes in this corpus are -- a country box runs to 4,939
    characters. Truncating instead would drop facts, and dropping facts is the
    defect this module exists to repair.

    `row` is the article's first Silver row, so `doc_id` is its lead section:
    the box sits at the top of the page and an answer citing it should point
    there. No period is set, so Phase 22's temporal arm never returns one.
    """
    if not row.infobox:
        return []

    prefix = f"{row.title} -- {HEADING}\n\n"
    chunks: list[Chunk] = []
    batch: list[str] = []
    length = 0

    def flush() -> None:
        chunks.append(
            Chunk(
                chunk_id=f"{row.page_id}:infobox:{len(chunks)}",
                doc_id=row.doc_id,
                page_id=row.page_id,
                position=len(chunks),
                title=row.title,
                heading=HEADING,
                text=prefix + "\n".join(batch),
                themes=row.themes,
                revision_id=row.revision_id,
                revision_timestamp=row.revision_timestamp,
                license=row.license,
            )
        )

    for line in _lines(row):
        if batch and length + len(line) + 1 > size:
            flush()
            batch, length = [], 0
        batch.append(line)
        length += len(line) + 1

    if batch:
        flush()
    return chunks
