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
│   │   └── s12_s13_s14_retrieval.py
│   ├── cli.py                 # Command Line Interface
│   └── main.py                # FastAPI Server Entrypoint
├── tests/                     # Comprehensive test suite (pytest)
│   └── test_pipeline_e2e_integration.py # E2E isolated registry tests
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

---

## ⚙️ Configuration & Extensibility

- **RAG Limits:** You can tweak the context limits (e.g., retrieving 50 chunks, reranking to 25) in `src/core/config.py`.
- **Dynamic Routing Rules:** Model routing priorities and fallback chains can be edited entirely without touching Python code by updating `config/providers.yaml`.
- **State Persistence:** UI state (chats, messages) is managed locally via JSON files in the `/data` directory using file-level advisory locks (`fcntl.flock`) for concurrency safety—meaning zero database setup is required.

## 📚 Architecture Details
For a deep dive into the internal mechanics, state management, and file structure of GlobleMind, please read the comprehensive **[ARCHITECTURE.md](ARCHITECTURE.md)** file included in this repository.
