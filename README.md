# eurohistory-rag

A retrieval-augmented generation system over a thematic history of Europe in
the 20th and 21st centuries, built from English Wikipedia via the MediaWiki
API.

Built phase by phase as a learning project. The deliverable is understanding,
not the system.

## Setup

```bash
uv sync                 # create .venv and install from uv.lock
cp .env.example .env    # then fill in your keys
```

## Development

```bash
uv run pytest           # tests
uv run ruff check .     # lint
uv run ruff format .    # format
uv run mypy             # types
```

## Layout

| Path | Why it exists |
|---|---|
| `src/eurohistory_rag/` | The package. Under `src/` so tests import the *installed* package, never loose files in the repo root. |
| `tests/` | Outside the package, so tests ship with the repo but not with the wheel. |
| `data/bronze/` | Raw wikitext as fetched. Immutable, append-only, the only irreplaceable layer. |
| `data/silver/` | Cleaned, typed, deduplicated documents. A cache — delete and rebuild freely. |
| `data/gold/` | Chunks, ready to embed. Also a cache. |
| `docs/` | Plan, roadmap, progress, decisions. |

`data/` is gitignored in full, so a fresh clone will not have those three
directories. Code that writes to them creates them.
