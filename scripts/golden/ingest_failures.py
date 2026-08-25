"""Ingest real failure records from failed_queries.jsonl, scrub PII, and generate draft golden cases."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from src.utils.error_classification import normalize_error
from src.utils.golden_models import GoldenCase

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_INPUT_FILE = PROJECT_ROOT / "data" / "failed_queries.jsonl"
DEFAULT_DRAFT_OUTPUT = PROJECT_ROOT / "tests" / "golden" / "sql_repair" / "draft_cases.json"

# PII and Credential Scrubbing Patterns
_API_KEY_RE = re.compile(r"(?:bearer\s+[a-zA-Z0-9_\-\.]{20,}|(?:sk|pk|api|key)[-_][a-zA-Z0-9]{16,})", re.IGNORECASE)
_PASSWORD_RE = re.compile(r'((?:password|passwd|pwd|secret|key)\s*=\s*)[^\s;&,\'"]+', re.IGNORECASE)
_EMAIL_RE = re.compile(r"\b[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+\b")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CC_RE = re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b")
_PHONE_RE = re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")


def anonymize_sql_and_error(text: str) -> str:
    """Scrub emails, phones, SSNs, credit cards, and credentials from text/SQL."""
    if not text:
        return ""
    cleaned = text
    cleaned = _API_KEY_RE.sub("[API_KEY]", cleaned)
    cleaned = _PASSWORD_RE.sub(r"\1[PASSWORD]", cleaned)
    cleaned = _EMAIL_RE.sub("[EMAIL]", cleaned)
    cleaned = _SSN_RE.sub("[SSN]", cleaned)
    cleaned = _CC_RE.sub("[CC]", cleaned)
    cleaned = _PHONE_RE.sub("[PHONE]", cleaned)
    return cleaned


def ingest_failures(
    input_file: Path | None = None,
    output_file: Path | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Read failure logs, sanitize PII, and generate draft GoldenCase items for review."""
    src_path = input_file or DEFAULT_INPUT_FILE
    dst_path = output_file or DEFAULT_DRAFT_OUTPUT

    if not src_path.exists():
        print(f"No failure log found at {src_path}. Writing empty draft list.")
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        dst_path.write_text("[]", encoding="utf-8")
        return []

    draft_cases: list[dict[str, Any]] = []
    seen_queries: set[str] = set()

    with open(src_path, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue

            raw_sql = rec.get("failed_sql", "").strip()
            if not raw_sql or raw_sql in seen_queries:
                continue
            seen_queries.add(raw_sql)

            clean_sql = anonymize_sql_and_error(raw_sql)
            raw_err = rec.get("raw_error", "")
            norm_err = normalize_error(anonymize_sql_and_error(str(raw_err)))
            err_type = rec.get("error_type", "unknown_error")
            schema_tables = rec.get("schema_tables", [])
            qid = rec.get("query_id", f"draft_{idx}")

            draft_item = {
                "case_id": f"draft_{qid}",
                "description": f"Ingested failure from query {qid}: {err_type}",
                "user_question": "[HUMAN_REVIEW_REQUIRED: Add natural language query]",
                "failed_sql": clean_sql,
                "error_message": norm_err,
                "error_type": err_type,
                "schema_context": {tbl: [] for tbl in schema_tables},
                "expected_sql_contains": ["[HUMAN_REVIEW_REQUIRED: Add expected substrings]"],
                "must_not_contain": ["[HUMAN_REVIEW_REQUIRED: Add forbidden substrings]"],
                "metadata": {
                    "source_query_id": qid,
                    "original_timestamp": rec.get("timestamp"),
                    "stage": rec.get("stage"),
                },
            }
            draft_cases.append(draft_item)
            if limit and len(draft_cases) >= limit:
                break

    dst_path.parent.mkdir(parents=True, exist_ok=True)
    with open(dst_path, "w", encoding="utf-8") as f:
        json.dump(draft_cases, f, indent=2, ensure_ascii=False)

    print(f"Successfully processed {len(draft_cases)} draft cases from {src_path} -> {dst_path}")
    return draft_cases


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest and anonymize SQL failure logs into draft golden cases.")
    parser.add_argument("--input", type=str, default=str(DEFAULT_INPUT_FILE), help="Input failed_queries.jsonl path")
    parser.add_argument("--output", type=str, default=str(DEFAULT_DRAFT_OUTPUT), help="Output draft_cases.json path")
    parser.add_argument("--limit", type=int, default=None, help="Max cases to ingest")

    args = parser.parse_args()
    ingest_failures(
        input_file=Path(args.input),
        output_file=Path(args.output),
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
