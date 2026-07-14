"""FastAPI application - the main entry point for the web service."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.core.config import PROJECT_ROOT, settings
from src.core.paths import contained_path
from src.services.document_watcher import DocumentWatcher

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
<<<<<<< HEAD
    """Startup/shutdown hooks.

    On startup:
      * reconcile the vector store's chunk ``active`` flags with the durable
        document registry. Because metadata now lives in Qdrant (the single
        source of truth), a fresh container/redeploy comes up with the correct
        registry state; this heals any chunk-flag drift left by a crash mid
        version-cutover, so superseded content never resurfaces after a restart;
      * optionally scan the drop-folder once (``AUTO_INGEST_ON_STARTUP``);
      * optionally launch a background loop that re-scans the drop-folder every
        ``AUTO_INGEST_INTERVAL_SECONDS`` seconds.

    Everything here is best-effort — a failure must never block the app from
    serving.
    """
    if settings.qdrant_url and settings.qdrant_api_key:
=======
    watcher = DocumentWatcher()
    app.state.document_watcher = watcher
    try:
        watcher.start(asyncio.get_running_loop())
    except Exception:
        logger.exception("Failed to start document watcher")
    try:
        await watcher.refresh_directory_state()
    except Exception:
        logger.exception("Failed to check uploads directory state")
    try:
        yield
    finally:
>>>>>>> origin/feature/backend-auto-ingestion
        try:
            await watcher.stop()
        except Exception:
<<<<<<< HEAD
            logger.exception("Startup reconcile failed — continuing without it")

    if settings.auto_ingest_on_startup:
        try:
            from src.pipeline.folder_ingestion import scan_and_ingest

            result = await scan_and_ingest()
            logger.info("Startup folder scan: %s", result.message)
        except Exception:
            logger.exception("Startup folder scan failed — continuing without it")

    scan_task = None
    if settings.auto_ingest_interval_seconds > 0:
        from src.pipeline.folder_ingestion import run_periodic_scan

        scan_task = asyncio.create_task(
            run_periodic_scan(settings.auto_ingest_interval_seconds)
        )

    try:
        yield
    finally:
        if scan_task is not None:
            scan_task.cancel()
            try:
                await scan_task
            except asyncio.CancelledError:
                pass
=======
            logger.exception("Failed to stop document watcher")
>>>>>>> origin/feature/backend-auto-ingestion


app = FastAPI(
    title="GlobleMind",
    description="Zero-Cost Enterprise RAG Pipeline - accuracy-first document processing",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

settings.ensure_dirs()

frontend_dir = PROJECT_ROOT / "frontend"
if frontend_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(frontend_dir / "assets")), name="assets")

from src.api.notifications import router as notifications_router  # noqa: E402
from src.api.query import router as query_router  # noqa: E402
from src.api.ui import router as ui_router  # noqa: E402
from src.api.upload import router as upload_router  # noqa: E402

app.include_router(upload_router, prefix="/api")
app.include_router(query_router, prefix="/api")
app.include_router(ui_router, prefix="/api")
app.include_router(notifications_router, prefix="/api")


@app.get("/api/health")
async def health_check() -> dict:
    """Health check with provider availability status."""
    from src.core.provider_client import ProviderRouter

    router = ProviderRouter()
    available = {name: provider.is_available for name, provider in router._providers.items()}

    return {
        "status": "healthy",
        "providers": available,
        "has_any_llm": any(available.values()),
    }


@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    """Serve the React Single Page App."""
    if not frontend_dir.exists():
        return {
            "app": "GlobleMind API",
            "docs": "/docs",
            "health": "/api/health",
            "status": "Frontend not built yet. Run 'npm run build' in LocalMind_UI.",
        }

    file_path = contained_path(frontend_dir, full_path)
    if file_path is not None and file_path.is_file():
        return FileResponse(file_path)

    return FileResponse(frontend_dir / "index.html")
