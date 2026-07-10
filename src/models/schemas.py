"""Pydantic data models for the entire pipeline.

Every stage produces typed outputs that flow into the next stage.
Models are intentionally flat where possible — deep nesting is avoided
unless the data genuinely has hierarchical structure (chunks do).
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Stage 1 — File Detection
# ---------------------------------------------------------------------------

class FileCategory(str, Enum):
    """Broad file category determined by magic bytes / extension."""
    PDF = "pdf"
    DOCX = "docx"
    DOC = "doc"
    PPTX = "pptx"
    PPT = "ppt"
    XLSX = "xlsx"
    XLS = "xls"
    CSV = "csv"
    TSV = "tsv"
    MARKDOWN = "markdown"
    PLAINTEXT = "plaintext"
    HTML = "html"
    XML = "xml"
    JSON = "json"
    IMAGE = "image"
    UNKNOWN = "unknown"


class FileDetectionResult(BaseModel):
    """Output of Stage 1 — what kind of file is this?"""
    file_path: str
    file_category: FileCategory
    mime_type: str
    file_size_bytes: int
    extension: str


# ---------------------------------------------------------------------------
# Stage 2 — Classification
# ---------------------------------------------------------------------------

class PageStructure(str, Enum):
    """Per-page structural classification."""
    NATIVE_TEXT = "native_text"
    SCANNED = "scanned"
    MIXED = "mixed"


class DocumentType(str, Enum):
    """Semantic document type — drives downstream extraction behavior."""
    SCIENTIFIC_PAPER = "scientific_paper"
    FINANCIAL_REPORT = "financial_report"
    LEGAL_CONTRACT = "legal_contract"
    INVOICE = "invoice"
    FORM = "form"
    PRESENTATION = "presentation"
    SPREADSHEET = "spreadsheet"
    GENERAL = "general"


class ClassificationResult(BaseModel):
    """Output of Stage 2 — structural + semantic classification."""
    structural: PageStructure
    page_structures: list[PageStructure] = Field(default_factory=list)
    document_type: DocumentType = DocumentType.GENERAL
    classification_confidence: float = 1.0


# ---------------------------------------------------------------------------
# Stage 3–8 — Parsed content
# ---------------------------------------------------------------------------

class TableData(BaseModel):
    """An extracted table — kept atomic, never split during chunking."""
    page_number: int
    table_index: int = 0
    markdown: str = ""
    html: str = ""
    rows: list[list[str]] = Field(default_factory=list)
    confidence: float = 1.0
    extraction_method: str = ""


class FigureData(BaseModel):
    """An extracted figure/chart/image with its description."""
    page_number: int
    figure_index: int = 0
    caption: str = ""
    description: str = ""
    image_path: str = ""
    confidence: float = 1.0
    extraction_method: str = ""


class PageContent(BaseModel):
    """Parsed content for a single page."""
    page_number: int
    structure: PageStructure = PageStructure.NATIVE_TEXT
    text: str = ""
    markdown: str = ""
    tables: list[TableData] = Field(default_factory=list)
    figures: list[FigureData] = Field(default_factory=list)
    ocr_confidence: float = 1.0
    ocr_method: str = ""
    layout_headings: list[str] = Field(default_factory=list)


class ParsedDocument(BaseModel):
    """Unified output of Stages 3–8 — the fully parsed document."""
    file_path: str
    file_category: FileCategory
    document_type: DocumentType = DocumentType.GENERAL
    total_pages: int = 0
    pages: list[PageContent] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Stage 9 — Chunks
# ---------------------------------------------------------------------------

class ChunkType(str, Enum):
    """What kind of content this chunk holds — affects retrieval behavior."""
    PROSE = "prose"
    TABLE = "table"
    FIGURE_CAPTION = "figure_caption"
    FOOTNOTE = "footnote"
    HEADING = "heading"
    CODE = "code"
    KEY_VALUE = "key_value"
    SQL_RESULT = "sql_result"


class Chunk(BaseModel):
    """A single chunk ready for embedding and storage."""
    chunk_id: str
    document_id: str
    chunk_type: ChunkType = ChunkType.PROSE
    content: str
    token_count: int = 0

    # Hierarchy metadata for parent-document retrieval
    page_number: int = 0
    section_hierarchy: list[str] = Field(default_factory=list)
    parent_chunk_id: str | None = None

    # Provenance
    document_type: DocumentType = DocumentType.GENERAL
    source_file: str = ""
    confidence: float = 1.0


# ---------------------------------------------------------------------------
# Stage 12–14 — Retrieval and generation
# ---------------------------------------------------------------------------

class RetrievedChunk(BaseModel):
    """A chunk returned by retrieval, scored and ready for reranking."""
    chunk: Chunk
    score: float = 0.0
    retrieval_method: str = ""  # "dense", "sparse", "hybrid"


class Citation(BaseModel):
    """A citation linking an answer span to a source chunk."""
    chunk_id: str
    source_file: str
    page_number: int = 0
    relevance_score: float = 0.0


class ThinkingStep(BaseModel):
    """One step in the query's reasoning trace, shown as a persistent
    Claude-style 'thinking' block in the UI."""
    label: str
    detail: str = ""


class QueryResult(BaseModel):
    """Final output of the query pipeline."""
    query: str
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    model_used: str = ""
    reasoning_task: str = ""
    chunks_retrieved: int = 0
    chunks_after_rerank: int = 0
    thinking: list[ThinkingStep] = Field(default_factory=list)
