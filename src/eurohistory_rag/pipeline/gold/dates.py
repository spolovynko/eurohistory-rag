"""What period does a chunk cover?

The distinction this module turns on is the one the roadmap names: the date a
chunk *mentions* is not the period it *covers*, and only the second is worth
filtering on. A section about the Berlin airlift mentions 1989 in a closing
sentence; it does not cover it.

So the answer is looked for in three places, best first, and the first one that
speaks wins. Nothing here guesses: a chunk with no year anywhere gets no span at
all, and a chunk with no span is never excluded from anything downstream.
"""

import re
from dataclasses import dataclass

# 1800-2029. Wide enough for a corpus whose articles reach back for background
# and forward to the present, narrow enough that a page number, a casualty
# figure or a sum of money cannot be mistaken for a year.
_YEAR = re.compile(r"\b(1[89]\d{2}|20[0-2]\d)\b")


@dataclass(frozen=True, slots=True)
class Span:
    """The years a chunk covers, and where that was read from.

    `source` is kept because the three rungs are not equally trustworthy and a
    verdict that cannot separate them cannot say which one earned the result.
    """

    start: int
    end: int
    source: str


def years_in(text: str) -> tuple[int, int] | None:
    """The first and last year mentioned, or None if none is.

    Plain minimum and maximum, with no outlier trimming, and that is deliberate.
    A stray year -- "the 1889-1890 influenza pandemic", in a section about the
    Belgian Congo -- widens the span, and a wider span matches more questions
    rather than fewer. The whole risk of date filtering is being too narrow, so
    the simple rule's failure mode points the safe way. See D-096.
    """
    years = [int(match.group()) for match in _YEAR.finditer(text)]
    return (min(years), max(years)) if years else None


def chunk_span(heading: str, title: str, text: str) -> Span | None:
    """The period this chunk covers, from the best source that names one.

    A heading beats a title because a Wikipedia editor wrote
    "Containment, Truman Doctrine, Korean War (1947-1953)" as the declared scope
    of that one section. A title beats the body because "1973 oil crisis" is
    still a declared scope, just a coarser one. The body is the fallback and the
    weakest rung, because those years are mentions.
    """
    for source, candidate in (("heading", heading), ("title", title), ("text", text)):
        found = years_in(candidate)
        if found is not None:
            return Span(start=found[0], end=found[1], source=source)
    return None
