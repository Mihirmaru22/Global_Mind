"""Failure capture utility for logging exact failed SQL queries, errors, and metadata."""

from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path
from typing import Any

from src.utils.error_classification import classify_error, normalize_error

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_FAILURE_LOG_FILE = DATA_DIR / "failed_queries.jsonl"


def capture_sql_failure(
    query_id: str | None = None,
    stage: str = "sql_execution",
    failed_sql: str = "",
    raw_error: str | Exception = "unknown_error",
    error_type: str | None = None,
    schema_tables: list[str] | None = None,
    file_path: str | Path | None = None,
) -> dict[str, Any]:
    """Capture a SQL validation or execution failure safely to the failure log.

    Appends structured failure details to data/failed_queries.jsonl.
    Never throws exceptions into the calling pipeline.
    """
    try:
        from src.utils.telemetry import get_current_query_id

        err_str = str(raw_error) if raw_error is not None else "unknown_error"
        resolved_error_type = error_type or classify_error(raw_error)
        clean_error = normalize_error(raw_error)

        effective_qid = str(query_id) if query_id else (get_current_query_id() or "unknown_query")

        record: dict[str, Any] = {
            "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
            "query_id": effective_qid,
            "stage": str(stage),
            "error_type": resolved_error_type,
            "failed_sql": str(failed_sql).strip(),
            "raw_error": err_str,
            "normalized_error": clean_error,
            "schema_tables": list(schema_tables or []),
        }

        # Determine target file
        target_path = Path(file_path) if file_path else DEFAULT_FAILURE_LOG_FILE

        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with open(target_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as file_exc:
            logger.warning("Failed to write to failure capture log at %s: %s", target_path, file_exc)

        return record

    except Exception as exc:
        logger.warning("capture_sql_failure encountered an unexpected error: %s", exc)
        return {}
