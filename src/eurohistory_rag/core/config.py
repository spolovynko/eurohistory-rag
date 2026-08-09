"""Typed application configuration, loaded from the environment and .env."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Wikipedia's licence, not a choice. Stated once here rather than stored on
# 30,362 identical payloads; the API repeats it with every response.
CORPUS_LICENSE = "CC BY-SA 4.0"


class Settings(BaseSettings):
    """Application configuration, validated at construction.

    Sources, highest priority first: constructor arguments, real environment
    variables, the .env file, field defaults. A required field that reaches the
    end of that list raises ValidationError immediately, so a missing key fails
    at startup rather than halfway through a run.

    Extra keys in .env are rejected (pydantic-settings defaults to
    extra='forbid'), so .env.example and these fields must be kept in step.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Required: no safe default exists for either.
    openai_api_key: SecretStr
    wikipedia_user_agent: str

    # Defaulted: correct locally, overridden by the environment in deployment.
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "chunks"

    # The embedding model and its output size must move together: the Qdrant
    # collection is created with this size, and a mismatch is only caught when
    # the first vector is written.
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536

    # D-052 chose gpt-4.1-mini and reversed gpt-5-mini. The default has to match
    # the decision: a machine without this key in .env runs the rejected model.
    generation_model: str = "gpt-4.1-mini"

    # Which model grades faithfulness. Its own setting rather than reusing
    # generation_model, because "the model that answers also marks its own
    # homework" is a known bias and this is the one line that fixes it. It
    # defaults to the same model, so by default the bias is present and the
    # number carries that caveat -- an honest default beats a flattering one.
    # Phase 10, D-079.
    judge_model: str = "gpt-4.1-mini"

    # The reranker runs locally, so there is no key to hold. Named here rather
    # than in code because swapping it is an experiment, not a code change --
    # and it is a per-machine concern: a laptop may want the smaller model.
    reranker_model: str = "BAAI/bge-reranker-base"

    # What the interface may offer, and therefore what a request may ask for.
    # An allow-list rather than free text: `model` and `reranker` arrive from a
    # browser, and a name that reaches OpenAI or HuggingFace unchecked is a way
    # to spend money or read 500 MB off the network on a stranger's say-so.
    # Every model here was called once and verified to answer; gpt-5-mini was
    # tried and left out, because it spends its budget on reasoning tokens and
    # returned an empty answer under the same cap the others answered within.
    selectable_models: tuple[str, ...] = (
        "gpt-4.1-mini",
        "gpt-4.1-nano",
        "gpt-4.1",
        "gpt-4o-mini",
    )

    # Both rerankers Phase 8 measured. bge-reranker-base is kept on the list
    # deliberately: it is the default above and it is the one Phase 8 found
    # broken, so hiding it would make the default unreproducible. The interface
    # marks it; see D-092.
    selectable_rerankers: tuple[str, ...] = (
        "cross-encoder/ms-marco-MiniLM-L6-v2",
        "BAAI/bge-reranker-base",
    )

    # Off by default so the system's behaviour does not change until the eval
    # says it should. Phase 8 turns it on in .env, measures, and then decides.
    reranker_enabled: bool = False

    # Load the reranker when the process starts instead of inside the first
    # request. On by default, unlike every other flag in this file, because it
    # cannot change an answer -- the same model produces the same scores whether
    # it was read at second 0 or second 30, so there is no comparison for a
    # forgotten flag to contaminate. It changes only who waits.
    #
    # The tests switch it off. `TestClient` runs the lifespan, so leaving it on
    # would make 649 offline tests read 88 MB off disk, and download it on a
    # machine that has never run the reranker. Phase 25, D-099.
    warm_start: bool = True

    # Hybrid search: BM25 keyword results fused with the dense ones. Off by
    # default for the same reason as the reranker -- with it off the system
    # behaves exactly as the Phase 8 run did, so a forgotten flag cannot
    # quietly contaminate the comparison. Phase 9, D-074.
    hybrid_enabled: bool = False

    # Temporal retrieval: a third arm restricted to chunks whose years overlap
    # the period the question names. Off by default for the same reason as the
    # two above, and for one more -- Phase 22 measured the failure it is meant
    # to fix at two questions out of sixteen, so the default has to be argued
    # from the verdict rather than assumed. Phase 22, D-096.
    temporal_enabled: bool = False

    # The groundedness gate: a second call that checks the draft answer against
    # the sources before it is returned. Off by default for the same reason as
    # the two above -- with it off the system behaves exactly as the run that
    # measured 99.0% faithfulness did, so the before in the before/after is
    # reproducible from a clean checkout. Phase 13, D-084.
    verify_enabled: bool = False

    # Which model checks the answer. Its own setting because a checker from the
    # same family shares the writer's blind spots, and this is the one line that
    # tests that. Defaults to the answering model, so the default carries the
    # bias and says so rather than hiding it -- the same trade as judge_model.
    verify_model: str = "gpt-4.1-mini"

    # Conversation: a follow-up is rewritten into a standalone question before
    # anything is embedded. **On by default, and the only flag here that is.**
    #
    # Every other switch above defaults off so that a clean checkout reproduces
    # the "before" half of its own measurement. That argument does not apply to
    # this one, because a question with no history never reaches the rewriter --
    # measured, not asserted: 0 of the 92 single-turn questions changed a single
    # chunk between runs 2026-08-09T1126Z and 2026-08-09T1341Z. So leaving it
    # off would cost the whole feature and protect nothing. The before half is
    # reproduced by setting this false, and that run is on disk. D-098.
    conversation_enabled: bool = True

    # Which model rewrites the follow-up. Its own setting for the reason
    # verify_model is: rewriting a question and answering one are different
    # jobs, and this is the line that lets a cheaper model do the first.
    rewrite_model: str = "gpt-4.1-mini"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the one Settings instance for this process.

    Cached, so .env is read and validated once rather than on every call.
    Constructed lazily on first call, so importing this module never requires
    a valid environment.
    """
    # Values come from the environment; mypy sees only the synthesised
    # dataclass-style __init__ and cannot know that.
    return Settings()  # type: ignore[call-arg]
