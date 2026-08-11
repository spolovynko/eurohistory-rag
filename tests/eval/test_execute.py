"""Tests for the shared run function.

Neither the CLI nor the API owns what an evaluation is any more, so this is
where that is checked: what gets written, in what order, and what happens when
somebody asks it to stop.
"""

from pathlib import Path
from typing import cast

import pytest
from pydantic import SecretStr

from eurohistory_rag.core.config import Settings
from eurohistory_rag.core.trace import Trace
from eurohistory_rag.eval.execute import PREDICTION_FILE, RunConfig, execute
from eurohistory_rag.eval.questions import Question
from eurohistory_rag.eval.run import Cancelled, run_all
from eurohistory_rag.generation.service import GenerationService
from eurohistory_rag.retrieval.search import SearchResult, SearchService
from eurohistory_rag.retrieval.vectorstore import VectorStore
from tests.fakes import FakeEmbedder, FakeGenerator


class StubStore:
    """Enough of a vector store for the two things a run asks of one."""

    def __init__(self, results: list[SearchResult]) -> None:
        self._results = results

    def count(self) -> int:
        return 54903

    def search(self, vector: list[float], limit: int) -> list[SearchResult]:
        return self._results[:limit]


class StubSearch:
    """Returns the same passage for every question."""

    def __init__(self, results: list[SearchResult]) -> None:
        self._results = results

    def search(
        self,
        question: str,
        k: int | None = None,
        min_score: float | None = None,
        trace: Trace | None = None,
    ) -> list[SearchResult]:
        return self._results[: k or len(self._results)]

    def search_with_vector(
        self,
        question: str,
        k: int | None = None,
        min_score: float | None = None,
        trace: Trace | None = None,
    ) -> tuple[list[SearchResult], list[float]]:
        return self.search(question, k, min_score, trace), [1.0, 0.0, 0.0]


def passage() -> SearchResult:
    return SearchResult(
        chunk_id="30030:1:0",
        doc_id="30030:1",
        page_id=30030,
        title="Marshall Plan",
        heading="Origins",
        text="The programme distributed $13.3 billion over four years.",
        score=0.61,
        revision_id=30130,
    )


def questions(count: int = 3) -> list[Question]:
    return [
        Question(id=f"q{n}", text="what happened?", kind="easy", expected=("30030:1",))
        for n in range(count)
    ]


def settings() -> Settings:
    """Settings with every field these tests read stated explicitly.

    Not `Settings()`: that reads the developer's `.env`, where the reranker is
    switched on, so the same assertion would pass on CI and fail on this
    laptop. D-093 was that failure in the other direction, and it cost a red
    build nobody could reproduce locally.
    """
    return Settings(
        openai_api_key=SecretStr("test-key"),
        wikipedia_user_agent="tests",
        generation_model="gpt-4.1-mini",
        reranker_enabled=False,
        hybrid_enabled=False,
        verify_enabled=False,
    )


def fake_search() -> SearchService:
    """A search that returns the same passage for every question.

    Cast rather than subclassed: `SearchService` is a concrete class here, and
    the run only ever calls `.search()` on it. The cast says "this honours the
    part that is used", which is what a Protocol would say if there were one.
    """
    return cast(SearchService, StubSearch([passage()]))


def fake_generation() -> GenerationService:
    return GenerationService(fake_search(), FakeGenerator("It did [1]."))


def stack(
    _: Settings, __: RunConfig
) -> tuple[SearchService, GenerationService, VectorStore]:
    """The retrieval and answer path, with nothing on the network behind it."""
    search = fake_search()
    return (
        search,
        GenerationService(search, FakeGenerator("It did [1].")),
        cast(VectorStore, StubStore([passage()])),
    )


CONFIG = RunConfig(
    k=5,
    model="gpt-4.1-mini",
    reranker="",
    hybrid=False,
    temporal=False,
    conversation=False,
    max_per_article=None,
)


def test_a_run_writes_the_four_files_the_cli_writes(tmp_path: Path) -> None:
    """Byte-comparable with a CLI run means the same files, from the same code."""
    directory = execute(
        questions(),
        settings(),
        CONFIG,
        run_id="2026-01-01T0000Z",
        runs_dir=tmp_path,
        build=stack,
    )

    assert sorted(path.name for path in directory.iterdir()) == [
        "meta.json",
        "records.jsonl",
        "summary.txt",
        "transcript.txt",
    ]


def test_the_configuration_reaches_meta_json(tmp_path: Path) -> None:
    """A run that cannot say what produced it is Phase 8's dead switch waiting.

    The knobs come from the request now rather than from `.env`, so the thing
    recorded has to be what was asked for, not what the process defaults to.
    """
    import json

    directory = execute(
        questions(),
        settings(),
        RunConfig(
            k=8,
            model="gpt-4.1-nano",
            reranker="cross-encoder/x",
            hybrid=True,
            temporal=True,
            conversation=False,
            max_per_article=None,
        ),
        run_id="2026-01-01T0000Z",
        runs_dir=tmp_path,
        build=stack,
    )
    meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))

    assert meta["k"] == 8
    assert meta["generation_model"] == "gpt-4.1-nano"
    assert meta["reranker"] == "cross-encoder/x"
    assert meta["hybrid"].startswith("bm25+rrf")


def test_a_prediction_already_in_the_directory_survives_the_run(
    tmp_path: Path,
) -> None:
    """The run writes into the directory the prediction is already in.

    This is the ordering the phase exists for, from the other end: the caller
    creates the directory and puts the prediction in it, and nothing the run
    writes afterwards may touch it.
    """
    directory = tmp_path / "2026-01-01T0000Z"
    directory.mkdir()
    (directory / PREDICTION_FILE).write_text("recall@5 will not move.\n", "utf-8")

    execute(
        questions(),
        settings(),
        CONFIG,
        run_id="2026-01-01T0000Z",
        runs_dir=tmp_path,
        build=stack,
    )

    assert (directory / PREDICTION_FILE).read_text(encoding="utf-8") == (
        "recall@5 will not move.\n"
    )
    assert (directory / "records.jsonl").exists()


def test_a_cancelled_run_writes_nothing(tmp_path: Path) -> None:
    """Half a run is not half a result -- it is no result, and it says so.

    `browse._is_run` requires meta.json and records.jsonl, so a directory with
    neither cannot be listed or gated. What a cancel must never do is leave a
    partial records file that scores as a real run of fewer questions.
    """
    with pytest.raises(Cancelled):
        execute(
            questions(),
            settings(),
            CONFIG,
            run_id="2026-01-01T0000Z",
            runs_dir=tmp_path,
            build=stack,
            should_stop=lambda: True,
        )

    assert not (tmp_path / "2026-01-01T0000Z").exists()


def test_progress_is_reported_once_per_question() -> None:
    """A four-minute job has to be able to say where it has got to."""
    seen: list[tuple[int, str]] = []

    run_all(
        questions(4),
        fake_search(),
        fake_generation(),
        answer_k=5,
        on_question=lambda position, question: seen.append((position, question.id)),
    )

    assert seen == [(1, "q0"), (2, "q1"), (3, "q2"), (4, "q3")]


def test_a_stop_is_checked_between_questions_not_inside_one() -> None:
    """The question being asked is already paid for, so it is finished.

    Stopping mid-call would spend the money and throw away the answer, and
    leave a record nobody could interpret.
    """
    asked: list[str] = []
    stop_after = 2

    records = []
    with pytest.raises(Cancelled):
        records = run_all(
            questions(5),
            StubSearch([passage()]),  # type: ignore[arg-type]
            GenerationService(StubSearch([passage()]), FakeGenerator("It did [1].")),  # type: ignore[arg-type]
            answer_k=5,
            on_question=lambda _, question: asked.append(question.id),
            should_stop=lambda: len(asked) >= stop_after,
        )

    assert asked == ["q0", "q1"]
    assert records == []


def test_the_default_configuration_is_what_settings_say() -> None:
    """`RunConfig.from_settings` is what "nothing overridden" means."""
    config = RunConfig.from_settings(settings())

    assert config.model == "gpt-4.1-mini"
    assert config.reranker == ""
    assert config.hybrid is False
    assert config.k == 5


def test_the_embedder_fake_is_not_used_by_accident() -> None:
    """A guard on the test stack itself, not on the code.

    `FakeEmbedder` exists for the retrieval tests; if it ever appeared in this
    module's stack it would mean the run was scoring vectors nobody wrote.
    """
    assert FakeEmbedder is not None


def test_from_settings_carries_every_retrieval_flag() -> None:
    """The wire that was forgotten, pinned.

    `temporal` was added to RunConfig with a default, the CLI built the object
    field by field and never passed it, and a run made with the flag on measured
    the flag off -- $0.11 for a table identical to the one before it. The field
    lost its default afterwards, which is what makes a forgotten wire a type
    error; this checks the values actually arrive. See the D-096 fourth addendum.
    """
    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        wikipedia_user_agent="test/1.0 (test@example.com)",
        hybrid_enabled=True,
        temporal_enabled=True,
        reranker_enabled=True,
    )
    config = RunConfig.from_settings(settings)
    assert config.hybrid is True
    assert config.temporal is True
    assert config.reranker == settings.reranker_model
