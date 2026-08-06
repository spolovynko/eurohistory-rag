"""Read and write corpus/registry.csv -- the reviewed list ingest works from.

The seed file lives in seeds.py. These were one module until Phase 14; they
owned two file formats, so they had two reasons to change.
"""

import csv
import logging
from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

REGISTRY_FIELDS = ("theme", "title", "seed_count")


class RegistryEntry(BaseModel):
    """One row of corpus/registry.csv -- one article to ingest."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    theme: str = Field(pattern=r"^[a-z0-9-]+$")
    title: str = Field(min_length=1)
    # Review metadata: how many seeds linked to this. ingest ignores it.
    seed_count: int = Field(ge=1)


def write_registry(path: Path, entries: Iterable[RegistryEntry]) -> None:
    """Write the curated candidate list, overwriting any existing file.

    Overwriting is why `curate` is run against one seed file at a time when a
    theme is added: re-curating every theme would discard the hand review that
    turned the previous draft into the committed registry. See D-086.
    """
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
