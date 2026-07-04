"""Upload API — file ingestion endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from pathlib import Path
from typing import AsyncGenerator

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from src.core.config import settings
from src.pipeline.ingestion import IngestionPipeline

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/upload")
async def upload_document(file: UploadFile = File(...)) -> dict:
    """Upload and ingest a single document into the RAG pipeline."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    upload_path = settings.upload_dir / file.filename
    try:
        with open(upload_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")

    try:
        pipeline = IngestionPipeline()
        result = await pipeline.ingest(upload_path)
        return {
            "status": "success",
            "message": f"Ingested '{file.filename}' successfully",
            **result.to_dict(),
        }
    except Exception as e:
        logger.exception("Ingestion failed for '%s'", file.filename)
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {e}")


@router.post("/upload/batch")
async def upload_documents_batch(files: list[UploadFile] = File(...)) -> dict:
    """Upload and ingest multiple documents concurrently (max 3 at a time)."""
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    pipeline = IngestionPipeline()
    semaphore = asyncio.Semaphore(3)
    results = []
    errors = []

    async def _process_file(file: UploadFile) -> None:
        if not file.filename:
            return
        
        upload_path = settings.upload_dir / file.filename
        try:
            with open(upload_path, "wb") as f:
                shutil.copyfileobj(file.file, f)
        except Exception as e:
            errors.append({"file": file.filename, "error": f"Failed to save: {e}"})
            return

        async with semaphore:
            try:
                res = await pipeline.ingest(upload_path)
                results.append(res.to_dict())
            except Exception as e:
                logger.exception("Batch ingestion failed for '%s'", file.filename)
                errors.append({"file": file.filename, "error": str(e)})

    await asyncio.gather(*[_process_file(f) for f in files])

    return {
        "status": "success" if not errors else "partial_success",
        "processed_count": len(results),
        "error_count": len(errors),
        "results": results,
        "errors": errors,
    }


@router.post("/upload/stream")
async def upload_document_stream(file: UploadFile = File(...)):
    """Upload a document and receive real-time ingestion progress via SSE."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    upload_path = settings.upload_dir / file.filename
    try:
        with open(upload_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")

    pipeline = IngestionPipeline()

    async def _event_generator() -> AsyncGenerator[str, None]:
        try:
            async for event in pipeline.ingest_with_progress(upload_path):
                # Format as Server-Sent Events (SSE)
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            error_event = {"stage": 0, "label": "complete", "status": "error", "error": str(e)}
            yield f"data: {json.dumps(error_event)}\n\n"

    return StreamingResponse(_event_generator(), media_type="text/event-stream")
