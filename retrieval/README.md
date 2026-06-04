# Policy DB Chatbot — Retrieval and Ingestion Component

This directory contains the data engineering and retrieval component for the **Policy DB Chatbot**. It transforms publicly accessible La Trobe University policy pages into validated, searchable Qdrant records and retrieves relevant policy evidence for downstream response generation.

## What This Component Does

- Crawls public policy pages and excludes pages identified as restricted or SSO-protected.
- Parses policy structure and preserves detected tables.
- Produces retrieval-ready chunks with source and breadcrumb context.
- Adds validated metadata, including broad audience categories and possible exception indicators.
- Stores dense and sparse vector representations in Qdrant.
- Publishes completed candidate collections through the stable `university_policies` alias.
- Performs hybrid retrieval, exception-aware retrieval and cross-encoder reranking.
- Provides audit and retrieval-evaluation scripts for maintenance checks.

## Project Location

The `retrieval/` package is part of the main project. Run module commands from the **project root**, not from inside the `retrieval/` folder.

```text
policy-chatbot/
├── docker-compose.yml
├── retrieval/
│   ├── config.py
│   ├── ingest.py
│   ├── retrieve_policies.py
│   ├── setup_db.py
│   ├── audit_db.py
│   ├── test_retrieval_metrics.py
│   └── utils/
└── data/
```

Example Windows project-root location:

```text
C:\policy-chatbot
```

## Key Modules

| Module | Responsibility |
|---|---|
| `retrieval/ingest.py` | Orchestrates staged ingestion, manifests, checkpoints, candidate insertion and publication. |
| `retrieval/config.py` | Stores database, model, vector-name, retry and active-role configuration. |
| `retrieval/setup_db.py` | Creates Qdrant candidate collections, vector fields, quantisation and payload indexes. |
| `retrieval/retrieve_policies.py` | Runs query rewriting, role-aware hybrid retrieval, exception retrieval and reranking. |
| `retrieval/audit_db.py` | Audits published Qdrant records and metadata distributions. |
| `retrieval/test_retrieval_metrics.py` | Runs the retrieval evaluation query set and writes result files. |
| `retrieval/utils/crawler.py` | Discovers/stages public policy HTML, detects restricted pages and hashes source state. |
| `retrieval/utils/parser.py` | Extracts metadata, parses structured content and preserves tables as Markdown. |
| `retrieval/utils/chunker.py` | Prepares breadcrumb-aware text/table chunks with semantic splitting safeguards. |
| `retrieval/utils/payload_builder.py` | Creates metadata payloads and assigns audience/exception information. |
| `retrieval/utils/schemas.py` | Validates stored payload structure and permitted audience values. |
| `retrieval/utils/vector_engine.py` | Generates vectors and inserts validated records into Qdrant. |
| `retrieval/utils/alias_manager.py` | Promotes a completed candidate collection to the live alias. |
| `retrieval/utils/state_manager.py` | Stores published source hashes in the SQLite ledger. |

## Current Configuration

| Item | Configured Value |
|---|---|
| Qdrant service URL | `http://localhost:6333` |
| Live collection alias | `university_policies` |
| Dense vector name | `text-dense` |
| Dense embedding model | `nomic-embed-text` |
| Dense vector size | `768` |
| Sparse vector name | `text-sparse` |
| Sparse embedding model | `prithivida/Splade_PP_en_v1` |
| Cross-encoder reranker | `BAAI/bge-reranker-base` |
| Metadata extraction model | `llama3.2` |
| Active retrieval roles | `Student`, `Staff`, `Public` |

## Prerequisites

Install the following before running the component:

- Python 3.12 or a compatible Python 3 environment
- Docker Desktop with Docker Compose
- Ollama

The current project does not include a committed `requirements.txt` file. Dependencies are installed directly using the commands below.

## Installation

From the main project root directory:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install aiohttp beautifulsoup4 crawl4ai docling docling-core fastembed numpy ollama pydantic psutil qdrant-client requests spacy
python -m spacy download en_core_web_sm
crawl4ai-setup
```

`spaCy` supports sentence processing during chunk preparation. If the English model is unavailable, the current chunker can fall back to basic sentence splitting, but the documented deployment should install it.

`crawl4ai-setup` installs browser-related resources required for HTML policy crawling.

## Start Qdrant

The main project uses `docker-compose.yml` in the project root. The Qdrant service configuration is:

```yaml
services:
  qdrant:
    container_name: qdrant_database
    image: qdrant/qdrant:v1.17.1

    ports:
      - "127.0.0.1:6333:6333"
      - "127.0.0.1:6334:6334"

    volumes:
      - qdrant_storage:/qdrant/storage

    restart: unless-stopped

volumes:
  qdrant_storage:
```

Start the service:

```powershell
docker compose up -d qdrant
docker compose ps
```

Open the local dashboard at:

```text
http://localhost:6333/dashboard
```

Stop the container while retaining stored data:

```powershell
docker compose down
```

Avoid `docker compose down -v` unless the persisted Qdrant volume is deliberately being removed.

## Start Ollama and Pull Models

Ollama must be running before ingestion or retrieval is executed.

```powershell
ollama pull nomic-embed-text
ollama pull llama3.2
```

The sparse embedding model and reranker are obtained through FastEmbed when first required.

## Optional Environment Variables

The implementation defaults to local services. Values can be overridden where required.

| Variable | Default / Purpose |
|---|---|
| `WEB_HUB_URL` | Defaults to `https://policies.latrobe.edu.au/browse`. |
| `QDRANT_URL` | Defaults to `http://localhost:6333`. |
| `QDRANT_API_KEY` | Optional; not required for the default local service. |
| `QDRANT_COLLECTION_ALIAS` | Defaults to `university_policies`. |
| `OLLAMA_EMBED_URL` | Defaults to `http://localhost:11434/api/embed`. |
| `OLLAMA_CHAT_URL` | Defaults to `http://localhost:11434/api/chat`. |
| `EXTRACTOR_MODEL_NAME` | Defaults to `llama3.2`. |
| `MAX_DENSE_EMBED_WORKERS` | Controls concurrent dense-embedding requests. |
| `MAX_EMBED_RETRIES` | Controls temporary dense-embedding retries. |
| `INGESTION_AVAILABLE_RAM_GB` | Overrides RAM used when sizing ingestion workers. |

## Run the Ingestion Pipeline

From the project root:

```powershell
python -m retrieval.ingest
```

The program presents the following modes:

| Option | Purpose |
|---:|---|
| `1` | Full public HTML policy-library rebuild and alias promotion. |
| `2` | Ten-policy publication-path test, including candidate promotion and ledger update. |
| `3` | Resume the latest incomplete candidate build using checkpoints. |
| `4` | Single-policy debug run without database insertion. |

Recommended first check for a new environment: use option `4`, because it verifies crawling, parsing, chunking and validation without altering the live collection.

**Important:** option `2` promotes a partial test collection. After using it, run option `1` before treating the database as the complete live policy index.

## Verify Retrieval

After a successful complete build:

```powershell
python -m retrieval.retrieve_policies
```

Sample retrieval results are written to:

```text
test_results.json
```

Run the broader retrieval evaluation:

```powershell
python -m retrieval.test_retrieval_metrics
```

Outputs are written to:

```text
retrieval/evaluation_outputs/
```

## Audit the Published Database

Run:

```powershell
python -m retrieval.audit_db
```

Audit reports are written to:

```text
retrieval/audit_outputs/
```

## Data and Runtime Outputs

The ingestion process creates working artefacts under the project-level `data/` directory, including staged HTML, parsed documents, chunked outputs, validated payloads, run manifests and the SQLite source-state ledger.

The Qdrant live retrieval layer queries the stable alias:

```text
university_policies
```

A new ingestion run builds a separate candidate collection and promotes it only after successful processing and vector insertion. The SQLite ledger is updated after successful publication so that the recorded source state corresponds to the active published policy index.

## Current Scope and Maintenance Notes

- Active role filtering uses the broad roles `Student`, `Staff` and `Public`.
- More detailed contextual tags, such as `HDR`, `International`, `Academic` and `Professional`, are stored for context and future evaluation but are not active access filters.
- Source hashes support change detection, while the current publication pathway creates a full candidate build rather than re-embedding only changed policies.
- Dependency installation is currently documented through direct commands because a committed `requirements.txt` is not included.
- Changes to metadata fields, vector configuration, indexed payload fields or chunking rules require a new candidate build and retrieval/audit verification before publication.

## Reference Documentation

- Qdrant Documentation: <https://qdrant.tech/documentation/>
- Qdrant Local Quickstart: <https://qdrant.tech/documentation/quickstart/>
- Crawl4AI Installation: <https://docs.crawl4ai.com/core/installation/>
- Ollama Documentation: <https://docs.ollama.com/>
