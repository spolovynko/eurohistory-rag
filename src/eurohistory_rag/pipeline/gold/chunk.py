"""Cutting one Silver document into Gold chunks.

The rules, all recorded in decisions.md:

  boundary  paragraphs, falling back to sentences, falling back to words
  size      1,200 characters of body
  overlap   150 characters, rounded up to whole sentences
  text      "{title} -- {heading}\\n\\n{body}", the prefix outside the budget

A chunk is meant to be about one thing. Everything below serves that: cut where
the author already put a break, and only cut somewhere worse when the author's
break leaves a piece too large to embed usefully.
"""

import re
from collections.abc import Sequence

from eurohistory_rag.pipeline.gold.store import Chunk
from eurohistory_rag.pipeline.silver.store import SilverRow

# Abbreviations that end in a full stop without ending a sentence. Not
# exhaustive and not meant to be -- this list covers what history prose
# actually uses, and an unlisted one costs a single ragged chunk.
_ABBREVIATIONS = frozenset(
    {
        "u.s",
        "u.k",
        "u.s.s.r",
        "e.g",
        "i.e",
        "cf",
        "ca",
        "c",
        "approx",
        "vs",
        "mr",
        "mrs",
        "ms",
        "dr",
        "prof",
        "gen",
        "col",
        "lt",
        "sgt",
        "capt",
        "st",
        "mt",
        "no",
        "vol",
        "pp",
        "ed",
        "jr",
        "sr",
    }
)

# A full stop, question or exclamation mark, then whitespace, then something
# that could begin a sentence.
_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[]?[A-Z0-9])")

# The final dotted word of a fragment: "the U.S." -> "U.S"
_TRAILING_WORD = re.compile(r"([\w.]+)\.$")


CHUNK_SIZE = 1200  # characters of body, prefix excluded. See D-037.
CHUNK_OVERLAP = 150  # rounded up to whole sentences
MIN_TAIL_CHARS = 200  # a final chunk smaller than this is merged backwards
_HEADING_MAX_CHARS = 70

_PARAGRAPH = "\n\n"


def _ends_in_abbreviation(fragment: str) -> bool:
    """True if this fragment's final full stop belongs to an abbreviation.

    Exists so the splitter can undo its own bad cuts rather than needing a
    lookbehind for every abbreviation, which regex cannot express.
    """
    match = _TRAILING_WORD.search(fragment)
    if match is None:
        return False
    return match.group(1).lower().rstrip(".") in _ABBREVIATIONS


def split_sentences(text: str) -> list[str]:
    """Cut text into sentences, the middle rung of the boundary ladder.

    Deliberately approximate: it runs only on paragraphs too large to keep
    whole, where a slightly wrong cut is much better than a mid-word one.
    """
    if not text.strip():
        return []
    sentences: list[str] = []
    for fragment in _BOUNDARY.split(text):
        if sentences and _ends_in_abbreviation(sentences[-1]):
            sentences[-1] = f"{sentences[-1]} {fragment}"
        else:
            sentences.append(fragment)
    return sentences


def _pack(pieces: Sequence[str], size: int, joiner: str) -> list[str]:
    """Greedily group pieces into strings of at most `size` characters.

    The one grouping rule in the module, used at all three rungs of the
    ladder: words into sentence-sized runs, sentences into paragraph-sized
    runs, paragraphs into chunks. A piece longer than `size` on its own is
    emitted as-is rather than cut -- deciding how to cut it belongs to the
    caller, which knows which rung it is on.
    """
    packed: list[str] = []
    current = ""
    for piece in pieces:
        candidate = piece if not current else f"{current}{joiner}{piece}"
        if current and len(candidate) > size:
            packed.append(current)
            current = piece
        else:
            current = candidate
    if current:
        packed.append(current)
    return packed


def _units(text: str, size: int) -> list[str]:
    """Break a document into the largest pieces that fit in one chunk.

    Walks the boundary ladder: a paragraph that fits is one unit; one that
    does not is regrouped into sentence runs; a single sentence that still
    does not fit is cut at spaces. Nothing this returns is longer than
    `size`, except a single word that is -- a URL, and rare enough to leave.
    """
    paragraphs = [p.strip() for p in text.split(_PARAGRAPH) if p.strip()]
    units: list[str] = []
    for paragraph in _attach_headings(paragraphs):
        if len(paragraph) <= size:
            units.append(paragraph)
            continue
        for run in _pack(split_sentences(paragraph), size, " "):
            if len(run) <= size:
                units.append(run)
            else:
                units.extend(_pack(run.split(), size, " "))
    return units


def _overlap_text(body: str, overlap: int) -> str:
    """The tail of a chunk, in whole sentences, to repeat at the head of the next.

    Exists so a claim split across a boundary survives whole in one chunk. It
    takes sentences from the end while they fit in `overlap`, so a chunk that
    ends on one very long sentence carries nothing forward -- which is fine,
    because a sentence that long is already self-contained.
    """
    if overlap <= 0:
        return ""
    tail: list[str] = []
    length = 0
    for sentence in reversed(split_sentences(body)):
        addition = len(sentence) + (1 if tail else 0)
        if length + addition > overlap:
            break
        tail.insert(0, sentence)
        length += addition
    return " ".join(tail)


def chunk_document(doc: SilverRow, size: int, overlap: int) -> list[Chunk]:
    """Cut one Silver document into the chunks that will be embedded.

    Pure by design: this is the one place in the project where a decision
    visibly changes answer quality, so it must be cheap to run a hundred times
    with different numbers and read the output.
    """
    if overlap >= size:
        raise ValueError(f"overlap ({overlap}) must be smaller than size ({size})")

    bodies = _pack(_units(doc.text, size), size, _PARAGRAPH)
    if not bodies:
        return []
    if len(bodies) > 1 and len(bodies[-1]) < MIN_TAIL_CHARS:
        bodies[-2:] = [f"{bodies[-2]}{_PARAGRAPH}{bodies[-1]}"]

    prefix = f"{doc.title} — {doc.heading}" if doc.heading else doc.title

    return [
        Chunk(
            chunk_id=f"{doc.doc_id}:{position}",
            doc_id=doc.doc_id,
            page_id=doc.page_id,
            position=position,
            title=doc.title,
            heading=doc.heading,
            text=_PARAGRAPH.join(
                part
                for part in (
                    prefix,
                    _overlap_text(bodies[position - 1], overlap) if position else "",
                    body,
                )
                if part
            ),
            themes=doc.themes,
            revision_id=doc.revision_id,
            revision_timestamp=doc.revision_timestamp,
            license=doc.license,
        )
        for position, body in enumerate(bodies)
    ]


def _looks_like_a_heading(paragraph: str) -> bool:
    """True if this paragraph is a subheading Silver left behind as bare text.

    Level-3 headings survive the Silver clean as a short line with no closing
    punctuation. Nothing else in the prose looks like that.
    """
    return len(paragraph) <= _HEADING_MAX_CHARS and not paragraph.endswith(
        (".", "!", "?", '"', ")")
    )


def _attach_headings(paragraphs: list[str]) -> list[str]:
    """Glue each bare subheading onto the paragraph it introduces.

    A heading belongs with what follows it, so binding the two before packing
    makes it impossible for a chunk to end on an orphaned heading whose
    content is in the next chunk. Consecutive headings travel together; a
    heading with nothing after it stays as it is rather than being dropped.
    """
    attached: list[str] = []
    pending: list[str] = []
    for paragraph in paragraphs:
        if _looks_like_a_heading(paragraph):
            pending.append(paragraph)
            continue
        attached.append("\n".join([*pending, paragraph]))
        pending = []
    if pending:
        attached.append("\n".join(pending))
    return attached
