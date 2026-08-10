"""Where one query's time went, stage by stage.

Lives in `core/` beside `logging.py` for the same reason that does: every layer
needs it and no layer owns it. `retrieval/` and `generation/` both write spans,
`api/` and `eval/` both read them, and none of those may depend on another.

A span is four things -- a name, a start, an end, and a parent -- and that is
the whole idea. Writing those four fields by hand is deliberate: OpenTelemetry
exists to carry them across processes and machines, and this system is one
process calling one function chain in order. See D-101.
"""

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field


@dataclass(slots=True)
class Span:
    """One stage of one query: what ran, how long it took, and how deep it sits.

    Mutable, unlike almost everything else in this project, because a span is
    written twice: opened when the stage starts and closed when it ends. The
    alternative was building it at the end, which loses the ordering -- a stage
    that finishes last would be listed last even if it started first.

    `depth` rather than a parent pointer. A trace here is a tree only in the
    sense that a table of contents is: strictly nested, walked in order, never
    revisited. An indent level says everything a parent link would and prints
    itself.

    `note` is whatever the stage wants remembered -- how many candidates it saw,
    which model it called. It is what makes a trace replayable rather than only
    countable.
    """

    name: str
    depth: int
    ms: float = 0.0
    note: str = ""


@dataclass(slots=True)
class Trace:
    """The stages one query passed through, in the order they started.

    One per query, created by whoever is asking and passed down. Not a global
    and not a context variable: the eval runner asks 106 questions in a row and
    a trace that outlived its question would quietly accumulate all of them.
    """

    spans: list[Span] = field(default_factory=list)
    _depth: int = 0

    @contextmanager
    def span(self, name: str) -> Iterator[Span]:
        """Time one stage, and yield its span so the stage can annotate it.

        The span is appended on the way *in*, so a parent always precedes its
        children in the list and printing it in order gives the tree back. The
        duration is filled in on the way out, and in a `finally` -- a stage that
        raised still took time, and a trace that dropped the failing stage would
        be blind to exactly the case worth reading.
        """
        span = Span(name=name, depth=self._depth)
        self.spans.append(span)
        self._depth += 1
        began = time.perf_counter()
        try:
            yield span
        finally:
            self._depth -= 1
            span.ms = round((time.perf_counter() - began) * 1000, 1)
