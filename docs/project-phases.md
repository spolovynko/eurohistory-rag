# Project phases

<details>
<summary><strong>Phase 0 — Project foundation</strong></summary>

### Definition

Phase 0 is the project-skeleton phase that establishes the development environment, package structure and quality checks. It creates the foundation on which every later component will be built. No ingestion, retrieval, generation or other RAG functionality is implemented yet.

### Use

Phase 0 creates a stable and reproducible foundation for the project. It organizes the codebase and establishes standard commands for installation, testing and validation. It is complete when the package imports successfully and pytest, Ruff and strict mypy all pass.

### Tech stack

- **Python 3.12** — needed to implement the application in a modern, typed language; alternatives include Python 3.11 or another backend language.
- **`src/` layout** — stores the application under `src/eurohistory_rag/`, ensuring tests import the installed package instead of loose repository files. This catches packaging mistakes early and keeps tests outside the distributed package. The simpler alternative is a top-level package directory.
- **`pyproject.toml`** — the central configuration file for project metadata, dependencies, package building, pytest, Ruff and mypy. It is needed to keep setup information in one standard file instead of spreading it across several tool-specific files. Alternatives include `setup.py`, `setup.cfg` and separate `requirements.txt` files.
- **uv** — a virtual environment is an isolated folder containing the Python interpreter and packages used only by this project. `uv sync` creates or updates `.venv` and installs the exact dependency versions recorded in `uv.lock`, making the environment reproducible. Alternatives include `pip` with `venv`, Poetry and PDM.
- **`uv.lock`** — a lockfile records the exact versions and integrity hashes of all direct and indirect dependencies. It ensures every machine installs the same packages instead of resolving potentially different versions from the ranges in `pyproject.toml`. Alternatives include `poetry.lock`, `pdm.lock` and a hash-pinned `requirements.txt`.
- **Hatchling** — needed to build and install the package correctly from the `src/` directory with minimal configuration; alternatives include Setuptools, Flit and Poetry Core.

**Important commands**

- `uv sync` — create or update the virtual environment from `uv.lock`.
- `uv run pytest` — run the automated tests inside the project environment.
- `uv run ruff check .` — find linting and code-quality problems.
- `uv run ruff format --check .` — verify formatting without changing files.
- `uv run mypy src` — run static type checking on the application code.
- `uv build` — build the installable package through Hatchling.
- `git status` — show modified, staged and untracked files.
- `git diff` — inspect changes before staging or committing them.
- `git add <file>` and `git commit -m "message"` — stage reviewed changes and record them in repository history.
- `git log --oneline` — view the project’s commit history in a compact form.

### Frameworks

- **pytest** — needed to verify behaviour and prevent regressions through concise tests, fixtures and clear failure reports; alternatives include `unittest` and Nose2.
- **Ruff** — needed to keep code consistent and catch common mistakes through fast linting and formatting; alternatives include Flake8, Black and isort.
- **mypy** — needed to catch incompatible types and interfaces before the code runs; alternatives include Pyright and Pyre.

</details>

<details>
<summary><strong>Phase 1 — API, configuration and logging</strong></summary>

### Definition

Phase 1 introduces the HTTP boundary, typed configuration and application logging. It creates a minimal FastAPI application with `GET /health`, generated OpenAPI documentation and configuration tests, but deliberately excludes ingestion, retrieval, authentication and RAG endpoints so the web framework can be understood independently. Logging belongs to this foundation but was completed during Phase 2 after ingestion exposed the need for progress diagnostics.

### Use

- Confirm that the API process is alive without checking external dependencies; liveness stays separate from readiness so an orchestrator does not restart a healthy process merely because Qdrant is unavailable.
- Load and validate required configuration before long-running work begins.
- Keep secrets outside source code and mask them in logs and error messages.
- Separate framework-independent `core/` code from FastAPI-specific `api/` code.
- Build independent applications with `create_app()` so tests cannot leak state into one another.
- Test API endpoints without starting a real server or opening a TCP port.
- Provide consistent terminal and file logging for every later phase.

### Tech stack

- **ASGI** — the standard interface connecting the Python web application to its server. It is needed so the same application can run behind Uvicorn and inside an in-process test client. WSGI is the older synchronous alternative.
- **Uvicorn** — the ASGI server that opens a TCP port and runs the FastAPI application. It is needed because FastAPI defines the application but does not serve network requests by itself. Alternatives include Hypercorn and Daphne.
- **Environment variables and `.env`** — store machine-specific configuration and secrets outside source code. Values are resolved in the order constructor arguments → real environment variables → `.env` → field defaults, so tests can override configuration and deployments can take priority over local settings without editing code. Alternatives include configuration files and managed secret stores.
- **Python logging** — records timestamped diagnostic events with levels and module names. Every module uses `logging.getLogger(__name__)`, while only process entry points configure handlers, because reusable modules must not decide whether their caller wants terminal output, a file or silence. It keeps command results on stdout, live diagnostics on stderr and detailed history in rotating log files; alternatives include structlog and Loguru.

**Important commands**

- `uv run uvicorn eurohistory_rag.api.main:app --reload` — run the development API and restart it after Python changes.
- Open `http://127.0.0.1:8000/health` — verify that the process is alive.
- Open `http://127.0.0.1:8000/docs` — inspect the OpenAPI documentation generated from endpoint types and docstrings.
- `uv run pytest tests/api tests/core` — run the Phase 1 API and configuration tests.
- `Get-Content logs/eurohistory.log -Wait` — follow the detailed log file in PowerShell.

### Frameworks

- **FastAPI** — defines typed HTTP endpoints and uses function annotations and docstrings to validate responses and generate OpenAPI documentation automatically. This keeps the executable endpoint contract and `/docs` in one place, preventing a separately written schema from becoming outdated. It was selected for its type-driven validation and small amount of setup; alternatives include Flask, Django and Starlette.
- **Pydantic Settings** — converts environment values into one validated, typed `Settings` object and fails immediately when required values are missing. `get_settings()` constructs this object lazily and caches it, avoiding configuration failures during import and repeated `.env` validation while remaining replaceable in tests. `SecretStr` masks the OpenAI key and `extra="forbid"` catches misspelled `.env` keys; alternatives include Dynaconf, environs and direct `os.environ` access.
- **Starlette TestClient and httpx** — call the ASGI application directly and return HTTP-style responses without running Uvicorn. They are needed for fast, isolated endpoint tests that cannot fail because a port is busy. The alternative is starting a real test server and calling it with an HTTP client.

</details>

<details>
<summary><strong>Phase 2 — Bronze ingestion</strong></summary>

### Definition

Phase 2 builds the immutable Bronze data layer by fetching raw article revisions from the English Wikipedia MediaWiki API. Curation first creates a reviewable title registry from hand-picked seed articles, and ingestion then downloads only that committed registry. The result is raw wikitext with provenance that every later data layer can rebuild from.

### Use

- Define the corpus explicitly instead of crawling Wikipedia without a boundary.
- Preserve article IDs, revision IDs, timestamps, themes, licence and unmodified wikitext.
- Resume safely after interruption by skipping title-and-theme pairs already stored.
- Retry temporary HTTP failures while recording permanently missing titles separately.
- Keep Bronze append-only so later cleaning mistakes never destroy the source.

### Tech stack

- **MediaWiki API** — supplies versioned Wikipedia wikitext and provenance through a documented HTTP interface. It was selected over pre-cleaned datasets because the project needed both reproducible revisions and realistic cleaning work. Alternatives include Wikimedia dumps and the Hugging Face Wikipedia dataset.
- **TOML and CSV** — `seeds.toml` stores hand-written themes, while `registry.csv` stores the generated and manually reviewed title list. Separating them makes corpus discovery repeatable without making every ingest depend on the current state of Wikipedia. Alternatives include JSON, YAML or a database table.
- **Parquet Bronze storage** — writes typed, compressed batches partitioned by ingest date. A new file per batch makes interrupted runs recoverable and avoids rewriting irreplaceable source data. Alternatives include JSONL, a relational database or object storage.

**Important commands**

- `uv run eurohistory curate` — generate candidate titles from the seed articles.
- `uv run eurohistory ingest` — download committed registry titles into Bronze.
- `uv run eurohistory --verbose ingest` — run ingestion with DEBUG diagnostics on the terminal.

### Frameworks

- **httpx** — performs synchronous MediaWiki requests with timeouts and retry handling. Serial requests were sufficient because Wikipedia accepts batches of up to 50 titles. Alternatives include Requests and aiohttp.
- **Typer** — exposes typed `curate` and `ingest` commands with generated help. It was selected to keep CLI definitions close to ordinary Python functions. Alternatives include Click and `argparse`.
- **Polars** — enforces the Bronze schema and writes compressed Parquet efficiently. Alternatives include pandas with PyArrow and DuckDB.
- **mwparserfromhell** — parses seed-article wikitext so curation can extract real article links instead of relying on regular expressions. Alternatives include wikitextparser and MediaWiki’s rendered-HTML API.
- **Pydantic** — validates seed and registry rows before network work begins. Alternatives include dataclasses with manual validation and Marshmallow.

</details>

<details>
<summary><strong>Phase 3 — Silver transformation</strong></summary>

### Definition

Phase 3 transforms raw Bronze wikitext into clean, typed Silver documents. One Silver row represents one meaningful level-two article section, with article metadata stored beside readable prose. Silver is a rebuildable cache, not a replacement for Bronze.

### Use

- Remove templates, references, tables and non-content links that would pollute embeddings.
- Preserve visible link text while storing link targets, categories and infobox values as metadata.
- Deduplicate articles that entered through several themes by stable `page_id`.
- Drop redirects, disambiguation pages, list-like pages, apparatus sections and very short remnants.
- Create sections that are narrow enough to represent one topic before chunking.

### Tech stack

- **Silver Parquet schema** — stores section text, identifiers, themes, links, categories, infobox data and revision provenance in one typed table. A flat table is easy to rebuild and query, while Bronze remains the recovery source. Alternatives include nested JSON documents and relational tables.
- **Section-level document IDs** — combine stable article identity with section position. Sections were chosen because whole Wikipedia articles cover too many subjects to embed as one document. Alternatives include article-level documents and splitting at every heading depth.
- **Full rebuild strategy** — overwrites the single Silver file because the transformation is deterministic and inexpensive compared with downloading Bronze again. Incremental updates would add state and deduplication complexity without protecting irreplaceable data.

**Important commands**

- `uv run eurohistory silver` — rebuild Silver from every Bronze partition.
- `uv run pytest tests/pipeline/silver` — run the cleaning, metadata and section tests.

### Frameworks

- **mwparserfromhell** — traverses wikitext nodes so markup can be removed or preserved by meaning rather than by fragile text replacement. Alternatives include wikitextparser and parsing MediaWiki HTML.
- **Polars** — scans every Bronze file, groups duplicate articles and enforces the fourteen-column Silver schema. Alternatives include pandas, PyArrow and DuckDB.
- **Python dataclasses** — represent immutable Silver rows before they become a dataframe, giving mypy a precise transformation contract. Alternatives include Pydantic models and plain dictionaries.

</details>

<details>
<summary><strong>Phase 4 — Gold chunking</strong></summary>

### Definition

Phase 4 converts Silver sections into Gold chunks, the units that will be embedded, retrieved and cited. Chunks are limited to about 1,200 body characters with 150 characters of sentence-aligned overlap. Every embedded chunk begins with its article title and section heading so it remains understandable outside its original page.

### Use

- Prevent long sections from being reduced to one diluted embedding.
- Keep related prose together by preferring paragraph boundaries, then sentences, then words.
- Preserve claims that cross a boundary through controlled overlap.
- Carry citation metadata and stable `chunk_id` values into retrieval.
- Rebuild Gold quickly whenever chunking rules change.

### Tech stack

- **Hierarchical text splitting** — fills chunks with paragraphs and falls back to sentences or words only when necessary. This respects boundaries written by the article’s authors better than fixed-character cuts. Alternatives include token-only, recursive library and semantic chunkers.
- **Character budget** — uses 1,200 body characters as a simple, model-independent approximation of roughly 300 tokens. It is easier to inspect than tokenizer-specific limits, though token-based sizing is more exact.
- **Sentence-aligned overlap** — repeats up to 150 characters from the previous body without cascading overlap forward. Alternatives include no overlap, exact-character overlap and percentage overlap.
- **Gold Parquet schema** — stores one typed row per chunk and can be overwritten because it is fully derivable from Silver. Alternatives include JSONL and writing chunks directly into the vector database.

**Important commands**

- `uv run eurohistory chunk` — rebuild Gold with the configured defaults.
- `uv run eurohistory chunk --size 1200 --overlap 150` — run an explicit chunk configuration.
- `uv run pytest tests/pipeline/gold` — verify splitting, overlap and storage rules.

### Frameworks

- **Python regular expressions** — provide the small sentence splitter used for this history corpus without adding a language-processing dependency. Alternatives include spaCy, NLTK and model tokenizers.
- **Polars** — reads Silver, enforces the Gold schema and writes the complete chunk table in seconds. Alternatives include pandas and PyArrow.
- **Python dataclasses** — define immutable `Chunk` objects that are type-checked before storage. Alternatives include Pydantic and plain dictionaries.

</details>

<details>
<summary><strong>Phase 5 — Embeddings, Qdrant and search</strong></summary>

### Definition

Phase 5 turns Gold chunks into searchable vectors and introduces `GET /search`. Each chunk receives a 1,536-dimensional OpenAI embedding and is stored in Qdrant with the metadata required for filtering, display and permanent citations. `SearchService` hides provider-specific objects from the rest of the application.

### Use

- Retrieve passages by semantic similarity rather than exact word matching.
- Rebuild or resume the index in controlled batches.
- Return project-owned `SearchResult` objects instead of leaking Qdrant types.
- Reduce overlapping duplicates by over-fetching and keeping at most two chunks per section.
- Keep `/health` as liveness and add `/ready` for Qdrant availability.

### Tech stack

- **OpenAI `text-embedding-3-small`** — creates 1,536-dimensional semantic vectors shared by documents and questions. It was selected for one hosted SDK and predictable output dimensions. Alternatives include local Sentence Transformers, Cohere embeddings and fastembed.
- **Qdrant** — stores dense vectors, payloads and indexes with cosine similarity and HNSW approximate search. Its in-memory mode permits realistic offline tests, which was a major reason for choosing it. Alternatives include pgvector, FAISS, Chroma, Milvus and managed vector stores.
- **Docker Compose** — runs a pinned Qdrant version with persistent named storage. It makes the local database reproducible without installing Qdrant directly. Alternatives include a native binary, Kubernetes and a managed service.
- **UUID5 point IDs** — deterministically convert human-readable chunk IDs into IDs Qdrant accepts. Alternatives include sequential integers and random UUIDs, which are harder to resume safely.

**Important commands**

- `docker compose up -d` — start Qdrant with persistent storage.
- `docker compose ps` — inspect the Qdrant container’s state.
- `uv run eurohistory index` — recreate and populate the vector collection.
- `uv run eurohistory index --resume` — continue an interrupted indexing run.
- Open `/ready` — verify that Qdrant and the collection are reachable.
- Open `/search?q=Why%20was%20the%20Berlin%20Wall%20built&k=5` — inspect retrieved chunks.

### Frameworks

- **OpenAI Python SDK** — batches embedding requests and standardizes retryable API failures. Alternatives include direct HTTP calls and other embedding-provider SDKs.
- **qdrant-client** — creates collections, upserts vectors and performs searches while containing every Qdrant import in one module. Alternatives follow the chosen vector store, such as psycopg for pgvector.
- **FastAPI dependency injection** — builds and caches the search stack while allowing tests to replace it with fakes. Alternatives include manual service construction in handlers and external dependency-injection containers.

</details>

<details>
<summary><strong>Phase 6 — Grounded generation</strong></summary>

### Definition

Phase 6 adds the generation part of RAG through `POST /ask`. The answering model receives only the question and numbered retrieved source blocks, and must cite factual claims inline or refuse when the sources are insufficient. The response maps citation markers back to the exact indexed Wikipedia revisions.

### Use

- Convert retrieved passages into a concise answer rather than exposing search results alone.
- Require inline citations so every factual claim can be checked against a passage.
- Support full answers, partial answers and honest refusals through one ordered prompt rule.
- Combine facts across sources without inventing unsupported connections.
- Return only cited sources, including their text and permanent revision URLs.

### Tech stack

- **OpenAI `gpt-4.1-mini`** — generates grounded answers at temperature zero for more repeatable evaluation. It replaced `gpt-5-mini`, which could not use the required temperature setting under the tested call. Alternatives include `gpt-4o-mini`, local language models and other hosted providers.
- **Markdown system prompt** — stores grounding, citation and refusal rules as a package resource that can be reviewed independently from Python code. Alternatives include a Python string, Jinja templates and external prompt management.
- **XML-like source blocks** — wrap each passage with a short numeric ID and title so boundaries remain clear inside long context. Alternatives include Markdown headings and real chunk IDs.
- **Inline `[n]` citations** — connect each claim to the numbered source immediately after it. End-of-answer bibliographies are easier to generate but harder to verify claim by claim.

**Important commands**

- `uv run uvicorn eurohistory_rag.api.main:app --reload` — run the answer API.
- `./scripts/ask.ps1 "Why was the Berlin Wall built?"` — ask and inspect an answer from PowerShell.
- `uv run pytest tests/generation tests/api` — run generation and endpoint tests without model calls.

### Frameworks

- **OpenAI Python SDK** — sends chat-completion requests and normalizes provider failures behind a `Generator` protocol. Alternatives include direct HTTP and provider-specific SDKs.
- **FastAPI and Pydantic** — validate the `/ask` request, serialize the answer and publish its schema. Alternatives include Flask with manual validation and Django REST Framework.
- **Python Protocols and dataclasses** — separate the answering service from its concrete model client and make tests use small fakes. Alternatives include abstract base classes and mocking the OpenAI SDK directly.

</details>

<details>
<summary><strong>Phase 7 — Repeatable evaluation</strong></summary>

### Definition

Phase 7 creates the first repeatable evaluation of the complete RAG system. Thirty corpus-verified questions measure retrieval, generation, refusals, latency and token cost while preserving every observation in an immutable run directory. From this phase onward, improvements must start from a named failure and end with a measured verdict.

### Use

- Separate retrieval failures from generation failures.
- Compare what the model sees at rank 5 with what retrieval found by rank 20.
- Measure recall, coverage, MRR, refusal behaviour, citations, latency and token usage.
- Store questions, retrieved passages and answers so metrics can be checked by reading evidence.
- Recompute corrected metrics offline without paying for another model run.

### Tech stack

- **TOML question set** — stores hand-written questions, types and expected Silver section IDs in a reviewable format. Section IDs survive re-chunking better than chunk IDs. Alternatives include JSON, YAML and an evaluation database.
- **JSONL evaluation records** — preserve one structured observation per question while remaining streamable and diffable. Alternatives include Parquet, CSV and a relational database.
- **Immutable run directories** — keep `meta.json`, `records.jsonl`, `summary.txt` and `transcript.txt` together under a timestamp. Overwriting one results file would destroy the baseline required for comparisons.
- **Rank-based metrics** — use recall@5, recall@20, coverage@5 and MRR because they answer different questions about presence, completeness and order. Exact-answer scoring alone cannot diagnose retrieval.

**Important commands**

- `uv run eurohistory evaluate` — run every question through retrieval and generation; this spends API money.
- `uv run eurohistory rescore eval/runs/<run-id>` — recompute metrics from stored observations for free.
- Open `eval/runs/<run-id>/transcript.txt` — read answers beside the passages supplied to them.

### Frameworks

- **Pydantic** — validates the human-edited question file and prevents malformed answer keys from silently entering a run. Alternatives include JSON Schema and manual parsing.
- **Typer** — exposes evaluation and rescoring through typed commands. Alternatives include Click and `argparse`.
- **Python dataclasses** — define frozen records and run metadata independently of API response models. Alternatives include Pydantic models and plain dictionaries.
- **Existing SearchService and GenerationService** — the evaluator calls the same production services instead of implementing a second RAG path. An external evaluation framework was rejected because it would obscure and potentially duplicate these mechanics.

</details>

<details>
<summary><strong>Phase 8 — Cross-encoder reranking</strong></summary>

### Definition

Phase 8 adds a local cross-encoder that jointly reads each question-and-passage pair and reorders the top twenty candidates. It targets the Phase 7 gap where recall@20 was 100% but recall@5 was only 75%. The measured headline did not improve, and the phase exposed serious wiring and model-validation failures.

### Use

- Improve ordering when the correct passage is already present in the candidate pool.
- Keep dense retrieval fast by applying the expensive joint model only to twenty candidates.
- Record a separate rerank score without overwriting the original cosine score.
- Fall back to dense order if the local reranker is unavailable.
- Preserve the negative result: recall@5 stayed at 75%, coverage and MRR fell, and the original reranker behaved incorrectly on real examples.

### Tech stack

- **Bi-encoder plus cross-encoder architecture** — the embedding model finds candidates cheaply, while the cross-encoder scores question-and-passage pairs more precisely. Running a cross-encoder over the full corpus would be impractically slow. Alternatives include dense retrieval alone, late-interaction models and hosted reranking APIs.
- **Fixed twenty-passage rerank pool** — keeps the answer path and evaluator on the same candidate population. Deriving the pool from requested `k` had made production and evaluation measure different systems.
- **Local model weights** — avoid a paid network call per candidate and keep passages on the machine. Alternatives include Cohere Rerank, Jina AI rerankers and other hosted services.

**Important commands**

- Set `RERANKER_ENABLED=true` and choose `RERANKER_MODEL` in `.env` — enable a measured reranking configuration.
- `uv run eurohistory evaluate` — compare the reranked configuration with the saved baseline.
- `uv run pytest tests/retrieval/test_search.py` — verify reranking, fallback and pool wiring.

### Frameworks

- **Sentence Transformers** — loads cross-encoder models and scores question-passage pairs locally. Alternatives include raw Transformers, ONNX Runtime and hosted reranking SDKs.
- **PyTorch and Transformers** — provide the model runtime used underneath Sentence Transformers. Alternatives include TensorFlow, ONNX and provider APIs.
- **Python Protocols** — let tests supply a deterministic fake reranker and keep `SearchService` independent of Sentence Transformers. Alternatives include abstract base classes and direct model mocking.

</details>

<details>
<summary><strong>Phase 9 — Hybrid search</strong></summary>

### Definition

Phase 9 combines dense semantic search with BM25 keyword search and merges their rankings using reciprocal rank fusion. It was intended to rescue exact names, dates and treaty terms that embeddings might underweight. Every retrieval metric worsened, so hybrid search remained implemented but disabled by default.

### Use

- Retrieve both semantically similar passages and passages sharing rare exact terms.
- Preserve dense and sparse scores separately because their numeric scales are not comparable.
- Fuse rankings by position rather than guessing a score-normalization formula.
- Diagnose configuration behaviour through a free retrieval-only sweep.
- Retain a reproducible experimental arm while shipping dense-only retrieval as the default.

### Tech stack

- **BM25 sparse vectors** — weight terms by frequency, rarity and document length without a trained model. Alternatives include TF-IDF, Elasticsearch/OpenSearch BM25 and learned sparse retrieval.
- **Reciprocal rank fusion** — adds `1 / (k + rank)` across ranked lists so incomparable cosine and BM25 scores never need to be added directly. Alternatives include score normalization, weighted sums and learned fusion.
- **Stable hashed term IDs** — map tokens into Qdrant’s sparse-vector index without Python’s process-randomized `hash()`. Alternatives include a stored vocabulary and a dedicated search engine.

**Important commands**

- `uv run eurohistory index` — rebuild the collection with dense and sparse vectors.
- Set `HYBRID_ENABLED=true` — enable BM25 plus reciprocal-rank fusion for an experiment.
- `uv run eurohistory evaluate` — measure the hybrid configuration against the baseline.

### Frameworks

- **qdrant-client** — stores dense and sparse vectors in one collection and searches each representation. Alternatives include Elasticsearch/OpenSearch or separate vector and keyword databases.
- **Python standard library** — implements tokenization, hashing, BM25 weights and fusion explicitly so the learning-critical algorithm remains visible. Alternatives include rank-bm25 and retrieval frameworks such as LangChain.

</details>

<details>
<summary><strong>Phase 10 — Evaluation hardening</strong></summary>

### Definition

Phase 10 improves the evaluation instrument instead of changing the RAG answer path. It adds retrieval sweeps, synthetic regression questions, a claim-level faithfulness judge and probes whose correct outcomes are known in advance. The judge initially failed its own probes, demonstrating why an evaluator must be validated before its scores are trusted.

### Use

- Diagnose many retrieval configurations without paying for generation each time.
- Require control rows to reproduce known runs before a sweep can be interpreted.
- Generate additional regression alarms without presenting synthetic questions as human quality evidence.
- Split answers into claims and check each claim against the passages the model received.
- Probe the judge with supported and unsupported examples before evaluating a saved run.

### Tech stack

- **Retrieval-only sweep records** — reuse saved questions and expected sections while skipping generation. This makes broad configuration diagnosis free apart from question embeddings. Alternatives include repeated full evaluations and external tuning platforms.
- **Synthetic TOML questions** — store model-generated questions beside their source section for reproducible regression checks. Human-written evaluation remains necessary because source-derived questions are naturally easier.
- **JSONL judgements** — keep claim-level verdicts beside, but separate from, immutable evaluation observations. This allows the judge prompt to improve without rewriting the original run.
- **Probe set** — contains manually labelled supported and unsupported claims, preventing a judge that always returns one verdict from appearing accurate.

**Important commands**

- `uv run eurohistory sweep --baseline eval/runs/<run-id>` — compare retrieval configurations without generation.
- `uv run eurohistory synthesize` — create synthetic regression questions; this spends API money.
- `uv run eurohistory judge-probe` — verify the judge before using it.
- `uv run eurohistory judge eval/runs/<run-id>` — write claim-level faithfulness results for a saved run.

### Frameworks

- **OpenAI model as judge** — extracts claims and evaluates them against supplied passages. It was used only after probes forced the model to quote the supporting sentence before deciding. Alternatives include human review, NLI models and rule-based checks.
- **Pydantic** — validates synthetic questions and probes, including the rule that probe expectations cannot all be identical. Alternatives include JSON Schema and manual validation.
- **Existing evaluation services** — sweeps call the same search code and compare control configurations against known runs. External evaluation suites were avoided to keep the measurement path inspectable.

</details>

<details>
<summary><strong>Phase 11 — Grounding the joins between facts</strong></summary>

### Definition

Phase 11 changes one prompt rule after the faithfulness judge found seven unsupported connections between otherwise supported facts. The model is instructed to treat causal, comparative and relationship words as claims requiring source support. Unsupported claims fell from seven to three while retrieval stayed identical.

### Use

- Prevent the model from inventing causes, contrasts or generalizations between true facts.
- Make connective words such as “because,” “both” and “rather than” part of grounding review.
- Demonstrate a one-failure, one-change, before-and-after improvement cycle.
- Preserve the limitation that prompt instructions reduce errors but cannot guarantee correctness.

### Tech stack

- **Versioned Markdown system prompt** — adds the grounding rule in the same inspectable prompt used by production and evaluation. Alternatives include application-side post-processing and a second verification call.
- **Saved faithfulness records** — compare changed claims against the earlier run while retrieval acts as an unchanged control. Alternatives include judging only aggregate answers or relying on anecdotal examples.

**Important commands**

- `uv run eurohistory evaluate` — create the after run using the revised prompt.
- `uv run eurohistory judge-probe` — confirm the judge still passes before comparison.
- `uv run eurohistory judge eval/runs/<run-id>` — measure changed unsupported claims.

### Frameworks

- **OpenAI generation model** — applies the revised instruction during the existing answer call; no new runtime dependency was introduced. Alternatives include constrained generation and a verifier model.
- **OpenAI judge workflow** — measures claim-level effects rather than assuming the prompt wording worked. Alternatives include a permanently human-labelled answer set and NLI scoring.

</details>

<details>
<summary><strong>Phase 12 — Per-article thinning experiment</strong></summary>

### Definition

Phase 12 tests whether one Wikipedia article should be prevented from occupying most of the five prompt slots. Several per-section and per-article caps were swept without changing production code. Article diversity increased, but expected-section coverage fell, so the cap was not shipped.

### Use

- Measure whether repeated articles, rather than poor ranking, caused multi-source failures.
- Compare caps of three, two and one against the existing section cap and no cap.
- Show that diversity is an intermediate property, not the product goal.
- Record that the available prompt slots were not the main retrieval bottleneck.

### Tech stack

- **Greedy thinning by `page_id`** — walks ranked candidates in order and limits chunks from the same article. Alternatives include maximal marginal relevance, clustering and learned diversification.
- **Retrieval-only configuration sweep** — measures recall, coverage, MRR and distinct articles without paying for generation. Alternatives include one full run per cap value.
- **Saved baseline records** — provide the candidate lists needed to test post-retrieval policies reproducibly.

**Important commands**

- `uv run eurohistory sweep --baseline eval/runs/<run-id>` — compare thinning configurations offline.
- Inspect the per-question sweep rows — verify which expected section was promoted and which was evicted.

### Frameworks

- **Python standard library** — implements greedy, order-preserving thinning as a small function with no new dependency. Alternatives include diversification libraries and vector-store grouping features.
- **Existing evaluation metrics** — coverage@5 and distinct articles@5 price the benefit and cost separately. Recall alone is too generous for questions expecting several sections.

</details>

<details>
<summary><strong>Phase 13 — Runtime groundedness verifier</strong></summary>

### Definition

Phase 13 adds an optional second model pass that checks a completed answer against its sources before returning it. The verifier corrected or removed unsupported claims, but it also deleted a supported fact, tripled latency and roughly doubled token usage. It was built and tested but left disabled by default.

### Use

- Test whether answer-time verification can catch errors that writing-time prompt rules miss.
- Preserve the original draft whenever the verifier changes an answer so revisions can be inspected.
- Measure firing rate, correctness, latency and token cost rather than faithfulness alone.
- Demonstrate that an apparently safer second model call can reduce useful information or introduce its own error.

### Tech stack

- **Verification Markdown prompt** — asks a model to revise only unsupported claims using the same sources as the writer. Alternatives include per-claim verification, NLI models and offline review.
- **Optional `VERIFY_ENABLED` configuration** — keeps the experimental path reproducible while preserving the measured default. A hardwired verifier would impose cost and latency on every request.
- **Draft-and-revision record** — stores both texts only when a change occurs, enabling direct qualitative review.

**Important commands**

- Set `VERIFY_ENABLED=true` — enable the runtime gate for an experiment.
- `uv run eurohistory evaluate` — measure the verified answer path.
- `uv run eurohistory judge eval/runs/<run-id>` — compare claim-level outcomes.

### Frameworks

- **OpenAI Python SDK** — runs the verifier through the same provider-independent `Generator` interface as answering. Alternatives include another model provider and a local NLI model.
- **Python dataclasses** — carry the revised text, change flag and token counts without coupling verification to FastAPI. Alternatives include Pydantic response models.

</details>

<details>
<summary><strong>Phase 14 — Corpus expansion</strong></summary>

### Definition

Phase 14 expands the corpus from three themes ending in 1945 to nine themes covering 1914–2024. Bronze articles increased from 664 to 1,274 and Gold chunks from 30,362 to 54,903. The old evaluation did not move because it contained no answerable questions about the newly added period.

### Use

- Align the actual corpus with the project’s stated twentieth- and twenty-first-century scope.
- Reuse the immutable Bronze-to-Gold pipeline rather than creating a second ingestion path.
- Reveal that an evaluation only measures the part of the corpus represented by its questions.
- Detect that four previously unanswerable questions had become answerable after expansion.
- Show that corpus changes require evaluation-set changes as well as re-indexing.

### Tech stack

- **Expanded `seeds.toml` and `registry.csv`** — add six curated themes while retaining the reviewable corpus boundary. Alternatives include unrestricted categories and automatic topic expansion.
- **Append-only Bronze plus rebuildable Silver and Gold** — downloads only new source articles, then rebuilds derived layers consistently. A destructive single-table pipeline would make this expansion riskier.
- **Full vector re-index** — embeds the expanded Gold corpus into one comparable Qdrant collection. Alternatives include separate collections per era and federated retrieval.

**Important commands**

- `uv run eurohistory curate` — generate candidate titles for the new themes.
- `uv run eurohistory ingest` — append reviewed new articles to Bronze.
- `uv run eurohistory silver` and `uv run eurohistory chunk` — rebuild derived data.
- `uv run eurohistory index` — recreate the expanded vector collection; this spends embedding money.
- `uv run eurohistory evaluate` — test whether the existing evaluation can observe the expansion.

### Frameworks

- **Existing MediaWiki, Polars and Qdrant pipeline** — scales the corpus without adding another storage or retrieval framework. The absence of new code is a feature: the original data architecture supports expansion.
- **Evaluation reports** — compare the old question population before and after the corpus change, revealing the measurement gap rather than a retrieval defect.

</details>

<details>
<summary><strong>Phase 15 — Evaluation-set repair</strong></summary>

### Definition

Phase 15 adds thirty questions covering the six newly introduced themes and reports old, new and combined suites separately. The original thirty remain byte-identical as a control. The work also exposes that ground truth inferred from samples can be wrong even when its schema is valid.

### Use

- Make evaluation coverage match the expanded corpus coverage.
- Replace refusal tests whose answers now exist in the corpus.
- Keep the original suite unchanged so earlier runs remain comparable.
- Report suite-specific results instead of allowing one historical period to hide another.
- Treat answer-key validation as part of evaluation engineering.

### Tech stack

- **Suite field in `questions.toml`** — labels golden and extended populations while retaining one question file and one runner. Alternatives include separate files and separate evaluation commands.
- **Corpus-verified section IDs** — ground expected results in complete Silver sections rather than topic guesses or short regex windows. Alternatives include article titles, chunk IDs and model-generated keys.
- **Multi-suite reports** — render each suite and the combined population so controls and new coverage remain visible.

**Important commands**

- `uv run eurohistory evaluate` — run both golden and extended suites.
- `uv run eurohistory rescore eval/runs/<run-id>` — regenerate corrected suite metrics offline.
- Read the changed-question transcripts — verify every expected section and refusal against the source.

### Frameworks

- **Pydantic question models** — validate suite names, question types, expected sections and unanswerable-question rules. Alternatives include manual TOML validation.
- **Existing evaluation report layer** — adds grouped summaries without changing retrieval or generation code, preserving the control path.

</details>

<details>
<summary><strong>Phase 16 — Noise-floor measurement</strong></summary>

### Definition

Phase 16 runs the unchanged sixty-question system three times to measure how far generation and judge metrics move when nothing was changed. Retrieval ranks were stable, while unsupported-claim counts varied by four and the judge contradicted itself on repeated claims. This establishes the minimum movement required before a generation result can be interpreted.

### Use

- Distinguish a real improvement from ordinary model variation.
- Establish noise floors for unsupported claims, faithfulness and fully faithful answers.
- Confirm that rank-based retrieval metrics are deterministic enough for strict comparison.
- Measure disagreement introduced by the model-based judge itself.
- Discover a false defect manufactured by the claim splitter dropping qualifiers.

### Tech stack

- **Repeated immutable runs** — hold question, source and configuration constant while resampling generation. Alternatives include assuming temperature zero is deterministic and using a single baseline.
- **Per-claim cross-run comparison** — matches identical claims and sources to identify judge disagreement directly. Aggregate averages would hide which component moved.
- **Minimum detectable effect thresholds** — record the observed spread rather than selecting convenient regression tolerances.

**Important commands**

- `uv run eurohistory judge-probe` — validate the judge before each measurement series.
- `uv run eurohistory evaluate` — repeat the unchanged question set.
- `uv run eurohistory judge eval/runs/<run-id>` — produce comparable claim verdicts.

### Frameworks

- **Existing OpenAI generation and judge models** — are intentionally rerun unchanged so their natural variation becomes measurable. Alternatives include deterministic local models and human-only assessment.
- **Python evaluation utilities** — compare records and claims offline without modifying the RAG system or adding a statistics framework.

</details>

<details>
<summary><strong>Phase 17 — Regression gate and CI</strong></summary>

### Definition

Phase 17 creates an offline command that compares a baseline run with a candidate and fails when protected behaviour regresses. It also adds free continuous integration for linting, formatting, typing, tests and a pinned published baseline. Paid model evaluation remains a deliberate release step because CI has no corpus, Qdrant index or API budget.

### Use

- Refuse metric comparison until run configurations and question populations are comparable.
- Require intentional differences to be declared and verify that each declared change actually occurred.
- Gate deterministic retrieval and behavioural regressions while reporting noisy generation and latency metrics.
- Prove the alarm works using a deliberately damaged copy of a real run.
- Prevent later metric-code changes from silently rewriting historical results.

### Tech stack

- **Offline gate reports** — compare saved JSON records and exit non-zero on protected regressions. Alternatives include paid evaluation on every commit and a hosted evaluation platform.
- **Pinned baseline test** — locks published figures to a specific immutable run so metric changes become explicit review events.
- **GitHub Actions CI** — runs every check that needs no model, database or secret on each push. Alternatives include GitLab CI, Azure Pipelines and local-only hooks.

**Important commands**

- `uv run eurohistory gate <baseline-run> <candidate-run>` — compare two saved runs for free.
- `uv run eurohistory gate <baseline-run> <candidate-run> --changed <field>` — declare an intentional configuration difference.
- `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .` and `uv run mypy` — reproduce the free CI gate locally.

### Frameworks

- **GitHub Actions** — executes repository quality checks automatically after code changes. Alternatives include other CI services and pre-commit-only enforcement.
- **Typer** — exposes the gate as a typed command with a meaningful process exit code. Alternatives include a standalone script and Click.
- **Python dataclasses** — represent individual checks and the final verdict in a testable, framework-independent form. Alternatives include Pydantic models and dictionaries.

</details>

<details>
<summary><strong>Phase 18 — Front end</strong></summary>

### Definition

Phase 18 adds a browser interface served by the existing FastAPI application. A person can ask a question, read the answer, inspect cited passages and browse saved evaluation runs without using a terminal. The page calls the same `/ask` path measured by evaluation, so presentation code cannot quietly create a second RAG system.

### Use

- Make the system usable and presentable outside scripts and API documentation.
- Render inline citation markers that link directly to the passage cards and permanent Wikipedia revisions.
- Distinguish an honest corpus refusal from an infrastructure failure.
- Display evaluation metrics and per-question outcomes for saved runs.
- Observe user-facing failures, including cold-start delay, that aggregate evaluation had hidden.

### Tech stack

- **HTML** — defines one accessible page with ask and evaluation views. A single static document was sufficient for the application’s state and avoided a separate build pipeline. Alternatives include server templates and a single-page application.
- **CSS** — provides responsive layout, dark mode, status states and matching colours between citations and passage cards. Alternatives include Tailwind CSS and component-library styles.
- **JavaScript ES modules** — separate asking, controls, evaluation, experiment and DOM responsibilities without a framework. Alternatives include React, Vue and Svelte.
- **Fetch and DOM APIs** — call FastAPI and build output using elements and text nodes, preventing corpus text from becoming executable HTML. Alternatives include Axios and UI-framework request layers.

**Important commands**

- `uv run uvicorn eurohistory_rag.api.main:app --reload` — start the API and page.
- Open `http://127.0.0.1:8000/` — use the ask interface.
- Open `http://127.0.0.1:8000/#eval` — browse saved evaluation runs.
- Restart Uvicorn after static-file edits — the current static resources are read at import and may otherwise remain stale.

### Frameworks

- **Vanilla browser APIs** — provide routing, requests and rendering with no new dependency or build step. A front-end framework would add value only after the interface gained enough shared state or components to justify it.
- **FastAPI HTML and static responses** — serve the page and packaged assets from the existing process. Alternatives include Jinja templates, a separate static server and a front-end deployment.

</details>

<details>
<summary><strong>Phase 19 — Per-request configuration</strong></summary>

### Definition

Phase 19 makes generation model, reranker, hybrid search and `k` selectable per request instead of requiring `.env` edits and process restarts. Expensive resources remain cached by name, while lightweight service objects are constructed for the chosen request. Every answer reports the configuration that produced it.

### Use

- Compare retrieval and generation configurations from the browser without restarting the API.
- Keep the page, API and evaluator on the same service path.
- Reuse Qdrant connections, model clients and loaded reranker weights instead of rebuilding them per request.
- Reject arbitrary model names through server-side allow-lists before they can spend money or download weights.
- Reproduce the earlier finding that hybrid search harms the golden corpus while leaving the default unchanged.

### Tech stack

- **Optional JSON request fields** — represent model, reranker, hybrid and passage-count overrides while omission preserves server defaults. A separate endpoint per configuration would duplicate the answer path.
- **Named LRU caches** — keep one generator or reranker per allowed model name and share the single vector-store connection. Alternatives include rebuilding every request and a general dependency-injection container.
- **Configuration allow-lists** — constrain browser-controlled values to models that were deliberately tested. Alternatives include free-text identifiers and deployment-level fixed configuration.
- **Configuration metadata** — travels with every answer so a result cannot be separated from the settings that produced it.

**Important commands**

- Open `/options` — inspect allowed models, rerankers, defaults and maximum `k`.
- Send optional `model`, `reranker`, `hybrid` and `k` fields to `POST /ask` — override one request.
- `uv run eurohistory evaluate --help` — inspect the equivalent evaluation controls.

### Frameworks

- **FastAPI and Pydantic** — validate optional overrides and reject unknown model names with clear 422 responses. Alternatives include manual JSON validation and separate endpoints.
- **`functools.lru_cache`** — caches expensive objects by model name using the standard library. Alternatives include a custom cache, a service container and process-global dictionaries.
- **Vanilla JavaScript controls** — populate both answer and evaluation settings from `/options`, preventing duplicated client-side allow-lists. Alternatives include front-end state frameworks.

</details>

<details>
<summary><strong>Phase 20 — Run evaluations from the page</strong></summary>

### Definition

Phase 20 lets the evaluation page start, monitor, cancel and automatically gate a paid experiment. The interface requires a written prediction and displays the estimated cost and preconditions before enabling the run. A page-started run writes the same files and uses the same execution stack as the CLI.

### Use

- Enforce the rule that a prediction exists before the first measured question is asked.
- Confirm API key, Qdrant availability and indexed point count before spending money.
- Run only one evaluation at a time and cancel safely between questions.
- Track progress independently of the browser tab that started the work.
- Compare the completed run with a selected baseline and display the gate verdict automatically.
- Verify equivalence: all sixty tested questions returned the same ranked chunks as the CLI baseline.

### Tech stack

- **Background worker thread** — lets a multi-minute evaluation outlive the HTTP request that started it. It is suitable for this single-process local tool; alternatives include Celery, RQ and a durable job service.
- **Lock and stop event** — make “check idle and start” one atomic operation and cancel only between completed questions. Alternatives include a database lock and message-queue cancellation.
- **Polling endpoint** — exposes current progress, error and gate state so reloads and second tabs see the same job. Alternatives include WebSockets and server-sent progress events.
- **Prediction file and cost estimate** — are written before work begins, turning research discipline into an enforced interface sequence.

**Important commands**

- Open the Evaluation view and select **Run experiment** — inspect cost and preconditions.
- Enter a prediction and choose a baseline — enable the paid run.
- `uv run eurohistory evaluate` — run the same workflow from the CLI.
- `uv run eurohistory gate <baseline> <candidate>` — reproduce the page’s final comparison offline.

### Frameworks

- **Python `threading`** — provides the worker, lock and cancellation event without adding infrastructure to a single-user local application. Alternatives include task queues and `asyncio` background tasks.
- **FastAPI** — exposes plan, start, status and cancel endpoints while restricting starts to loopback clients. Alternatives include a separate experiment service.
- **Vanilla JavaScript polling** — maintains the progress bar and reconnects after page reload. Alternatives include WebSockets and a front-end query library.

</details>

<details>
<summary><strong>Phase 21 — Streaming and time to first token</strong></summary>

### Definition

Phase 21 streams an answer as the model writes it instead of returning one completed JSON object after several seconds. Server-sent events carry sources, text fragments, completion data and failures over the existing `/ask` endpoint. Median time to first token improved from 3,521 ms to 1,121 ms while every retrieval metric remained identical.

### Use

- Replace several seconds of blank screen with visible answer progress.
- Send retrieved sources before generation because they are already known.
- Preserve the non-streaming JSON path for clients and evaluation that want a complete object.
- Measure perceived latency separately from total completion time.
- Report mid-stream failure honestly after the HTTP status code can no longer be changed.

### Tech stack

- **Server-sent events (`text/event-stream`)** — send ordered one-way events over a normal HTTP response. They fit answer streaming better than bidirectional WebSockets. Alternatives include WebSockets and newline-delimited JSON.
- **Iterator-based generation** — yields text fragments followed by one final typed completion carrying text, tokens and timing. Alternatives include separate streaming and non-streaming model methods that could drift.
- **`time.perf_counter()` timing** — measures search, generation and first-token latency with a monotonic clock. Wall-clock timestamps can jump and are unsuitable for durations.
- **Browser Streams API** — incrementally decodes SSE data and renders the answer as fragments arrive.

**Important commands**

- Request `POST /ask` with `Accept: text/event-stream` — select the streaming response.
- `uv run eurohistory evaluate` — record first-token and total latency after the change.
- `uv run eurohistory gate <baseline> <candidate>` — verify retrieval and behaviour did not regress.

### Frameworks

- **FastAPI `StreamingResponse`** — streams the event iterator without creating a second endpoint. Alternatives include a WebSocket handler and framework-specific streaming plugins.
- **OpenAI streamed chat completions** — supply text deltas and final token usage from the existing model client. Alternatives include polling a non-streaming completion and other provider streams.
- **Vanilla JavaScript** — parses and renders stream events without an additional client library. Alternatives include EventSource for GET-only streams and framework-specific stream hooks.

</details>

<details>
<summary><strong>Phase 22 — Temporal retrieval</strong></summary>

### Definition

Phase 22 adds year spans to chunks and an optional retrieval arm restricted to passages whose periods overlap the question. The filtered ranking is fused with ordinary dense retrieval instead of excluding undated chunks from the whole search. Temporal recall@5 was already 87.5% and remained 87.5%, while other metrics regressed, so the feature stays off by default.

### Use

- Distinguish the period a passage covers from incidental years mentioned in its body.
- Parse explicit ranges, decades, centuries and named eras from questions.
- Give date-aligned passages an additional path to rise without deleting undated semantic matches.
- Avoid guessing for ambiguous relative expressions such as “after the war.”
- Retain the implementation for reproducible experiments while respecting the failed regression gate.

### Tech stack

- **Year-span metadata** — stores `year_start`, `year_end` and the source from heading, title or body. Declared headings are preferred because body numbers can be incidental measurements. Alternatives include LLM-extracted dates and external knowledge graphs.
- **Temporal query parser** — maps supported expressions to a typed period and returns no period when interpretation would be unsafe. Alternatives include date-parsing libraries and an LLM query-understanding step.
- **Qdrant range indexes and filters** — search only points whose stored intervals overlap the question period. Exact scanning is used for the small filtered set after approximate HNSW search missed an obvious result.
- **Third-arm reciprocal rank fusion** — adds temporally aligned candidates to dense and optional sparse rankings without turning the date rule into a destructive pre-filter.

**Important commands**

- `uv run eurohistory chunk` — derive chunk periods after date logic changes.
- `uv run eurohistory index --payload-only` — refresh date payloads without paying to re-embed unchanged text.
- Set `TEMPORAL_ENABLED=true` — enable the temporal arm for an experiment.
- `uv run eurohistory evaluate` and `uv run eurohistory gate <baseline> <candidate>` — measure and gate the change.

### Frameworks

- **qdrant-client** — creates numeric payload indexes and performs exact filtered vector searches. Alternatives include pgvector range columns and Elasticsearch date filters.
- **Python regular expressions and dataclasses** — parse the deliberately limited temporal grammar into explicit `Period` objects. Alternatives include dateparser, spaCy and LLM extraction.
- **Polars** — carries nullable date fields through Gold rebuilds and payload refreshes. Alternatives include pandas and PyArrow.

</details>

<details>
<summary><strong>Phase 23 — Infobox retrieval</strong></summary>

### Definition

Phase 23 turns Wikipedia infobox key-value data already preserved in Silver into retrievable Gold chunks. Infobox facts join the same vector collection and answer path as prose instead of requiring a separate structured store and router. Factual answer rate improved from 50.0% to 85.7%, and the feature shipped despite a gate failure that was read and documented.

### Use

- Retrieve dates, areas, casualties and treaty facts that may exist only in an infobox.
- Reuse the same retrieval, prompt and citation path as prose passages.
- Append one fact chunk per article without changing existing prose chunk IDs.
- Index only the new chunks with resume mode instead of paying to embed the full corpus again.
- Expose that section-level coverage can be blind to eviction of a specific infobox chunk.

### Tech stack

- **Silver infobox structs** — preserve cleaned key-value pairs and their infobox type before markup is removed. Alternatives include normalized relational tables and dropping structured values.
- **Gold infobox chunks** — render fields as `key: value` text under an `Infobox` heading so the existing embedder can retrieve them. Alternatives include a SQL lookup path and tool-based routing.
- **Append-preserving chunk IDs** — place fact chunks after all existing prose chunks, allowing Qdrant resume to skip previously paid embeddings.

**Important commands**

- `uv run eurohistory chunk` — add infobox chunks to Gold.
- `uv run eurohistory index --resume` — embed only chunks absent from Qdrant.
- `uv run eurohistory evaluate` — measure the factual suite and existing suites.
- `uv run eurohistory gate <baseline> <candidate>` — inspect both gains and regressions before shipping.

### Frameworks

- **mwparserfromhell** — extracts and cleans infobox fields from raw templates in Silver. Alternatives include MediaWiki template APIs and HTML scraping.
- **Polars** — stores nested infobox structures and writes the expanded Gold table. Alternatives include PyArrow and a relational database.
- **Existing OpenAI/Qdrant RAG stack** — retrieves structured facts as text without introducing a router framework. Alternatives include SQL tools, function calling and hybrid structured/vector storage.

</details>

<details>
<summary><strong>Phase 24 — Conversation rewriting</strong></summary>

### Definition

Phase 24 rewrites a follow-up such as “When did it come down?” into a standalone question before retrieval. Conversation history is used only for this rewrite; retrieval, prompting, citations and evaluation continue to receive one self-contained question. Follow-up recall@5 improved from 46.2% to 92.3%, and the feature shipped enabled by default.

### Use

- Restore subjects and context omitted from short conversational follow-ups.
- Keep the embedding focused on the current question instead of averaging the whole conversation into one vector.
- Make the rewritten interpretation visible in API responses, evaluation records and the page.
- Preserve normal single-turn behaviour by bypassing rewriting when no history is supplied.
- Measure hazards: the rewriter can add world knowledge and is not perfectly deterministic.

### Tech stack

- **Standalone-question rewrite prompt** — instructs a model to return one self-contained question rather than answer it. Alternatives include embedding the full history, rule-based pronoun resolution and conversational retrieval models.
- **Bounded history** — supplies only the two most recent exchanges and truncates long assistant text, limiting cost and wrong antecedents. Alternatives include full history and a separate summary call.
- **History and standalone fields** — travel through request, response, question and evaluation schemas so rewriting never becomes invisible preprocessing.

**Important commands**

- Send `history` with `POST /ask` — enable rewriting for a follow-up request.
- Set `CONVERSATION_ENABLED=false` — reproduce the before configuration.
- `uv run eurohistory evaluate` — run the conversation suite.
- `uv run eurohistory gate <baseline> <candidate>` — verify the single-turn suites remain stable.

### Frameworks

- **OpenAI generator interface** — uses a separately configurable model client for rewriting and falls back to the original question when rewriting fails. Alternatives include a local rewrite model and rule-based coreference resolution.
- **FastAPI and Pydantic** — validate conversation turns and expose the resolved standalone question. Alternatives include server-side session objects and untyped request dictionaries.
- **Vanilla JavaScript state** — retains completed exchanges in the page and sends them with later questions. Alternatives include server-side conversation storage and front-end state frameworks.

</details>

<details>
<summary><strong>Phase 25 — Reranker warm start</strong></summary>

### Definition

Phase 25 moves local reranker construction from the first user request into application startup and removes a duplicate model cache. The original explanation blamed a 487 MB model, but measurement showed an 88 MB model was being constructed twice while the heavy library import had already happened at startup. Cold passage display improved from 6.9 seconds to about 1.0–1.1 seconds.

### Use

- Make startup pay the model-loading cost instead of the first person asking a question.
- Prevent the same reranker from being loaded into two cached objects per request path.
- Keep `/health` as liveness while `/ready` reports a failed reranker load.
- Disable warm start in tests so the offline suite never downloads or loads model weights.
- Measure cold browser behaviour directly because the median of a long evaluation cannot see a one-time cost.

### Tech stack

- **FastAPI lifespan** — loads the configured reranker before Uvicorn accepts traffic. A blocking startup accurately represents “not ready”; alternatives include lazy loading and background warm-up with explicit loading state.
- **Shared named reranker cache** — makes default and per-request service construction reuse the same model object. Alternatives include one global fixed model and manual cache dictionaries.
- **`warm_start` setting** — enables production warm-up while tests override it to remain fast and offline.
- **Browser cold-start measurements** — time separate just-started processes instead of averaging the first load across many warm questions.

**Important commands**

- `uv run uvicorn eurohistory_rag.api.main:app` — start the server and observe the reranker-ready log before startup completes.
- Open `/ready` — verify both Qdrant and reranker readiness.
- Set `WARM_START=false` — reproduce lazy loading or run isolated tests.
- Restart Uvicorn between cold measurements — ensure every sample includes a fresh process.

### Frameworks

- **FastAPI lifespan and dependency injection** — coordinate startup work and reuse the same dependency caches as request handling. Alternatives include an external process manager hook and module-import loading.
- **Sentence Transformers** — constructs the local cross-encoder whose weights are warmed. Alternatives include ONNX and a hosted reranker with no local model load.
- **Python `lru_cache` and logging** — deduplicate model instances and record startup duration and failure. Alternatives include a service container and custom caching.

</details>

<details>
<summary><strong>Phase 26 — Per-article thinning, re-measured</strong></summary>

### Definition

Phase 26 repeats the Phase 12 per-article cap experiment on the expanded corpus and complete 106-question evaluation. The configurable cap increases distinct articles but reduces expected-section coverage and factual answer performance. The implementation remains available, but `max_per_article` defaults to no cap and the change was not shipped as active behaviour.

### Use

- Verify whether the earlier negative result still holds after the corpus and evaluation grew substantially.
- Thread the cap through settings, search, evaluation metadata and comparability checks so experiments are reproducible.
- Protect against a dead configuration switch with a test proving the setting reaches `thin()`.
- Quantify the true opportunity: only 7.7% of missing expected sections were positioned where an article cap could promote them.
- Record the interaction where article caps removed lower-ranked infobox facts and turned two treaty-date answers into refusals.

### Tech stack

- **Optional `max_per_article` setting** — accepts an integer cap or `None` for the measured default. A number preserves the difference among caps of three, two and one better than a boolean.
- **Greedy `page_id` thinning** — applies after reranking while preserving candidate order and the existing per-section cap. Alternatives include MMR, clustering and multi-stage retrieval.
- **Run metadata and gate comparability** — record the exact cap so two runs cannot be compared as if they used the same retrieval policy.
- **Depth-invariance test** — proves that the first five results of a twenty-deep thinned list match a direct five-result request, keeping evaluation and `/ask` comparable.

**Important commands**

- Set `MAX_PER_ARTICLE=3`, `2` or `1` in `.env` — select an experimental cap.
- Leave `MAX_PER_ARTICLE` unset — run the measured production default with no article cap.
- `uv run eurohistory evaluate` — measure the complete suite under the chosen cap.
- `uv run eurohistory gate <baseline> <candidate> --changed max_per_article` — compare the intended retrieval-policy change.

### Frameworks

- **Pydantic Settings** — validates and exposes the optional cap consistently to API and evaluation wiring. Alternatives include a hard-coded constant and a per-request control.
- **Python dataclasses** — carry the cap in required `RunConfig` construction and recorded `RunMeta`, making forgotten call sites type errors. Alternatives include dictionaries with optional keys.
- **Existing SearchService and gate framework** — apply and measure the policy without introducing a new retrieval library. The result is deliberately negative: articles@5 rose from 2.7 to 3.2, while coverage@5 fell from 60.3% to 58.3% and the gate failed.

</details>
