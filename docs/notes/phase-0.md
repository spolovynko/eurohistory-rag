# Phase 0 notes — project skeleton

Reference for the concepts Phase 0 requires. Written against the state of this
repo on 2026-07-30, with uv 0.11.6, CPython 3.12.12, ruff 0.16.0, mypy 2.3.0,
pytest 9.1.1.

Everything below is grounded in files that exist in this repo. Where a path is
quoted, go look at it.

---

## What Phase 0 built

| File | Purpose |
|---|---|
| `pyproject.toml` | metadata, build backend, ruff/mypy/pytest config, dev deps |
| `src/eurohistory_rag/__init__.py` | the package; `__version__` only |
| `tests/test_smoke.py` | asserts the package *imports* — only possible if installed |
| `.env.example` | `OPENAI_API_KEY`, `QDRANT_URL`, `WIKIPEDIA_USER_AGENT`; unread until Phase 1 |
| `README.md` | setup, commands, one reason per folder |
| `uv.lock` | 14 packages, exact versions and hashes |

Green on all four gates: `pytest`, `ruff check`, `ruff format --check`,
`mypy --strict`.

---

## Part 1 — `pyproject.toml`, block by block

### `[project]`

Standard metadata (PEP 621) — the same keys whether the tool is uv, poetry, or
pip. `name` is the *distribution* name (what you would `pip install`).
`requires-python` is a hard gate: uv refuses to build an environment that
violates it. `dependencies` is what the code needs **at runtime**.

Without it, nothing knows what this project is called or what it needs, and
`uv sync` has nothing to install.

### `[build-system]`

```toml
requires = ["hatchling"]
build-backend = "hatchling.build"
```

Says: *to turn this source tree into an installable wheel, install `hatchling`
in a scratch environment and call it.* This is the PEP 517 contract that lets
any tool build any project without knowing anything about it in advance.

**This is why it matters even though nothing here is published to PyPI.**
`uv sync` installs *this project itself* into the venv, and that requires
building it. The evidence:

```
.venv/Lib/site-packages/eurohistory_rag-0.1.0.dist-info
.venv/Lib/site-packages/_editable_impl_eurohistory_rag.pth
```

`eurohistory-rag` is a real installed package in that environment, exactly like
pytest is. Remove `[build-system]` and the PEP 517 fallback is legacy
setuptools, which knows nothing about `src/` layout — the result is an empty
install or a build error.

### `[tool.hatch.build.targets.wheel]`

```toml
packages = ["src/eurohistory_rag"]
```

Backend-specific: *when building the wheel, ship this directory.* Hatchling can
often infer it (`eurohistory-rag` normalises to `eurohistory_rag`), but
inference is undesirable in the file that defines the package boundary. The
classic failure without it is a wheel that installs cleanly and contains **no
code**.

### `[dependency-groups]`

```toml
dev = ["mypy>=2.3.0", "pytest>=9.1.1", "ruff>=0.16.0"]
```

The block worth sitting with. Against `[project].dependencies`:

|  | `[project].dependencies` | `[dependency-groups]` |
|---|---|---|
| Answers | "what does this need to **run**?" | "what is needed to **work on** it?" |
| Ships in the wheel | yes | **no** |
| A consumer installing the package gets it | yes | no |
| Standard | PEP 621 | PEP 735, local-only |

Nobody running the RAG needs ruff; they need `fastapi`. Dev tools in
`dependencies` means every consumer downloads a linter they will never run, and
in a container image that is real weight for nothing.

`uv sync` installs the dev group by default; `uv sync --no-dev` gives the
production set. That flag is the entire point of the split.

### `[tool.ruff]`

```toml
line-length = 88
target-version = "py312"
```

`line-length` drives both the formatter and the `E501` lint rule.
`target-version` tells ruff which syntax is legal here — it is what lets the
`UP` rules rewrite `Optional[str]` to `str | None` and know that is safe.

### `[tool.ruff.lint]`

```toml
select = ["E", "F", "I", "UP", "B", "SIM"]
```

Ruff's default is only `E4, E7, E9, F` — deliberately timid. Each code is an
upstream tool ruff reimplemented:

| Code | Origin | Catches |
|---|---|---|
| `E` | pycodestyle | style and whitespace |
| `F` | Pyflakes | **real bugs** — undefined names, unused imports |
| `I` | isort | import ordering |
| `UP` | pyupgrade | syntax outdated for `target-version` |
| `B` | flake8-bugbear | likely bugs — mutable default args, loop-variable capture |
| `SIM` | flake8-simplify | needless complexity |

`F` and `B` catch actual defects. The rest keep diffs clean.

### `[tool.mypy]`

```toml
python_version = "3.12"
strict = true
files = ["src", "tests"]
```

`strict = true` is a bundle, flipping on roughly a dozen flags at once. The
significant ones: `disallow_untyped_defs` (every function annotated),
`disallow_any_generics` (bare `list` rejected, `list[str]` required), and
`warn_return_any`.

`files` is why bare `uv run mypy` works. A CLI path overrides it, so
`uv run mypy src` works too.

Starting strict is deliberate: adding types to 40 existing files is miserable,
never letting them go untyped is free.

### `[tool.pytest.ini_options]`

```toml
testpaths = ["tests"]
```

Bare `pytest` walks `tests/` and nothing else. Without it, collection starts at
the repo root and descends into `.venv/` — 75 MB of other people's test files —
and `data/`. Speed, and no accidental collection.

---

## Part 2 — the four concepts

### What a virtual environment physically is

Not a sandbox, not a container, not process isolation. **A directory and a
config file.**

```
.venv/
├── pyvenv.cfg            <- the entire mechanism
├── Scripts/              <- python.exe + shims: pytest.exe, ruff.exe, mypy.exe
└── Lib/site-packages/    <- the packages
```

`pyvenv.cfg`, verbatim from this repo:

```ini
home = C:\Users\User\AppData\Roaming\uv\python\cpython-3.12-windows-x86_64-none
implementation = CPython
uv = 0.11.6
version_info = 3.12.12
include-system-site-packages = false
prompt = eurohistory-rag
```

The mechanism: when CPython starts it looks for `pyvenv.cfg` next to its own
executable. If found, it sets `sys.prefix` to that directory and builds
`sys.path` from *that* `site-packages` rather than the global one.
`include-system-site-packages = false` makes machine-wide installs invisible.
That is the whole trick.

Two details in that file worth catching:

- `version_info = 3.12.12`, but the system `python --version` reports
  **3.12.10**. uv downloaded and used *its own* CPython from
  `AppData\Roaming\uv\python\`. This project's Python is pinned independently of
  anything installed system-wide.
- The venv is 75.5 MB and installed in 1.11 seconds. uv keeps one global wheel
  cache and **hardlinks** into the venv instead of copying. Deleting `.venv` and
  re-syncing is nearly free — treat it as disposable and never put anything in
  it by hand.

**What `uv sync` did, in order:** created `.venv/`, resolved the constraints
into one exact set, wrote `uv.lock`, hardlinked 14 packages from the cache into
`site-packages/`, and built and installed `eurohistory-rag` itself in editable
mode.

### Why `src/` layout

It prevents one specific failure: **tests that pass against code that would
never ship.**

Without `src/`, `eurohistory_rag/` sits at the repo root. Running pytest from
that root puts the root on `sys.path`, so `import eurohistory_rag` resolves to
the *source folder on disk* whether or not the package is correctly installed.
Forget a subpackage in the wheel, forget an `__init__.py`, misconfigure the
build backend — tests stay green and users get `ModuleNotFoundError`.

With `src/`, the repo root contains nothing importable. `import eurohistory_rag`
can only work through an install. That is why `tests/test_smoke.py` is worth
more than it looks: it is an assertion that packaging is correct.

Editing stays instant, via the `.pth` file:

```
$ cat .venv/Lib/site-packages/_editable_impl_eurohistory_rag.pth
C:\Projects\eurohistory-rag\src
```

A `.pth` file in `site-packages` is read at interpreter startup and each line is
appended to `sys.path`. So `src/` is on the path — but it got there through the
*install*, not through the shell's working directory.

### What `uv.lock` is

`pyproject.toml` states a **constraint**. `uv.lock` states the **answer**.

```toml
# pyproject.toml -- a range; infinitely many valid solutions
"ruff>=0.16.0"
```

```toml
# uv.lock -- one exact answer, with integrity hashes
name = "ruff"
version = "0.16.0"
sdist = { url = "https://files.pythonhosted.org/.../ruff-0.16.0.tar.gz",
          hash = "sha256:e460aafd5495ec89efaa6ced2e4a9a581116451e1c88b9d37ef497e0f8e93982" }
wheels = [ ... linux_armv6l, macosx_10_12_x86_64, macosx_11_0_arm64, manylinux_aarch64, ... ]
```

272 lines for 14 packages. It locks wheels for **every platform**, not just
Windows, so a collaborator on macOS resolves to an identical version set.

**Why it is committed.** Without it, `uv sync` today yields ruff 0.16.0 and
`uv sync` in four months yields 0.19 with new lint rules enabled — the build
breaks on a commit that changed nothing. The lockfile makes installs
deterministic across machines and across time. The hashes add supply-chain
integrity: a tampered artifact fails its checksum instead of executing.

General rule: **applications commit lockfiles, libraries usually do not** (a
library must work across a range, so pinning is the consumer's job). This is an
application.

### `ruff` vs `mypy`

Different questions entirely.

**ruff** reads one file's syntax tree. Fast, no cross-file reasoning. It asks:
*is this line wrong or ugly?*

**mypy** builds a whole-program model, follows imports, infers types, and checks
them across function boundaries. It asks: *do these two places agree about what
this value is?*

Ruff catches, mypy does not:

```python
import os          # F401 unused import -- mypy is entirely fine with this

def f(items=[]):   # B006 mutable default argument -- a real bug, correctly typed
    ...
```

mypy catches, ruff does not:

```python
def word_count(text: str) -> int:
    return text.split()        # returns list[str], declared int
```

Ruff sees nothing wrong: valid syntax, every name used, imports sorted. mypy
reports `Incompatible return value type (got "list[str]", expected "int")`. More
importantly it catches the *cross-file* version — `chunk.py` passing `None` into
a function in `embed.py` annotated `str` — which no single-file linter can see.

Neither subsumes the other.

---

## Part 3 — the same four ideas, demonstrated

Everything above is theory. Here is each claim actually tested in this repo, with
real output.

### Uninstalling the package breaks exactly one of the three tools

```
$ uv pip uninstall eurohistory-rag
Uninstalled 1 package in 4ms
 - eurohistory-rag==0.1.0 (from file:///C:/Projects/eurohistory-rag)
```

Then, with the source files completely untouched:

```
=== pytest ===
tests\test_smoke.py:8: in <module>
    import eurohistory_rag
E   ModuleNotFoundError: No module named 'eurohistory_rag'
1 error in 0.10s

=== ruff ===
All checks passed!

=== mypy ===
Success: no issues found in 1 source file
```

**Only pytest broke.** That split is the whole lesson:

- **pytest** genuinely *imports* the code. Import goes through `sys.path`, which
  now has no route to `src/` because the `.pth` file went away with the install.
  So pytest is testing the *installed package*, which is the point.
- **ruff** never imports anything. It parses files as text into a syntax tree.
  Files on disk are unchanged, so ruff is unaffected — and this is also the
  reason ruff cannot see across files.
- **mypy** reads the source of `src/` as given on the command line and does not
  need the package importable to analyse it.

Had this been a root-level layout instead of `src/`, pytest would have passed
too — silently importing the folder off disk — and a broken package would have
shipped green. That is the failure mode `src/` exists to prevent, and it is
visible in six lines of output.

Restoring is one command, because the lockfile already holds the answer:

```
$ uv sync
Resolved 14 packages in 1ms
Installed 1 package in 6ms
 + eurohistory-rag==0.1.0
$ uv run pytest -q
1 passed in 0.01s
```

### ruff and mypy, two more cases

Ruff objects, mypy does not:

```python
d = {}
for k in d.keys():          # SIM118: use `for k in d` instead
    print(k)
```

Nothing here is a type error. mypy is content.

mypy objects, ruff does not:

```python
def load_titles(path: str) -> list[str]:
    return path.read_text().splitlines()
```

`str` has no `.read_text()` — that is a `Path` method, and this is the mistake
you will actually make in Phase 2. Ruff sees a syntactically perfect function
with every name used. mypy reports `"str" has no attribute "read_text"`.

### Where `fastapi` goes in Phase 1

`[project].dependencies` — the API cannot run without it, so it is a runtime
dependency. If it went into `dependency-groups.dev` instead, `uv sync` would
still install it locally and everything would appear to work; the breakage
arrives later, when `uv sync --no-dev` or a container build produces an
environment where `import fastapi` fails at startup. Misplaced dev deps are
harmless locally and fatal in deployment, which is what makes them easy to get
wrong.

### The lockfile holds packages nobody asked for

Only three were requested: `mypy`, `pytest`, `ruff`. Fourteen were installed.
The other ten are transitive dependencies, and `uv.lock` records who pulled each
one in:

```toml
name = "pytest"
dependencies = [
    { name = "colorama", marker = "sys_platform == 'win32'" },
    { name = "iniconfig" },
    { name = "packaging" },
    { name = "pluggy" },
    { name = "pygments" },
]

name = "mypy"
dependencies = [
    { name = "ast-serialize" },
    { name = "librt", marker = "platform_python_implementation != 'PyPy'" },
    { name = "mypy-extensions" },
    { name = "pathspec" },
    { name = "typing-extensions" },
]
```

Two things worth noticing. `colorama` carries
`marker = "sys_platform == 'win32'"` — it is in the lock for everyone, but only
*installs* on Windows. That is how one lockfile stays valid across platforms.
And `ruff` appears with no dependencies at all: it is a single Rust binary, which
is why it runs in milliseconds.

The general shape: `pyproject.toml` holds what *you* asked for, `uv.lock` holds
the full closure — your requests plus everything they dragged along, pinned and
hashed.
