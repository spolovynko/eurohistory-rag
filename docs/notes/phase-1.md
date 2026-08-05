# Phase 1 notes — FastAPI skeleton and typed config

Reference for the concepts Phase 1 requires. Written against the state of this
repo on 2026-07-30, with fastapi 0.141.1, starlette 1.3.1, uvicorn 0.52.0,
pydantic 2.13.4, pydantic-settings 2.14.2, httpx 0.28.1.

Everything below is grounded in files that exist here — in `src/`, in `tests/`,
or in `.venv/Lib/site-packages/`. Where a path is quoted, go look at it.

---

## What Phase 1 built

| File | Purpose |
|---|---|
| `src/eurohistory_rag/core/config.py` | `Settings` (3 fields) and a cached `get_settings()` |
| `src/eurohistory_rag/core/logging.py` | `configure_logging()` — added later, see Part 6 |
| `src/eurohistory_rag/core/__init__.py` | states the rule: nothing here imports FastAPI |
| `src/eurohistory_rag/api/main.py` | `create_app()`, `GET /health`, module-level `app` |
| `tests/conftest.py` | the `client` fixture — a `TestClient` over a fresh app |
| `tests/api/test_api.py` | `/health` and the generated OpenAPI schema |
| `tests/core/test_config.py` | defaults, secret masking, fail-fast, source precedence, caching |

Dependencies added: `fastapi`, `uvicorn`, `pydantic-settings` to
`[project].dependencies`; `httpx` to `[dependency-groups].dev`, because only
`TestClient` needs it today. Phase 2 moves `httpx` to runtime when it becomes
the Wikipedia client.

Green on all four gates, plus the server verified by hand.

---

## Part 1 — TCP, HTTP, ASGI

Three layers, each hiding the one below it. Worth keeping straight, because
"the server" means something different at each level.

### TCP

The physical network moves packets. Packets get lost, arrive out of order, and
sometimes arrive twice. **TCP is a set of rules that hides all of that**: two
programs open a connection, and afterwards each can write bytes and read bytes
with a guarantee that the other side receives every byte, exactly once, in
order.

Raw packets are a hundred numbered postcards, some of which never arrive. TCP
is a phone call.

Reaching a specific program needs two things: an **IP address** (which machine)
and a **port** (which program on it). `uvicorn --port 8000` claims port 8000.
`http://localhost:6333` in `.env.example` is the same idea aimed at Qdrant.

**The limitation that matters: TCP delivers bytes and nothing else.** It has no
concept of a request, a header, or JSON.

### HTTP

An agreement about what those bytes *say*. Put this on the wire —

```
GET /health HTTP/1.1
Host: localhost:8000
```

— and both ends agree it means "fetch the thing at `/health`". A convention
layered on TCP's pipe, nothing more.

### ASGI

Now two separate jobs appear. Somebody must sit on the port, accept TCP
connections, read raw bytes and recognise them as an HTTP request: that is a
**web server**, and here it is uvicorn. Somebody else must decide that
`/health` answers `{"status": "ok"}`: that is the **application**, and here it
is FastAPI plus the handler.

Different jobs, different packages, different authors. So they need a written
contract, and **ASGI is that contract and nothing more**.

The predecessor was **WSGI** (1997): an application was a plain function taking
`(environ, start_response)`. It worked — it is why gunicorn can run any Flask
or Django app — but it is synchronous by construction. One request holds one
thread start to finish, and there is no way to express a connection that stays
open: no WebSockets, no streaming, no server-sent events.

ASGI is the async successor, and the whole spec is: *an application is an async
callable taking three arguments.* Here is FastAPI actually being one —
`starlette/applications.py:86`:

```python
async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
```

And the three types, `starlette/types.py:12-16`:

```python
Scope   = MutableMapping[str, Any]              # a dict
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]      # await it, get an event in
Send    = Callable[[Message], Awaitable[None]]  # await it, push an event out
```

- `scope` — a dict describing this connection:
  `{"type": "http", "method": "GET", "path": "/health", "headers": [...]}`.
  `type` is `"http"`, `"websocket"` or `"lifespan"`.
- `receive` — await it to pull incoming events (body chunks arriving).
- `send` — await it to push outgoing ones: `{"type": "http.response.start",
  "status": 200}`, then `{"type": "http.response.body", "body": b"..."}`.

**The division of labour.** uvicorn owns the socket, turns bytes into that
`scope` dict, and awaits your app. FastAPI is the callable it awaits — it never
touches a socket, never parses HTTP, and cannot tell whether the bytes came
from TCP, a Unix socket, or a test harness holding it in memory.

Two consequences:

1. `uvicorn eurohistory_rag.api.main:app` is not magic. That string is an
   import path to an **object**, and uvicorn's only requirement is that the
   object be an async callable of three arguments. This is why
   `api/main.py` ends with `app = create_app()` — a factory is a function, and
   there would otherwise be nothing named `app` to import. (`--factory` is the
   alternative; see D-013.)
2. Anything that can await the callable can drive the app. `TestClient` does
   exactly that, with no socket and no port. That is not a testing trick — it
   falls straight out of the contract.

---

## Part 2 — typed configuration

### Why a class instead of `os.environ.get()`

`os.environ.get("QDRANT_URL")` scattered through a codebase has three failure
modes:

- It returns `str | None`, so every call site handles `None` or crashes later
  with something unhelpful.
- Nothing lists what the application needs to run. You find out by grepping.
- A missing variable fails when it is *used* — possibly twenty minutes into an
  ingest run.

`Settings` inverts all three: one declaration of everything required, typed so
mypy checks every use, validated **once at construction** so a missing value
fails immediately with the field named.

### How a value is found

Nothing in `config.py` opens a file. `SettingsConfigDict(env_file=".env")` is
the entire instruction. On `Settings()`, pydantic-settings walks every field,
uppercases the name, and checks sources in a fixed order — **first hit wins**:

| | Source | Example |
|---|---|---|
| 1 | constructor arguments | `Settings(qdrant_url="http://other:6333")` |
| 2 | real environment variables | `QDRANT_URL` in the shell |
| 3 | the `.env` file | the line in `.env` |
| 4 | the field default | `"http://localhost:6333"` |

Reaching the bottom with no default is what raises `ValidationError`. That is
the fail-fast property, and it is entirely a consequence of *not* writing a
default.

The order also explains deployment: `.env` is a local convenience, and
production sets real environment variables that override it without editing
anything.

Two gotchas:

- **`env_file` is resolved relative to the current working directory**, not the
  module. Run from elsewhere and it silently finds nothing.
  `tests/core/test_config.py` weaponises this — `monkeypatch.chdir(tmp_path)`
  is what makes the real `.env` invisible so the missing-field case can be
  tested.
- **Encoding.** Without `env_file_encoding="utf-8"`, python-dotenv opens the
  file in the locale encoding, which on Windows is cp1252.

### `extra="forbid"` is the default

`pydantic_settings/main.py:564`:

```python
model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
    extra='forbid',
    case_sensitive=False,
    ...
)
```

A key in `.env` with no matching field is an **error**, not a silent skip.
(Real OS environment variables are looked up by field name, so extras there are
ignored; the `.env` file is read wholesale, which is why it is different.)

The consequence: `.env.example` and the field list are a contract, and must be
updated in the same commit.

### `SecretStr`

`openai_api_key: SecretStr` renders as `SecretStr('**********')` in every
string form. This matters because Pydantic prints field values in
`ValidationError` messages and FastAPI prints objects in tracebacks — one
unhandled exception with a plain `str` puts the key in a log file. Reading it
requires `.get_secret_value()`, and that friction is deliberate: it makes
reading a secret a visible act.

### `lru_cache` on `get_settings`

`lru_cache` is memoisation. On a **zero-argument** function with `maxsize=1`
there is only one possible call, so the effect is: run once, cache the object,
return the same object thereafter — a lazy singleton built from a stdlib
decorator.

Three things it gives that `settings = Settings()` at module scope does not:

- **Lazy.** A module-level instance is constructed *at import*. Import that
  module for any reason — a test that only wants the class, a CLI needing one
  field — and the environment must be valid or the import raises. With
  `lru_cache` nothing is constructed until someone calls.
- **Overridable.** FastAPI's dependency injection keys on the callable:
  `app.dependency_overrides[get_settings] = lambda: Settings(...)`. A variable
  is not a hook. `get_settings.cache_clear()` also comes free, and
  `tests/core/test_config.py` uses it.
- **Cheap.** Without the cache, every call re-opens `.env` and re-validates.

Importing `get_settings` is free — it binds a name. *Calling* it at module
scope is what re-creates the problem the cache exists to avoid.

### Why mypy demands arguments to `Settings()`

`pydantic/_internal/_model_construction.py:82` decorates the model metaclass:

```python
@dataclass_transform(kw_only_default=True, field_specifiers=(...))
```

That is PEP 681. It tells any type checker: treat classes built by this
metaclass like dataclasses — synthesise `__init__` from the annotated fields.
So mypy believes the signature is:

```python
Settings.__init__(*, openai_api_key: SecretStr, wikipedia_user_agent: str,
                  qdrant_url: str = ...)
```

and reports `Missing named argument` on a bare `Settings()`.

**mypy is statically correct and practically wrong** — the values arrive from
the environment, which no static analyser can see. This is permanent friction
between `pydantic-settings` and strict typing. The repo answers it with a
narrow, commented ignore at the single construction point:

```python
return Settings()  # type: ignore[call-arg]
```

Narrow (`[call-arg]`, not bare), local, and explained. Giving the fields
defaults would silence mypy by throwing away the startup validation.

---

## Part 3 — the application

### Why a factory

`app = FastAPI()` at module scope creates the app **at import time**: exactly
one, made before anyone can influence how. That is fine until a test wants an
app configured differently — a fake OpenAI client, `QdrantClient(":memory:")`,
a `Settings` with a test key. There is no seam; the app already exists when the
test runs, and every test in the process shares it, mutations included.

`create_app()` is a recipe rather than an object. Nothing exists until it is
called, each call is independent, and the arguments are the injection point.
`tests/conftest.py` uses it on day one so no test can leak into another.

### What FastAPI does with type hints

`@app.get("/health")` registers the function against a method and path. Then
FastAPI reads the function's **signature** and derives behaviour from it — that
is the framework's whole design. Parameters become query parameters, path
parameters or request bodies according to their types. The **return
annotation** becomes the response model: FastAPI validates what is returned
against it, serialises to JSON, and publishes it as an OpenAPI schema.

Which is why `/docs` exists without any documentation being written. Here is
`/openapi.json` from this repo:

```json
{"openapi":"3.1.0",
 "info":{"title":"Eurohistory RAG API","version":"0.1.0"},
 "paths":{"/health":{"get":{"summary":"Health check endpoint",
   "description":"Report that the process is alive.\n\nLiveness only: ..."
```

Every piece traces to something in `api/main.py`: `summary` from the decorator
argument, `description` from the **handler's docstring**, `version` from
`eurohistory_rag.__version__`, and the `200` response schema from the
`dict[str, str]` annotation. Nothing was written twice — the API description
*is* the code.

### Liveness vs readiness

`/health` checks nothing downstream, deliberately. *Liveness* asks "is this
process alive?"; *readiness* asks "can it serve traffic — is Qdrant
reachable?". Different consumers: an orchestrator that restarts a container on
a failed liveness probe should not restart it because a dependency is slow.
Deciding this in Phase 1 means Phase 5 adds an endpoint rather than quietly
changing this one's meaning. See D-014.

---

## Part 4 — testing without a server

`TestClient(create_app())` is handed the FastAPI app — the async callable of
three arguments. `client.get("/health")` builds the `scope` dict itself, awaits
the app, collects the events pushed back through `send`, and assembles a
response object. No TCP, no port, nothing to start or stop. It is a function
call dressed as an HTTP request, and it only works because ASGI made the app a
plain callable rather than something welded to a socket.

The practical result: the suite runs in 0.07 s and cannot fail because a port
was busy.

### `conftest.py`

pytest imports it automatically; it is never imported by name and nothing
references it. Fixtures defined there are available to every test in that
directory and below, matched by **parameter name** —
`test_health_returns_ok(client: TestClient)` receives the fixture purely
because the parameter is called `client`.

Two details in the fixture:

- It calls `create_app()`, not the module-level `app`.
- The `with` block runs the ASGI **lifespan**: entering triggers startup,
  leaving triggers shutdown. Nothing registers on startup yet, but Phase 5's
  Qdrant client will, and a test skipping the `with` would run against an app
  whose startup never happened.

### What the config tests actually assert

Not "does Pydantic work" — that is Pydantic's problem. They pin the decisions:
that the default is real, that `SecretStr` keeps the key out of `repr()`, that
a missing required field raises at construction, that an environment variable
beats a default, and that `get_settings()` returns one object. None of them
depend on a developer's own `.env`; a test that passes on one machine and fails
on a clean checkout is not a test.

---

## Part 5 — demonstrated

### The app really is an ASGI callable

```
$ uv run python -c "import inspect; from eurohistory_rag.api.main import app; ..."
type: FastAPI
callable: True
signature: (scope: MutableMapping[str, Any],
            receive: Callable[[], Awaitable[MutableMapping[str, Any]]],
            send: Callable[[MutableMapping[str, Any]], Awaitable[None]]) -> None
is coroutine fn: True
```

Not a description of ASGI — that is the contract, read off the object this repo
serves.

### Source precedence, live

```
$ QDRANT_URL=http://from-the-environment:6333 uv run python -c "..."
openai_api_key=SecretStr('**********')
wikipedia_user_agent='eurohistory-rag/0.1 (...)'
qdrant_url='http://from-the-environment:6333'
```

Three things visible at once: the environment variable beat the field default,
`wikipedia_user_agent` came from `.env`, and `SecretStr` masked the key in a
plain `print()`.

### `extra="forbid"` catching a typo

`config.py` briefly read `opeanai_api_key` — `a` and `n` transposed. One typo,
two errors:

```
pydantic_core.ValidationError: 2 validation errors for Settings
opeanai_api_key
  Field required [type=missing, ...]
openai_api_key
  Extra inputs are not permitted [type=extra_forbidden, ...]
```

Read together they point straight at the mismatch: pydantic looked for
`OPEANAI_API_KEY` and found nothing, then read `.env`, found `OPENAI_API_KEY`,
and had no field for it. With `extra="ignore"` only the first half would have
appeared — and "this obviously-present key is missing" is a much longer
debugging session.

**And the tools said nothing.** `mypy` reported `Success: no issues found`;
ruff passed. `opeanai_api_key: SecretStr` is a perfectly well-typed field, and
the environment is runtime data no static checker can see. This is the ruff/mypy
boundary from `phase-0.md` §"ruff vs mypy", met in real code rather than in an
example.

### The endpoint, over a real socket

```
$ uv run uvicorn eurohistory_rag.api.main:app --port 8123
INFO:     Uvicorn running on http://127.0.0.1:8123
INFO:     127.0.0.1 - "GET /health HTTP/1.1" 200 OK
{"status":"ok"}
INFO:     127.0.0.1 - "GET /docs HTTP/1.1" 200 OK
```

The same app the tests drive in-process, this time with uvicorn holding a real
TCP port in front of it. Identical code, two front doors — which is the point
of Part 1.

---

## Part 6 — logging

Written on 2026-07-31, one phase late. Logging belongs beside `Settings` — both
are cross-cutting startup concerns, set once and used everywhere after — but it
was omitted from the Phase 1 session and only surfaced in Phase 2, when `ingest`
needed to show progress. See D-020.

### The two halves

Python's `logging` splits into two things that are easy to conflate.

| | What it is | Who touches it |
|---|---|---|
| **Logger** | A named object. `logger.info(...)` creates a record and passes it upward. | Every module |
| **Handler** | The thing that actually writes somewhere. | The entry point, once |

`logging.getLogger(__name__)` in `data_ingestion/ingest.py` returns the logger
named `eurohistory_rag.data_ingestion.ingest`. That name is a path: a record
travels up through `eurohistory_rag.data_ingestion`, then `eurohistory_rag`,
then the root logger, and it is the root that owns the handler doing the
writing.

**That is why a library module never calls `basicConfig()`.** `ingest.py` has no
idea whether its caller wants stderr, a file, or silence — a CLI run, a pytest
run and a future FastAPI worker all want different answers. The module emits
records and lets whoever owns the process decide. The alternative shows up
immediately in tests: pytest's `caplog` works by attaching its own handler, which
a library configuring output for itself would fight.

**And why `print()` would have been wrong** in `ingest.py`: no level (nothing to
turn off), no logger name (no idea which module spoke), no timestamp, and it
writes to stdout — mixing a progress line into the stream a caller is parsing.

### The module

`src/eurohistory_rag/core/logging.py` is one function and a handful of
constants. It builds two handlers and gives them **different levels** — that
asymmetry is the whole design:

| Destination | Level | Because |
|---|---|---|
| stderr | INFO, or DEBUG with `--verbose` | You are watching it. Keep it readable. |
| `logs/eurohistory.log` | always DEBUG | Nobody is watching it, and the run worth reading it for is the one that already went wrong. |

So the terminal stays as short as it was before the file existed, while the file
quietly keeps the detail you did not know you would need — which a shell
redirect can never do, because it can only save what was already on screen.

The other decisions:

| | Why |
|---|---|
| Root logger set to `DEBUG` | The root is a gate before the handlers. Left at INFO it would drop DEBUG records before the file handler ever saw them, and per-handler levels would be pointless. |
| Handlers replaced, not added | Configuring twice in one process must not double every line. The old ones are also `close()`d, so a re-run does not leak an open file. |
| `RotatingFileHandler`, 5 MB × 3 | A plain `FileHandler` appends forever. Fine for a CLI run; not fine for the API process, which logs per request and runs until stopped. |
| `log_file: Path \| None` | The opt-out. Tests pass `None`, and it is the only way to get the old stderr-only behaviour. |
| `NOISY_LIBRARIES` as a tuple | The extension point is a list entry, not a code change. |

**`NOISY_LIBRARIES` became load-bearing when the file arrived.** At INFO on
stderr, `httpcore` and `urllib3` were invisible anyway. With a handler recording
everything at DEBUG they would write a line per socket operation, and the file
would be useless within one `index` run. Pinning them to WARNING is what keeps
it readable.

**No `get_logger()` wrapper.** `logging.getLogger(name)` is already a
process-wide registry returning the same object for the same name; wrapping it
adds a layer with no behaviour and hides the name hierarchy that makes
per-module control work. Same reason it is not a singleton class — see D-019.

### Where output goes

Three streams, and keeping them apart is the point:

| Stream | Carries | Written by |
|---|---|---|
| stdout | the command's **result** | `typer.echo` in `cli.py` |
| stderr | diagnostics, INFO and up | the console handler |
| `logs/eurohistory.log` | diagnostics, everything | the rotating file handler |

`logs/` is gitignored — the logs are machine-local and are never shared. Because
result and diagnostics are on different streams, this still works:

```bash
uv run eurohistory ingest > result.txt   # result to a file, logs on screen
```

### One line, read

```
2026-08-05 17:23:54,938 INFO     eurohistory_rag.demo: console and file
```

`LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"` — timestamp,
level padded to 8 so the messages line up, dotted logger name, message. The name
is the whole point: it tells you which module spoke without the message having
to say so.

### Adapting it

Everything below is a change in **one** place.

**Silence a chatty library.** Add it to `NOISY_LIBRARIES` in `core/logging.py`.
It already holds `openai`, `qdrant_client`, `sentence_transformers` and
`transformers` alongside the HTTP stack.

**Turn one of our modules up or down.** Add to `configure_logging()`:

```python
logging.getLogger("eurohistory_rag.pipeline.bronze.wikipedia").setLevel(logging.DEBUG)
```

Nothing in `wikipedia.py` changes. This is what the `__name__` hierarchy buys —
and `"eurohistory_rag.pipeline"` would catch the whole package at once.

**Move, or switch off, the log file.** `LOG_FILE` in `core/logging.py` is the
default; `configure_logging(log_file=None)` drops the handler entirely. If the
path ever needs to differ per machine, it becomes a `Settings` field — that is
the one change here that would not stay inside this module.

**See DEBUG.** `uv run eurohistory --verbose ingest`. The flag sits on the Typer
`@app.callback()`, not on each command, so one definition covers `curate`,
`ingest` and every command Phases 3-8 add. Cost: it comes *before* the command
name, like `git --no-pager log`.

**Log from a new module.** Two lines, forever:

```python
logger = logging.getLogger(__name__)   # module top
logger.info("fetched %d rows", n)      # at the event
```

Note `%d`, not an f-string. The placeholder form passes the value to logging,
which only builds the string if a handler will emit it — an f-string builds it
every time, including when the level filters the record out. It also keeps the
message *template* constant across records, which is what log aggregation groups
on.

**Configure the API entry point.** Still not done. `create_app()` is the right
place, but `configure_logging` clears existing handlers — including the one
pytest's `caplog` installs — so every test that builds an app would lose it.
It needs a fixture that accounts for that, which is exactly what
`tests/core/test_logging.py` does for this module.

### What each module logs

The ingestion path, as built in Phase 2 (the levels, and the reasoning for each,
are in `plan.md`'s Phase 1 section). Every module added since — silver, gold,
index, retrieval, generation, eval — carries its own
`logging.getLogger(__name__)` on the same pattern; 15 modules do as of Phase 8:

| Logger | Level | Event |
|---|---|---|
| `registry` | INFO | seeds path + theme count; registry path + entry count |
| `curate` | INFO | per theme: seeds fetched, links extracted, candidates kept |
| | ERROR | a seed title Wikipedia has no page for — then raises |
| `ingest` | INFO | run start: entries, already in Bronze, batch size |
| | INFO | per batch: theme, asked, got, progress |
| | WARNING | a registry entry Wikipedia has no page for |
| | INFO | run end: written / skipped / missing, duration |
| `wikipedia` | WARNING | retry: attempt, delay, what failed |
| | ERROR | retries exhausted |
| `bronze` | DEBUG | file written: path, rows, bytes |

Two details worth knowing:

**The retry WARNING sits at the `sleep`, not at the failure.** The failure is
detected at the bottom of the loop; the delay is only decided at the top of the
next one. Logging there gets status, attempt and delay on one line —
`retry 2/4 in 2s after HTTP 503`.

**`ingest` times with `time.monotonic()`, not `datetime.now()`.** Monotonic only
counts forward; a wall clock can jump backwards when NTP corrects it, printing a
negative duration. `fetched_at` stays wall-clock because it is *data* — it
answers how stale the copy is.

### Arguable

`wikipedia._get` and `curate.curate_theme` both log an ERROR immediately before
raising, so the same words appear twice on stderr — once as a log line, once in
the traceback. It follows the Phase 1 spec, and four WARNINGs closed by a
matching ERROR reads as one story in the log where a traceback reads as a
separate event. Dropping both is defensible; dropping one is not.
