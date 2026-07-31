"""Reading and validating the two corpus files.

These pin the decisions, not Pydantic's behaviour: that a bad slug is rejected
because slugs become directory names, that duplicate slugs are caught because
two themes would silently merge in Bronze, and that the registry round-trips
through CSV without losing types.
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from eurohistory_rag.pipeline.bronze.registry import (
    RegistryEntry,
    load_registry,
    load_seeds,
    write_registry,
)

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


def test_registry_round_trips_through_csv(tmp_path: Path) -> None:
    """Non-ASCII survives, and seed_count comes back as int rather than str."""
    path = tmp_path / "registry.csv"
    entries = [
        RegistryEntry(
            theme="wwi-and-aftermath", title="Treaty of Sèvres", seed_count=4
        ),
        RegistryEntry(theme="interwar", title="Weimar Republic", seed_count=2),
    ]

    write_registry(path, entries)
    loaded = load_registry(path)

    assert loaded == tuple(entries)
    assert loaded[0].title == "Treaty of Sèvres"
    assert isinstance(loaded[0].seed_count, int)


def test_registry_header_is_written_even_for_no_entries(tmp_path: Path) -> None:
    path = tmp_path / "registry.csv"

    write_registry(path, [])

    assert path.read_text(encoding="utf-8").strip() == "theme,title,seed_count"
    assert load_registry(path) == ()


def test_registry_rejects_a_non_numeric_seed_count(tmp_path: Path) -> None:
    path = tmp_path / "registry.csv"
    path.write_text("theme,title,seed_count\ninterwar,Weimar,four\n", encoding="utf-8")

    with pytest.raises(ValidationError, match="seed_count"):
        load_registry(path)


def test_registry_rejects_an_unexpected_column(tmp_path: Path) -> None:
    """A column added during hand review fails loudly rather than being ignored."""
    path = tmp_path / "registry.csv"
    path.write_text(
        "theme,title,seed_count,notes\ninterwar,Weimar,2,keep\n", encoding="utf-8"
    )

    with pytest.raises(ValidationError, match="notes"):
        load_registry(path)
