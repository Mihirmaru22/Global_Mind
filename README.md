# GlobleMind (LocalMind)

GlobleMind (often referred to as LocalMind in the UI) is an enterprise-grade Retrieval-Augmented Generation (RAG) system built with a single, aggressive constraint: **It must operate entirely on forever-free-tier APIs while rivaling paid, state-of-the-art systems in accuracy, resiliency, and user experience.**

By implementing a dynamic LLM routing pattern, GlobleMind rejects single-provider dependency. The system intelligently categorizes workloads and distributes them across free tiers from Google (Gemini), Groq, Nvidia NIM, and Jina AI based on rate limits, availability, and task complexity.

![Stack](https://img.shields.io/badge/Stack-FastAPI%20|%20React%20|%20Qdrant-success)
![Architecture](https://img.shields.io/badge/Architecture-14--Stage_Pipeline-blue)

---

## 🌟 Key Features

### 🧠 Intelligent Provider Routing
A resilient `ProviderRouter` directs workloads to the best free-tier model for the job. If it encounters a `429 Too Many Requests` (common on free tiers) or a `503 Service Unavailable`, it gracefully catches the error and instantly retries the payload against the secondary provider in the fallback chain.
- **Reasoning:** Groq (Llama 3.3 70B) → Gemini 2.5 Flash → Nvidia NIM (Llama 3 70B)
- **Vision & Layout:** Gemini 2.5 Flash → Nvidia NIM (Llama 3.2 90B Vision)
- **Embeddings:** Jina Embeddings V3 (1024-dim)
- **Vector DB:** Qdrant Cloud / Local Memory
- **Streaming Support:** Full Server-Sent Events (SSE) support across all generators for real-time streaming.

### 🚀 V2 Architecture Upgrades
- **Idempotent Ingestion (Deduplication):** Documents are hashed (SHA-256) and tracked. Re-uploading exact duplicates costs zero API credits. Updating a document automatically scrubs stale vectors.
- **True Hybrid Search (RRF):** Queries are powered by Qdrant's Reciprocal Rank Fusion, seamlessly merging semantic dense vectors with exact-keyword sparse vectors (via Jina `return_sparse`).
- **Metadata Filtering:** Constrain searches with surgical precision (e.g., by document type, filename, or page range).
- **Parallel Batching:** Ingest folders of documents concurrently without violating rate limits using an `asyncio.Semaphore`.
- **Live Pipeline Streaming:** The frontend syncs with the 14-stage pipeline in real-time via the `/upload/stream` SSE endpoint.
- **Confidence Gates (QA):** OCR and table-extraction output is scored against multiple heuristics (garbage-character ratio, dictionary-word ratio, cross-checking OCR text against the reported engine confidence) before it's allowed into the vector store — low-confidence extractions get flagged rather than silently corrupting retrieval later (`src/core/confidence.py`).

### 📄 14-Stage Ingestion Pipeline
Documents are processed through a rigorous pipeline designed for high accuracy. If a stage fails, the document is discarded without corrupting the vector database.
1. **File Detection:** Secure MIME type validation via `python-magic`.
2. **Classification:** Zero-shot LLM classification (e.g., Financial Report vs. Scientific Paper).
3. **Parsing:** Primary text extraction using PyMuPDF and pdfplumber.
4. **OCR (Fallback):** Uses `OCR.space` API to extract text from scanned PDFs.
5. **Layout Analysis:** Passes dense pages to Gemini Vision to determine reading order.
6. **Tables:** Heuristics and vision models to accurately extract tabular data into Markdown format.
7. **Visual Analysis (Images & Charts):** Asynchronously slices charts/graphs from the PDF and sends them to a Vision LLM to generate descriptive captions, making images "searchable".
8. **Chunking:** Semantic, token-based chunking with fractional overlap.
9. **Embeddings:** Jina V3 Embeddings (1024-dimensional vectors).
10. **Vector Store:** Final commit to Qdrant Cloud.

### 💻 Modern React UI
A beautiful, unified single-page React interface served directly by the FastAPI backend. It features **Server-Sent Events (SSE)** for real-time generative streaming responses, giving you a fluid chat experience with typing effects. The UI seamlessly replaces the raw streamed chunks with fully formatted Markdown and citation footnotes upon completion. You can also upload and ingest new documents directly from the UI sidebar without touching the CLI!

### 💬 Chat & Document Management
Full CRUD for conversations, backed by the JSON state layer (`state.py`) rather than a stub: create, rename, and delete chats (`POST` / `PATCH` / `DELETE /api/chats/{chat_id}`), each with its own persisted message history. The Documents view lists ingested files via the real `/api/documents` endpoint, and UI preferences are persisted via `/api/settings` (`get_settings`/`save_settings` in `state.py`). Note: the Settings and Documents *pages themselves* still carry some leftover "demo data" placeholder copy in their UI text from earlier scaffolding, even though the endpoints they call are real and working — worth a quick pass to update that copy so it doesn't undersell what's already wired up.

---

## 📂 Project Structure

GlobleMind is architected for extreme modularity. Here is the layout of the repository to help you navigate the codebase:

```text
globle_mind/
├── LocalMind_UI/              # React frontend source code (Vite)
│   ├── src/
│   │   ├── components/        # Reusable UI (Chat, Sidebar, etc.)
│   │   ├── services/          # api.js for FastAPI communication
│   │   └── store/             # React state management
│   └── package.json
├── config/
│   └── providers.yaml         # Dynamic LLM routing rules & fallback chains
├── data/                      # Local JSON state (Zero SQL required!)
│   ├── ingested_files.json    # Deduplication registry (SHA-256 state)
│   └── chats.json             # UI chat history (fcntl locked)
├── frontend/                  # Compiled React UI (Served directly by FastAPI)
├── src/                       # Core Python Backend
│   ├── api/                   # FastAPI Endpoints
│   │   ├── upload.py          # Supports /upload/batch and /upload/stream
│   │   └── query.py           # Handles RAG queries with metadata filters
│   ├── core/                  # Core Engine Logic
│   │   ├── config.py          # System limits and env vars
│   │   ├── provider_client.py # The Multi-LLM Orchestrator
│   │   ├── confidence.py      # OCR/table extraction QA gates
│   │   ├── db_client.py       # Read-only Text-to-SQL execution (SQLite / MySQL)
│   │   ├── sql_dialects.py    # Per-engine dialect facts (prompt wording, sqlglot dialect, schema query)
│   │   ├── state.py           # File-locking UI state manager
│   │   └── ingestion_registry.py # Idempotency logic
│   ├── models/
│   │   └── schemas.py         # Pydantic data models used across stages
│   ├── pipeline/              # Orchestrators
│   │   ├── ingestion.py       # Executes Stages 1-11 sequentially
│   │   └── query.py           # Executes Stages 12-14 sequentially
│   ├── stages/                # The 14 Atomic RAG Stages
│   │   ├── s01_file_detection.py
│   │   ├── s02_classification.py
│   │   ├── s03_parsing.py
│   │   ├── ...                # Modular atomic steps
│   │   ├── s10_embeddings.py  # Jina Dense + Sparse generation
│   │   ├── s11_vector_store.py# Qdrant Upsert (RRF)
│   │   ├── s12_s13_s14_retrieval.py
│   │   └── s12b_sql_retrieval.py # Text-to-SQL: NL2SQL generation + AST-validated read-only execution
│   ├── cli.py                 # Command Line Interface
│   └── main.py                # FastAPI Server Entrypoint
├── tests/                     # Comprehensive test suite (pytest)
│   ├── test_pipeline_e2e_integration.py # E2E isolated registry tests
│   └── test_sql_dialects.py   # Dialect registry, schema formatting, SQLite + MySQL query paths
├── ARCHITECTURE.md            # Deep-dive system mechanics documentation
└── pyproject.toml             # Python dependencies
```

---

## 🚀 Getting Started

### 1. Prerequisites
- Python 3.11+
- Node.js & npm (for building the UI)
- API Keys for the free tiers (Gemini, Groq, Nvidia NIM, Jina, Qdrant)

### 2. Installation
Clone the repository and install the Python dependencies into a virtual environment:
```text
# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate

# Install the backend in editable mode
pip install -e .
```

### 3. Environment Setup
Copy the example `.env` file and fill in your API keys:
```text
cp .env.example .env
```
Ensure you have keys for: `GEMINI_API_KEY`, `NVIDIA_NIM_API_KEY`, `GROQ_API_KEY`, `JINA_API_KEY`, `QDRANT_URL`, and `QDRANT_API_KEY`.

**Optional — Text-to-SQL live data:** By default, `DB_ENGINE=sqlite` and no further setup is needed beyond having a `data/live_data.db` file. To point the Text-to-SQL stage at MySQL instead, set:
```text
DB_ENGINE=mysql
DB_HOST=your-mysql-host
DB_PORT=3306
DB_NAME=your-database-name
DB_READONLY_USER=readonly_user
DB_READONLY_PASSWORD=your-readonly-password
```
`DB_READONLY_USER` should be a dedicated MySQL user with **only** `SELECT` granted (`GRANT SELECT ON your_db.* TO 'readonly_user'@'%';`) — this is the actual enforcement mechanism for write-prevention on MySQL, not just the query validation in code.

### 4. Build the Frontend
The React UI is designed to be served statically by FastAPI. You must build it first:
```text
cd LocalMind_UI
npm install
npm run build
cd ..
```

---

## 💡 Usage

### 1. Start the Server
Run the FastAPI backend, which will mount and serve the built React UI:
```text
python -m uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```
Open your browser and navigate to **http://localhost:8000**.

### 2. Ingest Documents
Before you can chat with a document, you must ingest it into the vector database. 

**Option A (UI):** Click the "Upload" button directly in the sidebar of the web application.

**Option B (CLI):** Use the built-in command line tool in a new terminal window:
```text
# Using the installed command
globle-mind ingest path/to/your/document.pdf

# Or running the module directly
python -m src.cli ingest path/to/your/document.pdf
```
*Note: Because of the deep visual analysis, complex PDFs (like Model Cards or Financial Reports) may take several minutes to ingest. The pipeline uses `asyncio` parallel processing and will automatically route around rate limits if needed!*

### 3. Chat!
Head back to `http://localhost:8000`, open a chat, and ask deep analytical questions. GlobleMind will automatically:
1. Embed your query.
2. Retrieve the top 50 chunks via Cosine Similarity.
3. Rerank them to the top 25 chunks using a Jina Cross-Encoder.
4. Synthesize a fully cited answer using Groq (Llama 3.3 70B), streaming it back to your screen in real-time.

### 4. Other CLI Commands
Beyond `ingest`, the CLI supports:
```text
# Query the pipeline directly from the terminal (no UI needed)
globle-mind query "What were the key findings in the Q3 report?"

# Start the FastAPI server (equivalent to the uvicorn command above)
globle-mind serve

# Check which LLM providers are currently reachable
globle-mind health
```

---

## ⚙️ Configuration & Extensibility

- **RAG Limits:** You can tweak the context limits (e.g., retrieving 50 chunks, reranking to 25) in `src/core/config.py`.
- **Dynamic Routing Rules:** Model routing priorities and fallback chains can be edited entirely without touching Python code by updating `config/providers.yaml`.
- **State Persistence:** Data persistence completely avoids SQL databases for application state. UI state is managed via flat JSON files (`/data`), and vectors are handled by Qdrant (cloud or local).
- **Text-to-SQL (Live Data):** A separate retrieval stage (`s12b_sql_retrieval.py`) lets the assistant answer questions against a live, structured database — independent of the JSON-backed UI state above. It supports **SQLite** (default, local file at `data/live_data.db`) and **MySQL**, selected via the `DB_ENGINE` env var (`sqlite` or `mysql`; see `.env.example`). Every generated query is AST-validated as a read-only `SELECT` (via `sqlglot`) and capped to a maximum row count before execution, and — for MySQL — should be run against a dedicated read-only database user (`GRANT SELECT` only) as the actual last line of defense at the database level. Adding a new engine (e.g. SQL Server) means adding one entry to the `DIALECTS` registry in `src/core/sql_dialects.py`, not a new class hierarchy.

## 📚 Architecture Details
For a deep dive into the internal mechanics, state management, and file structure of GlobleMind, please read the comprehensive **[ARCHITECTURE.md](ARCHITECTURE.md)** file included in this repository.
