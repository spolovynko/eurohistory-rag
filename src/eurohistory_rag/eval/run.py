"""Asking every question and writing down what happened.

One search deep enough to score recall at any depth, and one generation from
the top of that same list -- so the answer being judged is the answer /ask
would have given, not an approximation of it.
"""

import logging
import subprocess
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from eurohistory_rag.core.trace import Trace
from eurohistory_rag.eval.questions import Question
from eurohistory_rag.eval.record import CitationRef, EvalRecord, Retrieved, RunMeta
from eurohistory_rag.generation.client import GenerationUnavailable
from eurohistory_rag.generation.rewrite import Turn
from eurohistory_rag.generation.service import CITATION, GenerationService
from eurohistory_rag.retrieval.search import SearchResult, SearchService

logger = logging.getLogger(__name__)

# How deep retrieval is recorded. The deepest cut-off any metric reports, so
# recall@5 and recall@20 both come out of a single search rather than two.
RETRIEVAL_K = 20


def _elapsed_ms(started: float) -> float:
    """Milliseconds since a perf_counter reading, to one decimal."""
    return round((time.perf_counter() - started) * 1000, 1)


def git_sha() -> str:
    """The commit the code was at, or "unknown" outside a repository.

    Recorded on every run because a run is only meaningful next to the code
    that produced it -- "recall went up" means nothing without knowing what
    changed between the two.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def to_retrieved(
    results: Sequence[SearchResult], with_text: int = 0
) -> list[Retrieved]:
    """Search results as record rows, ranked from 1.

    `with_text` is how many of the top results keep their chunk text. Only the
    ones the model was shown need it, and carrying all twenty would triple a
    run's size for text already sitting in Gold.
    """
    return [
        Retrieved(
            rank=rank,
            chunk_id=result.chunk_id,
            doc_id=result.doc_id,
            page_id=result.page_id,
            source=result.source,
            score=round(result.score, 4),
            text=result.text if rank <= with_text else "",
            rerank_score=(
                None if result.rerank_score is None else round(result.rerank_score, 4)
            ),
            sparse_score=(
                None if result.sparse_score is None else round(result.sparse_score, 4)
            ),
        )
        for rank, result in enumerate(results, start=1)
    ]


def history(question: Question) -> list[Turn]:
    """The exchange before this question, in the shape a record stores.

    Two nearly identical types on purpose. `questions.Turn` is validated input a
    person edits, so it is a pydantic model with rules; `rewrite.Turn` is what
    the rest of the system passes around, and it is a plain dataclass because
    that is what a record is made of. Collapsing them would make the run format
    and the answer path depend on the question file's schema, which is the
    coupling `suite` and `expected_answers` already avoid.
    """
    return [Turn(user=t.user, assistant=t.assistant) for t in question.history]


def markers_in(text: str) -> list[int]:
    """Every [n] the answer wrote, in order, including invented ones.

    Deliberately not the same as the citation list: `cited()` drops a number
    with no source behind it, and the gap between the two is exactly the
    measure of whether the prompt's citation rule held.
    """
    return [int(match.group(1)) for match in CITATION.finditer(text)]


def run_question(
    question: Question,
    search: SearchService,
    generation: GenerationService,
    answer_k: int,
    retrieval_k: int = RETRIEVAL_K,
) -> EvalRecord:
    """Ask one question and record everything the system did with it.

    A generation failure is recorded rather than raised: one unreachable model
    call should not throw away the twenty-nine questions already answered.
    """
    started = time.perf_counter()
    # One trace per question, created here and passed into both halves. Not a
    # global and not one per run: 106 questions through one trace would be 106
    # questions' spans in a heap with nothing saying where each began. D-101.
    trace = Trace()
    # What actually gets embedded. With no rewriter, or with no history, this is
    # the question as written -- which is why every one of the 92 single-turn
    # questions takes the identical path it took before this phase existed.
    standalone = generation.standalone(question.text, history(question), trace=trace)
    results = search.search(standalone, k=retrieval_k, trace=trace)
    search_ms = _elapsed_ms(started)

    sent = results[:answer_k]
    generation_started = time.perf_counter()
    try:
        # The resolved question, not the typed one: the model is asked what the
        # reader meant. Identical to `question.text` for every single-turn
        # question, so nothing outside the conversation suite can move.
        answer = generation.answer_from(standalone, sent, trace=trace)
    except GenerationUnavailable as failure:
        logger.warning("%s: generation failed: %s", question.id, failure)
        generate_ms = _elapsed_ms(generation_started)
        return EvalRecord(
            question_id=question.id,
            question=question.text,
            kind=question.kind,
            suite=question.suite,
            expected_doc_ids=list(question.expected),
            expected_answers=list(question.expected_answer),
            history=history(question),
            standalone="" if standalone == question.text else standalone,
            retrieved=to_retrieved(results, with_text=answer_k),
            answer="",
            generation_model="",
            sources_sent=len(sent),
            markers_found=[],
            citations=[],
            search_ms=search_ms,
            generate_ms=generate_ms,
            total_ms=_elapsed_ms(started),
            trace=trace.spans,
            error=str(failure),
        )
    generate_ms = _elapsed_ms(generation_started)

    return EvalRecord(
        question_id=question.id,
        question=question.text,
        kind=question.kind,
        suite=question.suite,
        expected_doc_ids=list(question.expected),
        expected_answers=list(question.expected_answer),
        history=history(question),
        standalone="" if standalone == question.text else standalone,
        retrieved=to_retrieved(results, with_text=answer_k),
        answer=answer.text,
        revised=answer.revised,
        draft=answer.draft,
        generation_model=answer.model,
        sources_sent=len(sent),
        markers_found=markers_in(answer.text),
        citations=[
            CitationRef(
                number=citation.number,
                doc_id=citation.result.doc_id,
                source=citation.result.source,
            )
            for citation in answer.citations
        ],
        search_ms=search_ms,
        generate_ms=generate_ms,
        total_ms=_elapsed_ms(started),
        # From the start of the question, not the start of generation: the
        # search is part of the wait, and a TTFT that excluded it would flatter
        # the number by the 518 ms retrieval costs. None when nothing streamed.
        first_token_ms=(
            None
            if answer.first_token_ms is None
            else round(search_ms + answer.first_token_ms, 1)
        ),
        prompt_tokens=answer.prompt_tokens,
        completion_tokens=answer.completion_tokens,
        # The stages, in the order they ran. `total_ms` is read one line above
        # and these are read after, so anything the spans do not account for is
        # real unattributed time rather than a rounding artefact.
        trace=trace.spans,
    )


class Cancelled(Exception):
    """Raised when a caller asked for the run to stop between questions."""


def run_all(
    questions: Sequence[Question],
    search: SearchService,
    generation: GenerationService,
    answer_k: int,
    retrieval_k: int = RETRIEVAL_K,
    on_question: Callable[[int, Question], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> list[EvalRecord]:
    """Ask every question in order, one at a time.

    Sequential on purpose: thirty questions take a couple of minutes, and
    concurrent calls would make the latency numbers measure contention rather
    than the system.

    The two callbacks exist for the caller that is not a terminal. `on_question`
    is how a four-minute job says where it has got to; `should_stop` is how it
    is stopped. Both are checked *between* questions and never inside one --
    a half-asked question is money already spent, and abandoning it would leave
    a record nobody could interpret.
    """
    records: list[EvalRecord] = []
    for position, question in enumerate(questions, start=1):
        if should_stop is not None and should_stop():
            raise Cancelled(f"stopped before question {position}")
        logger.info("[%d/%d] %s", position, len(questions), question.id)
        if on_question is not None:
            on_question(position, question)
        records.append(
            run_question(question, search, generation, answer_k, retrieval_k)
        )
    return records


def build_meta(
    run_id: str,
    settings_collection: str,
    embedding_model: str,
    generation_model: str,
    points: int,
    answer_k: int,
    max_per_document: int,
    overfetch: int,
    reranker: str = "",
    hybrid: str = "",
    verifier: str = "",
    temporal: str = "",
    conversation: str = "",
    max_per_article: str = "",
    note: str = "",
) -> RunMeta:
    """Capture the conditions this run happened under."""
    return RunMeta(
        run_id=run_id,
        started_at=datetime.now(UTC).isoformat(timespec="seconds"),
        git_sha=git_sha(),
        embedding_model=embedding_model,
        generation_model=generation_model,
        collection=settings_collection,
        points=points,
        k=answer_k,
        max_per_document=max_per_document,
        overfetch=overfetch,
        reranker=reranker,
        hybrid=hybrid,
        verifier=verifier,
        temporal=temporal,
        conversation=conversation,
        max_per_article=max_per_article,
        note=note,
    )
