"""Background ingestion triggers used by the document watcher."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from src.pipeline.ingestion import IngestionPipeline

logger = logging.getLogger(__name__)

_PATH_LOCKS: dict[str, asyncio.Lock] = {}


def _canonical_key(file_path: str | Path) -> str:
    return str(Path(file_path).resolve())


def _get_path_lock(key: str) -> asyncio.Lock:
    lock = _PATH_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _PATH_LOCKS[key] = lock
    return lock


async def start_ingestion(file_path: str | Path, pipeline: IngestionPipeline | None = None):
    """Run ingestion for a single file while serializing duplicate triggers."""
    path = Path(file_path)
    key = _canonical_key(path)
    lock = _get_path_lock(key)

    async with lock:
        logger.info("Starting ingestion trigger for '%s'", path.name)
        active_pipeline = pipeline or IngestionPipeline()
        result = await active_pipeline.ingest(path)
        logger.info(
            "Ingestion trigger finished for '%s' (skipped=%s, chunks=%d)",
            path.name,
            getattr(result, "skipped", False),
            result.total_chunks,
        )
        return result


async def start_ingestion_with_progress(file_path: str | Path, pipeline: IngestionPipeline | None = None):
    """Yield ingestion progress events for a single file."""
    path = Path(file_path)
    active_pipeline = pipeline or IngestionPipeline()
    async for event in active_pipeline.ingest_with_progress(path):
        yield event

