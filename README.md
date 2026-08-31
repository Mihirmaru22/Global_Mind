# GlobleMind (LocalMind)

GlobleMind (often referred to as LocalMind in the UI) is an enterprise-grade Retrieval-Augmented Generation (RAG) and Text-to-SQL system built with a single, aggressive constraint: **It must operate entirely on forever-free-tier APIs while rivaling paid, state-of-the-art systems in accuracy, resiliency, latency, and security.**

By implementing dynamic multi-provider routing, sub-second semantic caching, deterministic template fast-paths, and AST-level query validation, GlobleMind rejects single-provider dependency. The system intelligently categorizes workloads and distributes them across free tiers from Google (Gemini), Groq (Multi-Key Pool), Nvidia NIM, OpenRouter, and Jina AI based on rate limits, availability, and task complexity.

![Stack](https://img.shields.io/badge/Stack-FastAPI%20|%20React%20|%20Qdrant-success)
![Architecture](https://img.shields.io/badge/Architecture-14--Stage_Pipeline-blue)
![Evaluation](https://img.shields.io/badge/SQL_Accuracy-96.3%25%20(157%2F163)-brightgreen)
![Latency](https://img.shields.io/badge/Cache_Hit_Latency-%3C0.8s%20(0.64s)-blueviolet)

---

## 🌟 Key Features

### ⚡ 3-Layer Latency Acceleration Architecture

GlobleMind features a 3-layer latency optimization architecture designed to deliver sub-second responses on cached and factual queries while slashing cold-start execution times:

1. **Layer 1: Semantic Cache (`src/utils/semantic_cache.py`) — The "Instant" Path**
   - **Sub-Second SLA:** Delivers cached and near-paraphrase answers in **$<0.8\text{s}$ (measured $0.0008\text{s} - 0.64\text{s}$)** with **0 LLM tokens consumed**.
   - **Dense Cosine Similarity:** Uses Jina dense embeddings with a strict cosine threshold ($\ge 0.95$).
   - **Dynamic TTL Rules:**
     - `COUNT`: 60 seconds
     - `SUM`: 60 seconds
     - `LIST`: 3,600 seconds (1 hour)
     - `POLICY`: 86,400 seconds (24 hours)
     - `OTHER`: 3,600 seconds
   - **Tenant & RBAC Isolation:** Strict `scope_key` enforcement (`{erp_instance_id}:{user_role_hash}`). Unscoped requests safely bypass cache rather than cross-contaminating.
   - **Safety Gate:** Failed AST validations, errors, and empty responses are never stored. Background updates run asynchronously without blocking response delivery.

2. **Layer 2: Template Fast Path (`src/utils/fast_path.py`) — The "Direct" Path**
   - **Bypasses Synthesis LLM:** Eliminates ~10.5s of synthesis LLM overhead for pure factual data queries (`COUNT`, `SUM`, `LIST`).
   - **Deterministic Markdown Formatting:** Formats validated SQL results directly into natural Markdown tables and localized summaries with commas and decimals.
   - **Analytical Disqualifier Guard:** Automatically routes contextual or comparative queries (`why`, `due to`, `compared to`, `versus`) to the synthesis LLM.
   - **Circuit Breaker:** Disables specific templates if failure rates exceed 1%.

3. **Layer 3: Async Parallelization (`src/pipeline/query.py`) — The "Fast" Path**
   - **Concurrent Retrieval:** Leverages `asyncio.gather()` to run independent SQL Retrieval and Vector Hybrid Search concurrently.
   - **Pure Coordinator Model:** Zero shared mutable state across asynchronous coroutines.

---

### 🧠 Intelligent Multi-Key Provider Routing

A resilient `ProviderRouter` directs workloads to the best free-tier model for the job. If it encounters a `429 Too Many Requests` or `503 Service Unavailable`, it automatically rotates across API keys or fails over to secondary providers in the fallback chain.
- **Multi-Key Rotating Groq Pool:** Configure multiple comma-separated keys in `.env` (`GROQ_API_KEY=key1,key2,key3,key4,key5`) for automatic round-robin rotation, unlocking **1.0M+ daily tokens** with zero downtime.
- **General QA:** Gemini 2.5 Flash → Groq (Qwen 2.5 Coder 32B / Llama 3.3 70B) → Nvidia NIM (Qwen 3.5 397B)
- **Reasoning & Text-to-SQL:** Groq (Qwen 2.5 Coder 32B) → Gemini 2.5 Flash / Gemma 4 31B → OpenRouter
- **Vision & Layout:** Gemini 2.5 Flash → Nvidia NIM (Llama 3.2 90B Vision / Nemotron Nano 12B)
- **Extraction:** Nvidia NIM (Qwen 3.5 397B) → Gemini 2.5 Flash → Groq
- **Summarization:** Nvidia NIM (Kimi K2.6) → Gemini 2.5 Flash
- **OpenRouter (Aggregator):** Configurable soft-pin provider (`meta-llama/llama-3.3-70b-instruct:free`, `meta-llama/llama-3.2-11b-vision-instruct:free`).
- **Embeddings & Reranking:** Jina Embeddings V3 (1024-dim dense + sparse) + Jina Cross-Encoder Reranker.
- **Vector DB:** Qdrant Cloud / Local Memory with Reciprocal Rank Fusion (RRF).

---

### 🛡️ Enterprise Text-to-SQL & Adversarial Safety

GlobleMind's SQL retrieval stage (`src/stages/s12b_sql_retrieval.py`) converts natural language into performant, secure SQL with comprehensive multi-layer defense gates:
- **`sqlglot` AST Validation:** Enforces read-only `SELECT` statements; blocks `DROP`, `UPDATE`, `DELETE`, `INTO OUTFILE`, and `LOAD_FILE`.
- **CTE Table Shadowing Protection:** Detects and blocks malicious CTEs designed to spoof physical table names and evade column security policies.
- **Cartesian Explosion Clamping:** Detects implicit comma-joins lacking `ON` conditions and clamps unbounded queries to `LIMIT 100`.
- **Column Registry & Synonyms:** Maps domain-specific jargon, synonyms, and business metrics to exact physical schema columns.
- **1-Hop Relationship Graph Expansion:** Automatically resolves join paths across foreign key relationships without hallucinating joins.
- **Delta Self-Repair:** Automatically analyzes database syntax errors and repairs SQL queries in real-time.

---

### 📊 Benchmark & Evaluation Results

GlobleMind has been comprehensively benchmarked across an enterprise evaluation suite of **163 complex real-world ERP questions**:

| Metric | Benchmark Result | Target SLA | Status |
|---|:---:|:---:|:---:|
| **Overall SQL Accuracy** | **96.3%** (157 / 163 scored 1.0) | $\ge 95.0\%$ | 🟢 **Achieved** |
| **Adversarial Defenses** | **5 / 5 Passed (100%)** | 100% | 🟢 **Secured** |
| **Cache Hit Latency** | **0.64s** ($0.0008\text{s}$ in-process) | $< 0.8\text{s}$ | 🟢 **Achieved** |
| **Cold-Start Pipeline Latency** | **3.5s – 5.5s** (Unthrottled Groq) | $12.0\text{s} – 15.0\text{s}$ | 🟢 **Beat SLA** |
| **Token Budget Compliance** | **7,577 avg tokens / query** | $\le 8,000$ tokens | 🟢 **Under Budget** |
| **Total Test Suite** | **372 Tests Passing** | 100% Green | 🟢 **Verified** |

---

### 📄 14-Stage Ingestion Pipeline

Documents are processed through a 14-stage pipeline designed for extreme accuracy:
1. **File Detection** (`s01`): Secure MIME type validation via `python-magic` and `filetype`.
2. **Classification** (`s02`): Zero-shot LLM classification.
3. **Parsing** (`s03`): Text extraction from PDF, DOCX, PPTX, XLSX, CSV, JSON, HTML, and TXT.
4. **OCR (Fallback)** (`s04`): `OCR.space` API extraction for scanned documents.
5. **Layout Analysis** (`s05`): Reading order determination for multi-column documents.
6. **Tables** (`s06`): Heuristics and vision models extracting tabular data into clean Markdown.
7. **Visual Analysis** (`s07_s08`): Deep chart/graph slicing with Vision LLM descriptive captioning.
8. **Chunking** (`s09`): Semantic token-based chunking with fractional overlap.
9. **Embeddings** (`s10`): Jina V3 Embeddings (1024-dim dense + sparse vectors).
10. **Vector Store** (`s11`): Commit to Qdrant Cloud with Reciprocal Rank Fusion (RRF).
11. **Retrieve** (`s12`): Hybrid Dense + Sparse search with metadata filtering.
12. **SQL Retrieval** (`s12b`): Schema RAG + NL2SQL + AST validation + Readonly execution.
13. **Rerank** (`s13`): Jina Cross-Encoder reranking top candidate chunks.
14. **Generate / Fast Path** (`s14`): Deterministic template formatting or LLM synthesis with inline citation footnotes.

---

### 💻 Modern React UI

A unified single-page React interface (Vite) served directly by FastAPI:
- **SSE Real-Time Streaming:** Live streaming responses with animated typing effects.
- **Thinking Traces:** Collapsible reasoning traces (understand → retrieve → rank → write) displayed above answers.
- **Mermaid Diagram Rendering:** Inline SVG rendering of Mermaid charts (`xychart-beta`, `pie`, `flowchart`).
- **PDF & Report Export:** Export conversations as formatted transcripts or restructured professional documents.
- **In-App Provider Selector:** Real-time switching between Groq, Gemini, NVIDIA NIM, and OpenRouter.
- **Theme Support:** Dark, light, and system-auto themes with adaptive CSS custom properties.

---

## 📂 Project Structure

```text
globle_mind/
├── LocalMind_UI/              # React frontend source code (Vite)
│   ├── src/
│   │   ├── components/        # Reusable UI components (Chat, Mermaid, ThinkingTrace, etc.)
│   │   ├── pages/             # Route-level components (Home, Documents, Settings, About)
│   │   ├── store/             # Zustand state management
│   │   └── styles/            # Design system & component CSS
│   ├── index.html
│   ├── vite.config.js
│   └── package.json
├── config/
│   └── providers.yaml         # Dynamic LLM routing rules & fallback chains
├── data/                      # Application state (flat JSON & SQLite live data)
│   ├── live_data.db           # SQLite database for Text-to-SQL stage
│   └── telemetry_events.jsonl # Structured latency and token usage telemetry
├── evals/                     # Evaluation benchmark suite (163 enterprise questions)
│   └── globalmind/
│       ├── questions.jsonl    # Master question set
│       └── baseline_v2/       # Automated evaluator & accuracy scorers
├── src/                       # Core Python Backend
│   ├── api/                   # FastAPI endpoints (query, upload, ui)
│   ├── core/                  # Engine logic (ProviderRouter, RateLimiter, DBClient, Dialects)
│   ├── models/                # Pydantic schemas
│   ├── pipeline/              # Orchestrators (Ingestion, QueryPipeline)
│   ├── stages/                # 14 Atomic RAG & SQL stages
│   └── utils/                 # Semantic Cache, Fast Path, Telemetry, Token Budget
├── tests/                     # 372 unit & integration tests
├── Dockerfile                 # Container image
└── pyproject.toml             # Python dependencies
```

---

## 🚀 Getting Started

### 1. Installation
```bash
# Clone the repository
git clone https://github.com/Mihirmaru22/Global_Mind.git
cd Global_Mind

# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate

# Install backend in editable mode
pip install -e .
```

### 2. Configure Environment
Copy `.env.example` to `.env` and add your API keys:
```bash
cp .env.example .env
```

```ini
# Multi-Key Groq Pool (comma-separated for 1.0M+ daily tokens)
GROQ_API_KEY=key1,key2,key3,key4,key5

# Google AI Studio
GEMINI_API_KEY=your_gemini_key

# NVIDIA NIM
NVIDIA_NIM_API_KEY=your_nvidia_key

# Jina AI (Embeddings + Reranker)
JINA_API_KEY=your_jina_key

# Qdrant Cloud
QDRANT_URL=your_qdrant_url
QDRANT_API_KEY=your_qdrant_key
```

### 3. Build Frontend & Start Server
```bash
# Build React UI
cd LocalMind_UI
npm install
npm run build
cd ..

# Start FastAPI server
python -m uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```
Open **http://localhost:8000** in your browser.

---

## 🧪 Running Tests

Run the full test suite (372 tests):
```bash
pytest tests/ -v
```

Run the core latency acceleration and Text-to-SQL suite:
```bash
pytest tests/test_semantic_cache.py tests/test_fast_path.py tests/test_sql_retrieval.py -v
```

---

## 📄 License
MIT License. Free for development and commercial use.
