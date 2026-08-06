"""Reading and writing corpus/registry.csv.

These pin the decisions, not Pydantic's behaviour: that the registry
round-trips through CSV without losing types, and that a seed_count which is
not a number is rejected rather than silently coerced.

The seed file's tests live in test_seeds.py.
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from eurohistory_rag.pipeline.bronze.registry import (
    RegistryEntry,
    load_registry,
    write_registry,
)


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
