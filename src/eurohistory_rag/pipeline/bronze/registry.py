"""Read the seed list and the curated title registry."""

import csv
import logging
import tomllib
from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

logger = logging.getLogger(__name__)

REGISTRY_FIELDS = ("theme", "title", "seed_count")


class Theme(BaseModel):
    """One theme and the survey articles curation starts from."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Becomes the Bronze `theme` value and a partition directory name, so it is
    # constrained to characters that are safe in a path.
    slug: str = Field(pattern=r"^[a-z0-9-]+$")
    name: str
    seeds: tuple[str, ...] = Field(min_length=1)


class _SeedFile(BaseModel):
    """The file as a whole, so the top-level shape is validated too."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    theme: tuple[Theme, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _slugs_are_unique(self) -> "_SeedFile":
        """Two themes sharing a slug would silently merge in Bronze."""
        slugs = [t.slug for t in self.theme]
        duplicates = sorted({s for s in slugs if slugs.count(s) > 1})
        if duplicates:
            raise ValueError(f"duplicate theme slugs: {', '.join(duplicates)}")
        return self


def load_seeds(path: Path) -> tuple[Theme, ...]:
    """Parse corpus/seeds.toml into Themes, in file order.

    Validation happens here and only here: _SeedFile.model_validate is what runs
    the field constraints and the uniqueness check, so building Themes by hand
    anywhere else would bypass all of it.
    """
    with path.open("rb") as f:
        raw = tomllib.load(f)
    themes = _SeedFile.model_validate(raw).theme
    logger.info("seeds: %s, %d themes", path, len(themes))
    return themes


class RegistryEntry(BaseModel):
    """One row of corpus/registry.csv -- one article to ingest."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    theme: str = Field(pattern=r"^[a-z0-9-]+$")
    title: str = Field(min_length=1)
    # Review metadata: how many seeds linked to this. ingest ignores it.
    seed_count: int = Field(ge=1)


def write_registry(path: Path, entries: Iterable[RegistryEntry]) -> None:
    """Write the curated candidate list, overwriting any existing file."""
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=REGISTRY_FIELDS)
        writer.writeheader()
        for entry in entries:
            writer.writerow(entry.model_dump())


def load_registry(path: Path) -> tuple[RegistryEntry, ...]:
    """Read the reviewed, committed registry. The only input ingest reads."""
    with path.open(encoding="utf-8", newline="") as f:
        entries = tuple(RegistryEntry.model_validate(row) for row in csv.DictReader(f))
    logger.info("registry: %s, %d entries", path, len(entries))
    return entries
