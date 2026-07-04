# GlobleMind Deep Architecture & Context Map

This document is the **definitive, granular guide** to the GlobleMind project. Paired with `CLAUDE.md` (which dictates coding standards), this file explains *how everything works, from the smallest utility functions to the macro system architecture*. 

If you are an AI reading this, you now hold the complete blueprint of the system in your mind.

---

## 1. Core Architecture Philosophy
GlobleMind (also known as LocalMind in the UI) is an enterprise-grade Retrieval-Augmented Generation (RAG) system built with a single, aggressive constraint: **It must operate entirely on forever-free-tier APIs while rivaling paid systems in accuracy.**

To achieve this, the architecture rejects single-provider dependency. Instead, it uses a **dynamic LLM routing pattern**. The backend acts as a smart orchestrator that categorizes workloads and distributes them across Google (Gemini), Groq, Nvidia NIM, and Jina AI based on rate limits, availability, and task complexity.

Data persistence completely avoids SQL databases. UI state is managed via flat JSON files (`/data`), and vectors are handled by Qdrant (cloud or local). 

---

## 2. Directory Map & The Engine Room (`src/core/`)

The backend is a Python 3.11+ FastAPI application (`src/main.py`).

### `src/core/config.py`
The central nervous system. Uses `pydantic_settings` to load the `.env` file. It holds critical pipeline limits:
- `retrieval_top_k` (default 50): How many chunks to pull from Qdrant.
- `rerank_top_k` (default 25): How many chunks to feed to the final LLM (essential for a large context window model like Llama 3.3).
- `ocr_confidence_threshold`: Determines when to fallback to intensive OCR.

### `src/core/state.py` (Database Replacement)
We use a JSON-based Data Access Object (DAO) pattern. The `UIStateManager` reads/writes entirely to the `data/` directory (`chats.json`, `messages.json`, `documents.json`). To ensure concurrency safety across asynchronous API calls, it implements file-level advisory locking via `fcntl.flock`. This ensures the app is highly portable, safe for parallel access, and has zero database setup costs.

### `src/core/ingestion_registry.py` (Deduplication State)
Provides stateful tracking of ingested documents via SHA-256 hashing (stored in `data/ingested_files.json`). Prevents redundant API calls on duplicate uploads and orchestrates the deletion of stale vector chunks when a document is modified.

### `src/core/provider_client.py` (The Routing Engine)
This is the most critical file in the system. It implements `ProviderRouter`, which loads rules dynamically from `config/providers.yaml`.
- When a task (e.g., `reasoning`, `image_understanding`) is requested, the router attempts the `priority: 1` provider.
- If it encounters a `429 Too Many Requests` (common on free tiers) or a `503 Service Unavailable`, it gracefully catches the error and instantly retries the payload against the `priority: 2` provider (e.g., falling back from Gemini to Nvidia NIM).
- Supports both standard generative responses (`chat()`) and **Server-Sent Events streaming** (`chat_stream()`) across all providers using a unified `AsyncGenerator` interface.

---

## 3. The 14-Stage RAG Pipeline (`src/stages/`)

The ingest and query logic is rigorously decoupled into 14 explicit stages, ensuring atomic processing and easy debugging.

### Ingestion Pipeline (`src/pipeline/ingestion.py`)
Documents are passed sequentially through stages 1-11 in memory. If a stage fails, the document is discarded without corrupting the database.

* **s01_file_detection.py**: Wraps `python-magic` to securely validate MIME types, preventing spoofed files.
* **s02_classification.py**: Uses zero-shot LLM classification to categorize the document (e.g., Financial Report vs. Scientific Paper). This informs downstream extraction rules.
* **s03_parsing.py**: Primary text extraction using PyMuPDF and pdfplumber.
* **s04_ocr.py**: Fallback module. Uses `OCR.space` API to extract text from scanned PDFs or images.
* **s05_layout.py**: Passes dense pages to Gemini 2.5 Flash Vision to determine reading order and distinguish headers/footers from main prose.
* **s06_tables.py**: Uses heuristics and vision models to accurately extract tabular data into Markdown format.
* **s07_s08_visuals.py**: Slices charts, graphs, and images from the PDF and sends them to a Vision LLM to generate deep descriptive captions. Utilizes `asyncio.gather` bounded by a semaphore to process multiple visuals in parallel for maximum throughput.
* **s09_chunking.py**: Implements semantic, token-based chunking with fractional overlap to maintain sentence boundaries.
* **s10_embeddings.py**: Sends chunks to Jina AI's V3 Embedding model, converting text to 1024-dimensional floating-point vectors **alongside exact-keyword Sparse Vectors**.
* **s11_vector_store.py**: The final commit. Pushes the multi-vectors and payload metadata to Qdrant Cloud. Enables **Reciprocal Rank Fusion (RRF)** for true hybrid search.

### Retrieval Pipeline (`src/pipeline/query.py`)
When a user submits a prompt, it triggers stages 12-14:

* **s12_s13_s14_retrieval.py**: 
  - **Stage 12 (Retrieve):** Embeds the user prompt, queries Qdrant using **Hybrid Search (Dense + Sparse)** with optional **Metadata Filters**, and pulls 50 chunks via RRF fusion.
  - **Stage 13 (Rerank):** Sends the 50 chunks to Jina's Cross-Encoder Reranker to re-order them based on deep contextual relevance to the prompt.
  - **Stage 14 (Generate):** Formats the top 25 chunks into a massive context block and feeds it to the `ProviderRouter`. Enforces citation generation via footnotes (e.g., `[1]`), and yields the generative answer chunk-by-chunk for real-time UI streaming.

---

## 4. Frontend Architecture (`LocalMind_UI/`)

The frontend is a single-page React application built with Vite. It is completely decoupled from the AI logic and acts purely as a presentation layer.

### Integration with Backend
Instead of running a separate Node server, we use `npm run build` to compile the React code into static files in the `/frontend/` directory. FastAPI (`src/main.py`) mounts this directory as a StaticFiles app, serving `index.html` on the root route.

### Key Directories
- **`src/pages/` & `src/components/`**: Standard React component hierarchy.
  - `Chat.jsx`: Main UI wrapper for messages and input.
  - `Sidebar.jsx`: Chat history loaded from `/api/chats`.
  - `Message.jsx`: Renders individual messages using `react-markdown`.
- **`src/services/api.js`**: An Axios wrapper that communicates strictly with FastAPI endpoints (e.g., `POST /api/chats/{id}/messages`).
- **`src/styles/`**: Global Vanilla CSS. Minimalist design system (`globals.css`, component-specific scoped classes).

### UI/UX Details
- **Real-Time Generative Streaming**: Rather than making users wait for long RAG pipeline operations to finish, the React UI (`api.js` and `store.js`) intercepts Server-Sent Events via `POST /api/chats/{id}/messages/stream`. It displays the chunks iteratively with a typing effect. Upon stream completion, it seamlessly replaces the chunks with a beautifully formatted markdown message including a `**Sources:**` citation block.
- **Styling**: The CSS deliberately avoids backgrounds and borders on loading elements to make the UI look clean and deeply integrated.
- **In-App Ingestion**: The sidebar natively includes a File Upload component allowing users to upload and ingest documents directly into the vector database via `POST /api/upload`.

---

## 5. End-to-End Traces

### Trace A: Ingesting a PDF via CLI
1. User runs `globle-mind ingest Model_Card.pdf`.
2. `src/cli.py` triggers `IngestionPipeline.process()`.
3. The PDF is classified, parsed, OCR'd.
4. Gemini Flash analyzes 40 charts in the PDF. Google throws a `429 Too Many Requests`.
5. `ProviderRouter` catches the 429 and dynamically fails over to Nvidia NIM's Vision model to finish the charts.
6. Jina embeds 96 chunks into 1024-dim vectors.
7. Stage 11 pushes all 96 chunks to Qdrant. The document is now active.

### Trace B: A User Chat Query
1. User types "Compare benchmarks" in the React UI.
2. React fires `fetch` to `POST /api/chats/chat-123/messages/stream` using a stream reader.
3. `api/ui.py` creates a "user" message in `messages.json` and calls `QueryPipeline.query_stream()`.
4. Stage 12 embeds "Compare benchmarks" and pulls 50 chunks from Qdrant.
5. Stage 13 reranks them to the top 25 chunks.
6. Stage 14 heuristically identifies this prompt as a `reasoning` task.
7. `ProviderRouter` sends the prompt + 25 chunks to Groq's Llama 3.3 70B (priority 1 for reasoning) invoking the `chat_stream` generator.
8. `ui.py` streams SSE events back to the UI (`{"type": "chunk", "text": "..."}`).
9. React receives the chunks and visually types the response iteratively in real-time.
10. Once the LLM completes, `QueryPipeline` yields the final `QueryResult` object, extracting citations and mapping them to `[1]` format.
11. `ui.py` sends the final formatted `{"type": "done", "message": ...}` payload via SSE, updating `messages.json`. React swaps the raw streamed message with the polished Markdown text and citations.
