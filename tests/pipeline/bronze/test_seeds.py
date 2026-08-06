"""Reading and validating corpus/seeds.toml.

These pin the decisions, not Pydantic's behaviour: that a bad slug is rejected
because slugs become directory names, and that duplicate slugs are caught
because two themes would silently merge in Bronze.
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from eurohistory_rag.pipeline.bronze.seeds import load_seeds

VALID_SEEDS = """
[[theme]]
slug = "interwar"
name = "Interwar period"
seeds = ["Weimar Republic", "Stalinism"]

[[theme]]
slug = "wwii-and-holocaust"
name = "Second World War"
seeds = ["Nazi Germany"]
"""


def write_seeds(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "seeds.toml"
    path.write_text(content, encoding="utf-8")
    return path


def test_load_seeds_returns_themes_in_file_order(tmp_path: Path) -> None:
    themes = load_seeds(write_seeds(tmp_path, VALID_SEEDS))

    assert [t.slug for t in themes] == ["interwar", "wwii-and-holocaust"]
    assert themes[0].seeds == ("Weimar Republic", "Stalinism")
    assert themes[0].name == "Interwar period"


def test_seeds_are_a_tuple_not_a_list(tmp_path: Path) -> None:
    """Immutable, so a caller cannot append and confuse the next one."""
    themes = load_seeds(write_seeds(tmp_path, VALID_SEEDS))

    assert isinstance(themes[0].seeds, tuple)


@pytest.mark.parametrize(
    ("slug", "reason"),
    [
        ("Interwar", "capital letter"),
        ("inter war", "space"),
        ("inter_war", "underscore"),
        ("interwar/1939", "path separator"),
    ],
)
def test_slug_must_be_path_safe(tmp_path: Path, slug: str, reason: str) -> None:
    """The slug becomes a partition directory name, so it is constrained."""
    content = f'[[theme]]\nslug = "{slug}"\nname = "x"\nseeds = ["a"]\n'

    with pytest.raises(ValidationError, match="slug"):
        load_seeds(write_seeds(tmp_path, content))


def test_duplicate_slugs_are_rejected(tmp_path: Path) -> None:
    """Two themes sharing a slug would silently merge into one Bronze partition."""
    content = (
        '[[theme]]\nslug = "interwar"\nname = "a"\nseeds = ["x"]\n\n'
        '[[theme]]\nslug = "interwar"\nname = "b"\nseeds = ["y"]\n'
    )

    with pytest.raises(ValidationError, match="duplicate theme slugs: interwar"):
        load_seeds(write_seeds(tmp_path, content))


def test_misspelled_key_names_both_problems(tmp_path: Path) -> None:
    """extra='forbid' turns one typo into two errors that read together."""
    content = '[[theme]]\nslug = "interwar"\nname = "x"\nseed = ["a"]\n'

    with pytest.raises(ValidationError) as exc:
        load_seeds(write_seeds(tmp_path, content))

    message = str(exc.value)
    assert "Field required" in message  # seeds is missing
    assert "Extra inputs are not permitted" in message  # seed is not a field


def test_theme_with_no_seeds_is_rejected(tmp_path: Path) -> None:
    content = '[[theme]]\nslug = "interwar"\nname = "x"\nseeds = []\n'

    with pytest.raises(ValidationError, match="seeds"):
        load_seeds(write_seeds(tmp_path, content))


def test_file_with_no_themes_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="theme"):
        load_seeds(write_seeds(tmp_path, "# nothing here\n"))
