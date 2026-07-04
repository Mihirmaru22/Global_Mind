"""FastAPI application — the main entry point for the web service."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.core.config import PROJECT_ROOT, settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)

app = FastAPI(
    title="GlobleMind",
    description="Zero-Cost Enterprise RAG Pipeline — accuracy-first document processing",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure runtime directories exist
settings.ensure_dirs()

# Mount frontend static files
frontend_dir = PROJECT_ROOT / "frontend"
if frontend_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(frontend_dir / "assets")), name="assets")

# Register API routes
from src.api.upload import router as upload_router  # noqa: E402
from src.api.query import router as query_router  # noqa: E402
from src.api.ui import router as ui_router  # noqa: E402

app.include_router(upload_router, prefix="/api")
app.include_router(query_router, prefix="/api")
app.include_router(ui_router, prefix="/api")


@app.get("/api/health")
async def health_check() -> dict:
    """Health check with provider availability status."""
    from src.core.provider_client import ProviderRouter

    router = ProviderRouter()
    available = {name: p.is_available for name, p in router._providers.items()}

    return {
        "status": "healthy",
        "providers": available,
        "has_any_llm": any(available.values()),
    }


# Catch-all route to serve the React SPA
from fastapi.responses import FileResponse # noqa: E402

@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    """Serve the React Single Page App."""
    if not frontend_dir.exists():
        return {
            "app": "GlobleMind API",
            "docs": "/docs",
            "health": "/api/health",
            "status": "Frontend not built yet. Run 'npm run build' in LocalMind_UI."
        }
    
    # If the file exists in the root of frontend (e.g., vite.svg), serve it
    file_path = frontend_dir / full_path
    if full_path and file_path.exists() and file_path.is_file():
        return FileResponse(file_path)
    
    # Otherwise, return index.html for client-side routing
    return FileResponse(frontend_dir / "index.html")
