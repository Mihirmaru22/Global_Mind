"""Ingestion Pipeline — orchestrates Stages 1–11.

Takes a file path, runs it through detection → classification → parsing →
OCR → layout → tables → visuals → chunking → embedding → vector store.

Features:
  - Deduplication via SHA-256 registry (skips already-ingested files)
  - True hybrid dense+sparse embeddings passed to vector store
  - ingest_with_progress() async generator for SSE-based progress streaming
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, AsyncGenerator

from src.core.config import settings
from src.core.ingestion_registry import IngestionRegistry, RegistryStatus
from src.core.provider_client import ProviderRouter
from src.core.rate_limiter import RateLimiter
from src.models.schemas import Chunk, ParsedDocument
from src.stages.s01_file_detection import detect_file
from src.stages.s02_classification import classify_semantic, classify_structure
from src.stages.s03_parsing import parse_document
from src.stages.s04_ocr import run_ocr
from src.stages.s05_layout import analyze_layout
from src.stages.s06_tables import extract_tables
from src.stages.s07_s08_visuals import analyze_visuals
from src.stages.s09_chunking import chunk_document
from src.stages.s10_embeddings import EmbeddingService
from src.stages.s11_vector_store import QdrantStore

logger = logging.getLogger(__name__)


# Stage labels for progress events
_STAGE_LABELS: dict[int, str] = {
    1: "File detection",
    2: "Document classification",
    3: "Content parsing",
    4: "OCR (scanned pages)",
    5: "Layout analysis",
    6: "Table extraction",
    7: "Visual analysis",
    8: "Chunking",
    9: "Embedding",
    10: "Storing in vector DB",
}


class IngestionPipeline:
    """Orchestrates the full document ingestion flow (Stages 1–11)."""

    def __init__(
        self,
        router: ProviderRouter | None = None,
        embedding_service: EmbeddingService | None = None,
        vector_store: QdrantStore | None = None,
        registry: IngestionRegistry | None = None,
    ) -> None:
        self._rate_limiter = RateLimiter()
        self._router = router or ProviderRouter()
        self._embeddings = embedding_service or EmbeddingService(self._rate_limiter)
        self._store = vector_store or QdrantStore()
        self._registry = registry or IngestionRegistry()

    async def ingest(self, file_path: str | Path) -> "IngestionResult":
        """Ingest a single document through the full pipeline.

        Checks the deduplication registry first:
          - Already ingested (same hash) → returns immediately with skipped=True
          - Content changed (same name, new hash) → deletes old vectors, re-ingests
          - New file → normal ingestion

        Returns an IngestionResult with metadata about what was processed.
        """
        path = Path(file_path)
        logger.info("=== Ingesting: %s ===", path.name)

        # ── Deduplication check ──────────────────────────────────────────────
        check = self._registry.check(path)

        if check.status == RegistryStatus.ALREADY_INGESTED:
            entry = check.old_entry or {}
            logger.info("Skipping '%s' — already ingested (hash match)", path.name)
            return IngestionResult(
                file_path=str(path),
                file_category=entry.get("file_category", "unknown"),
                document_type=entry.get("document_type", "general"),
                total_pages=entry.get("total_pages", 0),
                total_chunks=entry.get("total_chunks", 0),
                warnings=[],
                skipped=True,
            )

        if check.status == RegistryStatus.CONTENT_CHANGED and check.old_document_id:
            logger.info(
                "Content changed for '%s' — removing old vectors (doc_id=%s)",
                path.name,
                check.old_document_id,
            )
            try:
                await self._store.delete_document(check.old_document_id)
            except Exception as e:
                logger.warning("Failed to delete old document vectors: %s", e)

        # ── Pipeline ────────────────────────────────────────────────────────
        result = await self._run_pipeline(path)

        # Register after successful ingestion
        self._registry.register(
            path,
            document_id=result.document_id,
            total_chunks=result.total_chunks,
            sha256=check.sha256,
        )

        return result

    async def ingest_with_progress(
        self, file_path: str | Path
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Async generator that yields SSE-compatible progress events for each stage.

        Each event dict has: stage (int), label (str), status ("running"|"done"|"skipped"|"error")
        The final event has type="complete" with the full IngestionResult dict.

        Usage:
            async for event in pipeline.ingest_with_progress(path):
                yield f"data: {json.dumps(event)}\\n\\n"
        """
        path = Path(file_path)

        def _event(stage: int, status: str, **extra: Any) -> dict[str, Any]:
            return {
                "type": "progress",
                "stage": stage,
                "total_stages": len(_STAGE_LABELS),
                "label": _STAGE_LABELS.get(stage, f"Stage {stage}"),
                "status": status,
                **extra,
            }

        # ── Deduplication check ──────────────────────────────────────────────
        check = self._registry.check(path)
        if check.status == RegistryStatus.ALREADY_INGESTED:
            entry = check.old_entry or {}
            yield {"type": "skipped", "file": path.name, "reason": "Already ingested (content unchanged)"}
            yield {
                "type": "complete",
                "skipped": True,
                "result": {
                    "file_path": str(path),
                    "total_chunks": entry.get("total_chunks", 0),
                    "total_pages": entry.get("total_pages", 0),
                    "warnings": [],
                },
            }
            return

        if check.status == RegistryStatus.CONTENT_CHANGED and check.old_document_id:
            yield {"type": "info", "message": f"Content changed — removing old vectors for '{path.name}'"}
            try:
                await self._store.delete_document(check.old_document_id)
            except Exception as e:
                logger.warning("Failed to delete old document vectors: %s", e)

        # ── Stage 1: File Detection ──────────────────────────────────────────
        yield _event(1, "running")
        try:
            detection = detect_file(path)
            yield _event(1, "done", detail=detection.file_category.value)
        except Exception as e:
            yield _event(1, "error", error=str(e))
            yield {"type": "error", "message": str(e)}
            return

        # ── Stage 2: Classification ──────────────────────────────────────────
        yield _event(2, "running")
        try:
            classification = classify_structure(path, detection)
            yield _event(2, "done", detail=classification.structural.value)
        except Exception as e:
            yield _event(2, "error", error=str(e))
            return

        # ── Stage 3: Parsing ─────────────────────────────────────────────────
        yield _event(3, "running")
        try:
            document = parse_document(path, detection, classification)
            # Semantic classification needs parsed text
            text_sample = ""
            for page in document.pages:
                if page.text:
                    text_sample += page.text
                    if len(text_sample) > 2000:
                        break
            document.document_type = await classify_semantic(text_sample, detection, self._router)
            yield _event(3, "done", detail=f"{document.total_pages} pages, type={document.document_type.value}")
        except Exception as e:
            yield _event(3, "error", error=str(e))
            return

        # ── Stage 4: OCR ─────────────────────────────────────────────────────
        yield _event(4, "running")
        try:
            document = await run_ocr(document, self._router)
            yield _event(4, "done")
        except Exception as e:
            yield _event(4, "error", error=str(e))
            return

        # ── Stage 5: Layout Analysis ─────────────────────────────────────────
        yield _event(5, "running")
        try:
            document = await analyze_layout(document, self._router)
            yield _event(5, "done")
        except Exception as e:
            yield _event(5, "error", error=str(e))
            return

        # ── Stage 6: Table Extraction ────────────────────────────────────────
        yield _event(6, "running")
        try:
            document = await extract_tables(document, self._router)
            table_count = sum(len(p.tables) for p in document.pages)
            yield _event(6, "done", detail=f"{table_count} tables")
        except Exception as e:
            yield _event(6, "error", error=str(e))
            return

        # ── Stage 7: Visual Analysis ─────────────────────────────────────────
        yield _event(7, "running")
        try:
            document = await analyze_visuals(document, self._router)
            yield _event(7, "done")
        except Exception as e:
            yield _event(7, "error", error=str(e))
            return

        # ── Stage 8: Chunking ────────────────────────────────────────────────
        yield _event(8, "running")
        try:
            chunks = chunk_document(document)
            yield _event(8, "done", detail=f"{len(chunks)} chunks")
        except Exception as e:
            yield _event(8, "error", error=str(e))
            return

        if not chunks:
            yield {"type": "warning", "message": "No chunks produced — document may be empty"}
            yield {
                "type": "complete",
                "skipped": False,
                "result": {
                    "file_path": str(path),
                    "total_chunks": 0,
                    "total_pages": document.total_pages,
                    "warnings": document.warnings,
                },
            }
            return

        # ── Stage 9: Embeddings ──────────────────────────────────────────────
        yield _event(9, "running", detail=f"Embedding {len(chunks)} chunks")
        try:
            vectors, sparse_vectors = await self._embeddings.embed_chunks(chunks)
            has_sparse = any(not sv.is_empty() for sv in sparse_vectors)
            yield _event(9, "done", detail=f"sparse={'yes' if has_sparse else 'no'}")
        except Exception as e:
            yield _event(9, "error", error=str(e))
            return

        # ── Stage 10: Vector Store ───────────────────────────────────────────
        yield _event(10, "running")
        try:
            await self._store.upsert(chunks, vectors, sparse_vectors)
            yield _event(10, "done")
        except Exception as e:
            yield _event(10, "error", error=str(e))
            return

        # ── Registration & Complete ──────────────────────────────────────────
        document_id = chunks[0].document_id if chunks else ""
        self._registry.register(
            path,
            document_id=document_id,
            total_chunks=len(chunks),
            sha256=check.sha256,
        )

        yield {
            "type": "complete",
            "skipped": False,
            "result": {
                "file_path": str(path),
                "file_category": detection.file_category.value,
                "document_type": document.document_type.value,
                "total_pages": document.total_pages,
                "total_chunks": len(chunks),
                "warnings": document.warnings,
                "document_id": document_id,
            },
        }

    # ------------------------------------------------------------------
    # Internal: shared pipeline logic (no progress events)
    # ------------------------------------------------------------------

    async def _run_pipeline(self, path: Path) -> "IngestionResult":
        """Run the full ingestion pipeline without progress events."""
        # Stage 1 — File Detection
        logger.info("[Stage 1] File detection")
        detection = detect_file(path)

        # Stage 2a — Structural Classification
        logger.info("[Stage 2a] Structural classification")
        classification = classify_structure(path, detection)

        # Stage 3 — Parsing
        logger.info("[Stage 3] Parsing")
        document = parse_document(path, detection, classification)

        # Stage 2b — Semantic Classification (needs text from parsing)
        logger.info("[Stage 2b] Semantic classification")
        text_sample = ""
        for page in document.pages:
            if page.text:
                text_sample += page.text
                if len(text_sample) > 2000:
                    break
        document.document_type = await classify_semantic(text_sample, detection, self._router)

        # Stage 4 — OCR (only on scanned pages)
        logger.info("[Stage 4] OCR")
        document = await run_ocr(document, self._router)

        # Stage 5 — Layout Analysis
        logger.info("[Stage 5] Layout analysis")
        document = await analyze_layout(document, self._router)

        # Stage 6 — Table Extraction
        logger.info("[Stage 6] Table extraction")
        document = await extract_tables(document, self._router)

        # Stages 7-8 — Visual Analysis
        logger.info("[Stages 7-8] Visual analysis")
        document = await analyze_visuals(document, self._router)

        # Stage 9 — Chunking
        logger.info("[Stage 9] Chunking")
        chunks = chunk_document(document)

        if not chunks:
            logger.warning("No chunks produced from '%s'", path.name)
            return IngestionResult(
                file_path=str(path),
                file_category=detection.file_category.value,
                document_type=document.document_type.value,
                total_pages=document.total_pages,
                total_chunks=0,
                warnings=document.warnings + ["No chunks produced"],
                document_id="",
            )

        # Stage 10 — Embeddings (returns dense + sparse)
        logger.info("[Stage 10] Embedding %d chunks", len(chunks))
        vectors, sparse_vectors = await self._embeddings.embed_chunks(chunks)

        # Stage 11 — Vector Store (with sparse vectors)
        logger.info("[Stage 11] Storing in vector DB")
        await self._store.upsert(chunks, vectors, sparse_vectors)

        document_id = chunks[0].document_id if chunks else ""

        result = IngestionResult(
            file_path=str(path),
            file_category=detection.file_category.value,
            document_type=document.document_type.value,
            total_pages=document.total_pages,
            total_chunks=len(chunks),
            warnings=document.warnings,
            document_id=document_id,
        )

        logger.info(
            "=== Ingestion complete: %s → %d chunks stored ===",
            path.name,
            len(chunks),
        )
        return result


class IngestionResult:
    """Result of a document ingestion."""

    def __init__(
        self,
        file_path: str,
        file_category: str,
        document_type: str,
        total_pages: int,
        total_chunks: int,
        warnings: list[str] | None = None,
        skipped: bool = False,
        document_id: str = "",
    ) -> None:
        self.file_path = file_path
        self.file_category = file_category
        self.document_type = document_type
        self.total_pages = total_pages
        self.total_chunks = total_chunks
        self.warnings = warnings or []
        self.skipped = skipped
        self.document_id = document_id

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "file_category": self.file_category,
            "document_type": self.document_type,
            "total_pages": self.total_pages,
            "total_chunks": self.total_chunks,
            "warnings": self.warnings,
            "skipped": self.skipped,
            "document_id": self.document_id,
        }
