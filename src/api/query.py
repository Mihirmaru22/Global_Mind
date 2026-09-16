"""Query API — RAG query endpoint."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from src.api.auth import get_current_user_optional
from src.pipeline.query import QueryPipeline

logger = logging.getLogger(__name__)
router = APIRouter()


class QueryRequest(BaseModel):
    """Request body for the query endpoint."""

    question: str
    top_k: int = 30
    rerank_top_k: int = 6
    filters: dict[str, Any] | None = None


@router.post("/query")
async def query_documents(
    request: QueryRequest,
    current_user: str = Depends(get_current_user_optional),
) -> dict:
    """Query ingested documents using the RAG pipeline.

    Supports optional metadata filtering via the ``filters`` field to
    constrain retrieval to specific document types, files, or page ranges.
    """
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    query_filters = dict(request.filters or {})
    if current_user and current_user not in ("*", "all", "anonymous"):
        query_filters.setdefault("user_id", current_user)

    try:
        pipeline = QueryPipeline()
        result = await pipeline.query(request.question, filters=query_filters or None)
        return {
            "status": "success",
            "query": result.query,
            "answer": result.answer,
            "citations": [c.model_dump() for c in result.citations],
            "model_used": result.model_used,
            "chunks_retrieved": result.chunks_retrieved,
            "chunks_after_rerank": result.chunks_after_rerank,
            "filters_applied": request.filters,
        }
    except Exception:
        # Log the full error server-side; return a generic message so internal
        # details (paths, provider errors, keys in messages) don't leak.
        logger.exception("Query failed")
        raise HTTPException(status_code=500, detail="Query failed. Please try again.")
