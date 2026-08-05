"""BM25 weighting: the tokenizer, the word ids, and the two vector builders.

Pure functions with no store and no network, so these are cheap and exact. The
tests worth having here are the ones that would catch a silent poisoning of all
30,362 chunks: a tokenizer that drops years, an id that moves between runs, and
a weight that ignores chunk length.
"""

from eurohistory_rag.retrieval.sparse import (
    average_length,
    document_vector,
    query_vector,
    term_index,
    tokenize,
)

# --- tokenize ---------------------------------------------------------------


def test_tokenize_lowercases_and_splits_on_punctuation() -> None:
    assert tokenize("Treaty of Trianon, signed 1920.") == [
        "treaty",
        "of",
        "trianon",
        "signed",
        "1920",
    ]


def test_tokenize_keeps_years() -> None:
    """A history corpus is asked about dates constantly; digits are terms."""
    assert "1945" in tokenize("Europe in 1945")


def test_tokenize_splits_hyphens_and_underscores() -> None:
    assert tokenize("Brest-Litovsk") == ["brest", "litovsk"]
    assert tokenize("cold_war") == ["cold", "war"]


def test_tokenize_empty_text() -> None:
    assert tokenize("   ") == []


# --- term_index -------------------------------------------------------------


def test_term_index_is_stable() -> None:
    """The whole index depends on this. A salted hash would fail silently."""
    assert term_index("trianon") == term_index("trianon")
    assert term_index("trianon") == 3728728011


def test_term_index_separates_words() -> None:
    assert term_index("trianon") != term_index("versailles")


def test_term_index_fits_an_unsigned_32_bit_slot() -> None:
    """Qdrant addresses sparse dimensions with a uint32."""
    assert 0 <= term_index("versailles") < 2**32


# --- average_length ---------------------------------------------------------


def test_average_length_is_the_mean_token_count() -> None:
    assert average_length([["a", "b"], ["c", "d", "e", "f"]]) == 3.0


def test_average_length_of_an_empty_corpus() -> None:
    assert average_length([]) == 0.0


# --- document_vector --------------------------------------------------------


def test_document_vector_is_keyed_by_term_id() -> None:
    vector = document_vector(["trianon"], corpus_average_length=1.0)
    assert set(vector) == {term_index("trianon")}


def test_document_vector_of_an_empty_chunk() -> None:
    assert document_vector([], corpus_average_length=10.0) == {}


def test_repeating_a_word_raises_its_weight() -> None:
    once = document_vector(["trianon"], 4.0)[term_index("trianon")]
    twice = document_vector(["trianon", "trianon"], 4.0)[term_index("trianon")]
    assert twice > once


def test_repetition_saturates() -> None:
    """K1 exists so a word spammed four times is not worth four mentions."""
    once = document_vector(["trianon"], 4.0)[term_index("trianon")]
    four = document_vector(["trianon"] * 4, 4.0)[term_index("trianon")]
    assert four < 4 * once


def test_a_longer_chunk_earns_less_for_the_same_mention() -> None:
    """B exists so a long chunk cannot win on volume. Same one mention, twice
    the length, lower weight."""
    short = document_vector(["trianon"] + ["filler"] * 3, 8.0)
    long = document_vector(["trianon"] + ["filler"] * 15, 8.0)
    assert long[term_index("trianon")] < short[term_index("trianon")]


def test_document_vector_without_a_corpus_average() -> None:
    """An empty corpus must not divide by zero; the length penalty drops out."""
    assert document_vector(["trianon"], corpus_average_length=0.0) == {
        term_index("trianon"): 1.0
    }


# --- query_vector -----------------------------------------------------------


def test_query_vector_weights_every_word_once() -> None:
    vector = query_vector("Why did Trianon matter?")
    assert set(vector.values()) == {1.0}
    assert term_index("trianon") in vector


def test_query_vector_ignores_repetition() -> None:
    """A question is short; saying a word twice in it means nothing."""
    assert query_vector("trianon trianon") == query_vector("Trianon")


def test_query_vector_of_an_empty_question() -> None:
    assert query_vector("") == {}
