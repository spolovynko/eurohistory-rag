"""BM25 weights for a piece of text.

The keyword half of hybrid search. Cosine search finds chunks that *mean*
something similar to the question; this finds chunks that use the same rare
words, which is what pulls a Trianon section out of a corpus full of post-war
treaties.

Only the term-frequency half of BM25 lives here. The rare-word half -- IDF --
needs document frequencies for the entire corpus, and Qdrant already holds
them: the collection declares `modifier=Idf` and multiplies it in at query
time. See D-075.
"""

import re
import zlib
from collections import Counter
from collections.abc import Iterable, Sequence

# Runs of letters and digits; everything else is a separator. Digits are kept
# on purpose -- "1945" is a term this corpus gets asked about constantly.
_TOKEN = re.compile(r"[^\W_]+")

# How fast a repeated word stops earning score. At 1.5 the fourth mention of
# "Trianon" is worth much less than the first, so a long article cannot beat a
# short precise one by repetition alone.
K1 = 1.5

# How hard length is punished. 0.75 is BM25's standard: a chunk twice the
# average length needs more mentions to score the same.
B = 0.75


def tokenize(text: str) -> list[str]:
    """The words BM25 counts, lowercased.

    Deliberately plain -- no stemming and no stopword list, so "invaded" and
    "invasion" are two different terms. D-075 records that as a known cost
    rather than an oversight: both are cheap to add once a number says they are
    needed, and adding them now would make this phase two changes.
    """
    return _TOKEN.findall(text.lower())


def term_index(token: str) -> int:
    """A stable 32-bit id for a word.

    Qdrant addresses sparse dimensions by integer, so every word needs a number.
    CRC32 rather than Python's `hash`, which is salted per process -- an index
    built in one run would not match a query made in the next, and the failure
    would be silent.

    Two different words can land on the same id. At this corpus size that is a
    handful of pairs out of four billion slots, and the cost of one is a term
    scoring slightly high on an unrelated chunk.
    """
    return zlib.crc32(token.encode("utf-8"))


def average_length(documents: Iterable[Sequence[str]]) -> float:
    """Mean token count across the corpus.

    BM25 judges a chunk's length against the average rather than in absolute
    terms, so this has to be measured over the whole of Gold before a single
    chunk can be weighted. Returns 0.0 for an empty corpus, which
    `document_vector` reads as "no length penalty".
    """
    lengths = [len(document) for document in documents]
    return sum(lengths) / len(lengths) if lengths else 0.0


def document_vector(
    tokens: Sequence[str], corpus_average_length: float
) -> dict[int, float]:
    """BM25 weights for one chunk, keyed by term id.

    Each weight is the part of the score that depends on this chunk alone: how
    often a word appears here, damped by K1, and reduced if the chunk is longer
    than average. How rare the word is across the corpus is deliberately
    missing -- that half is Qdrant's.
    """
    if not tokens:
        return {}
    length_penalty = (
        K1 * (1 - B + B * len(tokens) / corpus_average_length)
        if corpus_average_length
        else K1
    )
    return {
        term_index(token): frequency * (K1 + 1) / (frequency + length_penalty)
        for token, frequency in Counter(tokens).items()
    }


def query_vector(text: str) -> dict[int, float]:
    """BM25 weights for a question: every word counts once.

    No frequency damping and no length penalty on this side. A question is
    short and a word repeated in it carries no extra meaning, so the query only
    says *which* words to look for; the weighting is the document's job and the
    rarity is Qdrant's.
    """
    return {term_index(token): 1.0 for token in tokenize(text)}
