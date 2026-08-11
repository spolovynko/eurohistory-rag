# The API, as an image. Phase 33.
#
# Build:  docker build -t eurohistory-rag .
# Run:    docker compose up -d          (brings Qdrant with it)
#
# This image serves questions. It does not build the corpus: `curate`, `ingest`,
# `silver`, `chunk` and `index` all run on the host, write into `data/`, and
# `data/` is gitignored and 56,324 chunks large. An image that carried the
# corpus would be an image nobody could pull, so the container talks to a Qdrant
# that someone else filled -- see the "Full build" section of README.md.

# Two stages for one reason: uv, the compilers it may need, and the wheel cache
# are build-time concerns, and none of them should end up in the thing that
# runs. The final image gets the virtual environment and nothing that made it.
FROM python:3.12-slim-bookworm AS build

# Pinned by digest-bearing tag rather than :latest, for the same reason
# uv.lock is committed and compose.yaml pins Qdrant: a rebuild in six months
# must resolve the same way or the lockfile is decoration.
COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /usr/local/bin/uv

# Byte-compile on install and copy rather than link: the venv is about to cross
# a stage boundary, so hardlinks into uv's cache would arrive dangling, and
# compiling here means the first request does not pay for it.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies before source, as their own layer. Source changes every commit
# and the lockfile changes a few times a year; installing them together would
# re-resolve ~400 MB of wheels every time a docstring moved.
#
# --no-dev: pytest, mypy and ruff are how the code is checked, not how it runs.
# --no-install-project: the project itself is deliberately left out here so this
# layer depends on uv.lock alone.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

# Now the project. README.md is copied because pyproject.toml names it as the
# package readme and hatchling refuses to build without it.
#
# --no-editable matters and is not a preference. uv installs the project
# editable by default, which leaves a path pointer to /app/src inside the venv
# rather than the code itself. The venv then crosses into the runtime stage,
# /app/src does not follow it, and the container starts and dies on
# `ModuleNotFoundError: No module named 'eurohistory_rag'`. This built a real
# wheel only after that had happened once.
COPY README.md ./
COPY src/ ./src/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable


FROM python:3.12-slim-bookworm AS runtime

# Not root. Nothing in here needs it, and a container that answers HTTP from the
# public internet is the wrong place to find out that something did.
RUN useradd --create-home --uid 1000 app

WORKDIR /app

# The environment arrives whole from the build stage. Its absolute path is baked
# into the console scripts, so /app/.venv here must match /app/.venv there.
COPY --from=build --chown=app:app /app/.venv /app/.venv

# Three things this process reads from the working directory at runtime, all of
# them small and all of them in git:
#   eval/questions.toml  - the 106 questions, loaded by /eval and the run browser
#   eval/runs/           - 31 saved runs, ~39 MB, which is what makes the page
#                          worth opening without an API key: every past result
#                          is browsable and rescorable offline
#   data/spend/          - the day's spend ledger, written not read; created
#                          empty because a fresh container has spent nothing
COPY --chown=app:app eval/ ./eval/
RUN mkdir -p /app/data/spend && chown -R app:app /app/data

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# The default `.env` says localhost, which inside a container means "this
# container" -- and Qdrant is not in it. Overridden by compose or `-e`.
ENV QDRANT_URL=http://qdrant:6333

USER app
EXPOSE 8000

# /health, not /ready. /ready is 503 whenever Qdrant is unreachable, which is a
# true statement about the system and a false one about this container -- a
# healthcheck on it would have Docker restart a perfectly good API because a
# database is down. That distinction is the whole reason the two endpoints are
# separate; see D-099.
HEALTHCHECK --interval=30s --timeout=3s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health').read()"

# No --reload: it watches the filesystem, and there is nothing here to watch.
# One worker on purpose. The handlers are `def` rather than `async def` because
# they make blocking calls to OpenAI and Qdrant, so FastAPI already runs them on
# a thread pool; adding processes would multiply the reranker's memory by the
# worker count for throughput nobody has asked for.
CMD ["uvicorn", "eurohistory_rag.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
