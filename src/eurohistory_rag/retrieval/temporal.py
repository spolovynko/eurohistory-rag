"""What period is this question asking about?

The query half of D-096. One job: turn a question into a `Period`, or into
nothing at all. Nothing is a normal answer and it is the common one -- 38 of the
78 evaluation questions name no period, and for those the temporal arm of search
never runs.

The rule that matters most here is the refusal. "After the war" resolves to
nothing, on purpose, because this corpus holds two world wars and a cold one and
a system that quietly picks one is worse than a system that admits it cannot.
"""

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_YEAR = r"(1[89]\d{2}|20[0-2]\d)"

# "between 1947 and 1953", "from 1973 to 1993", "1979-1985". The two years must
# sit next to each other with only a separator between them, so "in 1968, and
# what happened next" is a single year rather than half of a range.
_RANGE = re.compile(
    rf"\b{_YEAR}\s*(?:-|--|–|—|to|and|until)\s*{_YEAR}\b", re.IGNORECASE
)
_BARE_YEAR = re.compile(rf"\b{_YEAR}\b")

# "the 1970s", "the early 1980s", "the late 1930s", "the mid-1960s".
_DECADE = re.compile(r"\b(early|mid|late)?[\s-]*(1[89]\d0|20[0-2]0)s\b", re.IGNORECASE)

# Which third of a decade a qualifier means. Four years for early and late, three
# for the middle, because a decade does not divide by three and stretching the
# ends is the permissive direction.
_DECADE_PARTS: dict[str, tuple[int, int]] = {
    "": (0, 9),
    "early": (0, 3),
    "mid": (4, 6),
    "late": (6, 9),
}

# Named periods, with the years this project uses for them. Every one is a
# judgement call somebody could argue with -- the Cold War's start date has a
# literature of its own -- so they live here, in one table, rather than being
# spelled into a regex. `docs/tuning.md` carries the row.
ERAS: dict[str, tuple[int, int]] = {
    "first world war": (1914, 1918),
    "world war i": (1914, 1918),
    "great war": (1914, 1918),
    "second world war": (1939, 1945),
    "world war ii": (1939, 1945),
    "interwar": (1918, 1939),
    "between the wars": (1918, 1939),
    "early cold war": (1947, 1962),
    "late cold war": (1979, 1991),
    "cold war": (1947, 1991),
}

# A date next to any of these is a *reference point*, not the period being asked
# about. "What was Germany made to pay after 1918" is a question about the whole
# of the 1920s; reading it as the single year 1918 is not a near miss, it is the
# wrong answer. "Between the end of the Second World War and his election" is
# about 1945-1953, and resolving it to 1939-1945 would push retrieval at exactly
# the wrong sections.
#
# Which side of the reference point is meant, and how far it runs, cannot be read
# off the words. So nothing is returned -- for a bare year and for a named era
# alike. This is the roadmap's "a relative expression is ambiguous in a corpus
# that contains two of them", implemented as a deliberate absence rather than a
# guess, and it is why 40 of 78 evaluation questions resolve to nothing.
#
# An explicit two-year range and an explicit decade survive it, because those
# state their own width: "between 1947 and 1953" means that and nothing else,
# whatever else the sentence is doing.
_DIRECTIONAL = re.compile(
    r"\b(after|before|since|following|preceding|end of|start of|outbreak of|"
    r"aftermath of|run[- ]up to|lead[- ]up to|eve of)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class Period:
    """A closed range of years, both ends included."""

    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueError(f"period runs backwards: {self.start}-{self.end}")

    def agreement(self, start: int | None, end: int | None) -> float:
        """How much this period and a chunk's span agree, from 0 to 1.

        Overlapping years divided by the years either one covers. It exists
        because the first build of the temporal arm treated overlap as a yes or
        no: `Cold War (1985-1991)` touches a question about 1979-1985 by the
        single year 1985, qualified on that basis, and displaced the section
        that covers 1979-1985 exactly.

        Two failures, one number. A near-miss scores low because the overlap is
        small (1/13 for that example). A span so wide it covers everything --
        1800-2024, which 9.7% of body-derived spans approach -- also scores low,
        because the union is enormous (2/225 against a question about 1948-49).
        Rewarding coverage alone would have promoted exactly those. See the
        D-096 addendum.

        An undated chunk scores 0. It is never removed for it; this only ever
        orders a list the chunk is already in.
        """
        if start is None or end is None:
            return 0.0
        overlap = min(self.end, end) - max(self.start, start) + 1
        if overlap <= 0:
            return 0.0
        union = max(self.end, end) - min(self.start, start) + 1
        return overlap / union


def parse_period(question: str) -> Period | None:
    """The years this question is about, or None when they cannot be read.

    Absolute beats relative, always. A question that states years means those
    years, whatever era names happen to appear beside them -- "What did Germany
    lose under the 1919 treaty ending the First World War" is about 1919.
    """
    ranged = _RANGE.search(question)
    if ranged is not None:
        first, second = int(ranged.group(1)), int(ranged.group(2))
        return Period(min(first, second), max(first, second))

    # Every decade named, not the first one. "in the 1950s and 1960s" means
    # 1950-1969, and reading only the first half of it is how
    # `why-life-got-better-fast` lost its answer past rank 20 -- the
    # over-narrow filter the roadmap warned about, arriving through the parser
    # rather than through the data. Bare years below already span all their
    # matches; this is the same rule, applied where it was missing.
    decades = [
        (
            base + _DECADE_PARTS[(qualifier or "").lower()][0],
            base + _DECADE_PARTS[(qualifier or "").lower()][1],
        )
        for qualifier, raw in _DECADE.findall(question)
        for base in (int(raw),)
    ]
    if decades:
        return Period(min(d[0] for d in decades), max(d[1] for d in decades))

    # Everything below states a point rather than a width, so a word pointing
    # away from that point makes the width unreadable and nothing is returned.
    if _DIRECTIONAL.search(question):
        logger.debug("period declined: %r is relative to its date", question)
        return None

    years = [int(match.group()) for match in _BARE_YEAR.finditer(question)]
    if years:
        return Period(min(years), max(years))

    return _era(question)


def _era(question: str) -> Period | None:
    """A named period, when the question names one and nothing more precise.

    Longest name first, so "early cold war" is not swallowed by "cold war".
    """
    lowered = question.lower()
    for name in sorted(ERAS, key=len, reverse=True):
        if name in lowered:
            start, end = ERAS[name]
            return Period(start, end)
    return None
