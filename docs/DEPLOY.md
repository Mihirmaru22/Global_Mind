# Deploying GlobleMind

GlobleMind is a **Python FastAPI** app that serves both the API and the bundled
React UI from one process, and streams responses over **SSE**. It needs a host
that can run a long-lived ASGI server (`uvicorn`) without buffering.

> **Not suitable:** CloudLinux / cPanel / Plesk *shared* hosting. Those run
> Python only through Passenger (which buffers and breaks SSE streaming) and
> restrict long-running processes. Use a container host instead.

The repo ships a `Dockerfile`, so any container host works. Below is Render
(free tier); Railway is identical (it auto-detects the `Dockerfile`).

## Deploy on Render (from GitHub, auto-deploy)

1. Push this repo to GitHub (already done — `main`).
2. Render → **New → Blueprint** → connect the repo. Render reads `render.yaml`.
3. Set the secret env vars in the dashboard (values from your local `.env`):

   | Variable | Purpose |
   |---|---|
   | `GEMINI_API_KEY` | Gemini LLM/vision |
   | `GROQ_API_KEY` | Groq LLM |
   | `NVIDIA_NIM_API_KEY` | NVIDIA NIM (vision/LLM) |
   | `JINA_API_KEY` | Embeddings + reranker |
   | `OCR_SPACE_API_KEY` | OCR fallback |
   | `OPENROUTER_API_KEY` | OpenRouter (default provider) |
   | `OPENROUTER_TEXT_MODEL` | e.g. `tencent/hy3:free` |
   | `OPENROUTER_VISION_MODEL` | OpenRouter vision model |
   | `QDRANT_URL` | Qdrant Cloud endpoint |
   | `QDRANT_API_KEY` | Qdrant Cloud key |

   `DEFAULT_PROVIDER` and `DB_ENGINE` are preset in the blueprint.

4. Deploy. When it's live, open the Render URL — the chat UI loads and
   `/(api/health)` shows which providers are configured.

Every push to `main` redeploys automatically (`autoDeploy: true`).

## Notes

- **Streaming works out of the box** — uvicorn serves SSE directly, no proxy
  buffering to fight.
- **Qdrant is external** (Qdrant Cloud), so vectors persist across redeploys.
- **Local state is ephemeral on the free tier.** `data/` (chat history, the
  ingestion registry) lives on the container's disk, which resets on redeploy/
  sleep. Chats and the "already ingested" registry reset; the actual document
  vectors in Qdrant are unaffected. For durable chat history, attach a
  persistent disk (paid) mounted at `/app/data`, or move state to a DB later.
- **Cold starts:** the free plan sleeps after ~15 min idle; the first request
  after that takes ~30s to wake.

## Run locally with Docker

```bash
docker build -t globlemind .
docker run --rm -p 8000:8000 --env-file .env globlemind
# open http://localhost:8000
```
