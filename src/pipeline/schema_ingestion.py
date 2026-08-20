"""Schema Ingestion — sync the live database schema into the vector store.

Fetches the full database schema, splits it into one chunk per table,
embeds each chunk, and upserts them into Qdrant under
document_id="live_db_schema" with chunk_type=SQL_SCHEMA.

This powers Schema RAG: instead of pasting the entire (potentially huge)
schema into the NL→SQL prompt, the pipeline retrieves only the 5–10 most
relevant tables for the user's question.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from src.core.config import settings
from src.core.db_client import run_readonly_query
from src.core.sql_dialects import get_dialect_profile, SQLDialectProfile
from src.models.schemas import Chunk, ChunkType, DocumentType
from src.stages.s10_embeddings import EmbeddingService
from src.stages.s11_vector_store import QdrantStore
from src.stages.s12b_sql_retrieval import format_schema_rows, format_fk_rows

logger = logging.getLogger(__name__)

SCHEMA_DOCUMENT_ID = "live_db_schema"


def _split_mysql_tables(rows: list[dict[str, Any]]) -> dict[str, str]:
    """Group MySQL information_schema rows into per-table CREATE-TABLE-like text."""
    tables: dict[str, list[str]] = {}
    for i, row in enumerate(rows):
        if row.get("sql"):
            # Direct CREATE statement present
            name = row.get("name") or row.get("table_name") or f"table_{i}"
            tables[name] = [row["sql"]]
            continue
        tname = row.get("table_name") or row.get("TABLE_NAME") or row.get("name")
        cname = row.get("column_name") or row.get("COLUMN_NAME", "")
        ctype = row.get("data_type") or row.get("DATA_TYPE", "")
        if not tname:
            continue
        comment = row.get("column_comment") or ""
        suffix = f"  -- {comment}" if comment else ""
        tables.setdefault(tname, []).append(
            f"  {cname} {ctype}{suffix}".strip()
        )
    return {
        name: cols[0] if (len(cols) == 1 and cols[0].startswith("CREATE TABLE")) else f"TABLE {name} (\n" + ",\n".join(cols) + "\n)"
        for name, cols in tables.items()
    }


def _split_sqlite_tables(rows: list[dict[str, Any]]) -> dict[str, str]:
    """Split SQLite sqlite_master rows into per-table CREATE statements."""
    return {
        row["name"]: row["sql"]
        for row in rows
        if row.get("name") != "sqlite_sequence" and row.get("sql")
    }


def _split_schema_by_table(
    dialect: SQLDialectProfile, rows: list[dict[str, Any]]
) -> dict[str, str]:
    """Return {table_name: schema_text} for each table in the database."""
    if dialect.key == "mysql":
        return _split_mysql_tables(rows)
    if dialect.key == "sqlite":
        return _split_sqlite_tables(rows)
    raise ValueError(f"Unsupported dialect key {dialect.key!r}")


def _load_table_metadata() -> dict[str, dict[str, Any]]:
    """Load table domain and metadata from evals/globalmind/globalmind_schema.json if present."""
    from pathlib import Path
    schema_file = Path(__file__).resolve().parents[2] / "evals" / "globalmind" / "globalmind_schema.json"
    if not schema_file.exists():
        return {}
    try:
        import json
        data = json.loads(schema_file.read_text(encoding="utf-8"))
        tables = data.get("tables", [])
        return {t["name"].lower(): t for t in tables if isinstance(t, dict) and "name" in t}
    except Exception as e:
        logger.warning("Could not load schema metadata from %s: %s", schema_file, e)
        return {}


def _enrich_table_schema(
    table_name: str,
    schema_text: str,
    table_meta: dict[str, Any] | None = None,
    fk_lines: list[str] | None = None,
) -> str:
    """Format an enriched table chunk with domain header, primary key, and foreign keys."""
    lines: list[str] = []

    if table_meta:
        domain = table_meta.get("domain")
        pk = table_meta.get("primary_key")
        parts = [f"-- Table: {table_name}"]
        if domain:
            parts.append(f"Domain: {domain}")
        if pk:
            pk_str = ", ".join(pk) if isinstance(pk, list) else str(pk)
            parts.append(f"Primary Key: ({pk_str})")
        lines.append(" | ".join(parts))

    lines.append(schema_text)

    if fk_lines:
        lines.append("-- Relationships / Foreign Keys:")
        lines.extend(fk_lines)

    return "\n".join(lines)


async def sync_live_schema(
    embedding_service: EmbeddingService | None = None,
    vector_store: QdrantStore | None = None,
) -> dict[str, Any]:
    """Fetch the live DB schema, chunk per table, embed, and upsert to Qdrant.

    Returns a summary dict with table count and status.
    """
    from pathlib import Path
    import json
    from src.core.rate_limiter import get_shared_rate_limiter

    rate_limiter = get_shared_rate_limiter()
    embeddings = embedding_service or EmbeddingService(rate_limiter)
    store = vector_store or QdrantStore(embedding_service=embeddings)

    dialect = get_dialect_profile(settings.db_engine)

    # 1. Fetch schema rows from the live database
    schema_rows = await run_readonly_query(dialect.schema_query, max_rows=20000)
    if not schema_rows:
        return {"status": "error", "message": "No schema rows returned from database"}

    # 2. Split into per-table chunks
    table_schemas = _split_schema_by_table(dialect, schema_rows)

    # 3. Fetch FK info and attach to relevant tables
    fk_map: dict[str, list[str]] = {}
    try:
        if dialect.key == "mysql" and dialect.fk_query:
            fk_rows = await run_readonly_query(dialect.fk_query, max_rows=20000)
        elif dialect.key == "sqlite":
            from src.stages.s12b_sql_retrieval import fetch_sqlite_foreign_keys
            fk_rows = await fetch_sqlite_foreign_keys()
        else:
            fk_rows = []

        for fk_row in fk_rows:
            from_table = fk_row.get("table_name") or fk_row.get("TABLE_NAME", "")
            from_col = fk_row.get("column_name") or fk_row.get("COLUMN_NAME", "")
            to_table = fk_row.get("referenced_table_name") or fk_row.get("REFERENCED_TABLE_NAME", "")
            to_col = fk_row.get("referenced_column_name") or fk_row.get("REFERENCED_COLUMN_NAME", "")
            if from_table and to_table:
                fk_line = f"  FOREIGN KEY ({from_col}) REFERENCES {to_table}({to_col})"
                fk_map.setdefault(from_table, []).append(fk_line)
    except Exception as e:
        logger.warning("Could not fetch FK info for schema sync: %s", e)

    # If DB introspection gave no FKs (databases without formal FK constraints),
    # fall back to inferred relationships from config/sql_relationships.json
    if not fk_map:
        try:
            rel_path = Path(__file__).resolve().parents[2] / "config" / "sql_relationships.json"
            if rel_path.exists():
                rel_data = json.loads(rel_path.read_text(encoding="utf-8"))
                rels = rel_data.get("relationships") if isinstance(rel_data, dict) else rel_data
                for r in rels or []:
                    frm, fcol = r.get("from_table"), r.get("from_column")
                    to, tcol = r.get("to_table"), r.get("to_column")
                    if frm and fcol and to and tcol:
                        fk_line = f"  FOREIGN KEY ({fcol}) REFERENCES {to}({tcol})"
                        fk_map.setdefault(frm, []).append(fk_line)
        except Exception as e:
            logger.warning("Could not load fallback inferred relationships: %s", e)

    # 4. Build Chunk objects — one per table, enriched with domain metadata and FKs
    meta_map = _load_table_metadata()
    chunks: list[Chunk] = []
    for table_name, schema_text in table_schemas.items():
        enriched_content = _enrich_table_schema(
            table_name=table_name,
            schema_text=schema_text,
            table_meta=meta_map.get(table_name.lower()),
            fk_lines=fk_map.get(table_name),
        )

        chunk_id = f"schema_{table_name}"
        chunks.append(
            Chunk(
                chunk_id=chunk_id,
                document_id=SCHEMA_DOCUMENT_ID,
                chunk_type=ChunkType.SQL_SCHEMA,
                content=enriched_content,
                token_count=len(enriched_content) // 4,  # rough estimate
                document_type=DocumentType.DATABASE,
                source_file=f"live_database/{table_name}",
            )
        )

    if not chunks:
        return {"status": "error", "message": "No tables found in schema"}

    # 5. Embed all table chunks FIRST — if embedding fails/rate-limits, old schema remains safe
    vectors, sparse_vectors = await embeddings.embed_chunks(chunks)

    # 6. Upsert new chunks into Qdrant — with deterministic per-table IDs, existing chunks
    # are atomically updated in place with zero downtime or empty-store window
    await store.upsert(chunks, vectors, sparse_vectors)

    # 7. Invalidate in-memory schema cache on SQLRetriever so next query picks up new schema
    try:
        from src.stages.s12b_sql_retrieval import SQLRetriever
        SQLRetriever.clear_schema_cache()
    except Exception as e:
        logger.warning("Could not clear SQLRetriever schema cache: %s", e)

    logger.info(
        "Schema sync complete: %d tables embedded and upserted to Qdrant",
        len(chunks),
    )

    return {
        "status": "ok",
        "tables_synced": len(chunks),
        "table_names": sorted(table_schemas.keys()),
    }
