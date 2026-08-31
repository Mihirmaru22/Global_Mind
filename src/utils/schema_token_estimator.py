"""Schema token estimation and budget calculation utilities."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def estimate_schema_tokens(schema_representation: str | dict[str, Any] | list[Any] | Any) -> int:
    """Estimate the token cost of a schema chunk or representation.

    Handles:
    - String (DDL text, CREATE TABLE statements, Markdown schemas)
    - Dictionary (e.g. {"table_name": "...", "ddl": "..."} or {"table": ["col1", "col2"]})
    - List of columns or tables

    Uses conservative heuristic matching Phase 5 token counter (4 chars/token or 1.3 words/token).
    """
    if not schema_representation:
        return 0

    try:
        if isinstance(schema_representation, str):
            text = schema_representation.strip()
        elif isinstance(schema_representation, dict):
            if "ddl" in schema_representation and isinstance(schema_representation["ddl"], str):
                text = schema_representation["ddl"].strip()
            else:
                parts: list[str] = []
                for k, v in schema_representation.items():
                    if isinstance(v, (list, tuple, set)):
                        parts.append(f"Table '{k}': {', '.join(str(c) for c in v if c)}")
                    elif isinstance(v, dict):
                        parts.append(f"Table '{k}': {', '.join(str(c) for c in v.keys() if c)}")
                    else:
                        parts.append(f"{k}: {v}")
                text = "\n".join(parts)
        elif isinstance(schema_representation, (list, tuple, set)):
            text = ", ".join(str(item) for item in schema_representation)
        else:
            text = str(schema_representation).strip()

        if not text:
            return 0

        char_estimate = max(1, int(len(text) / 4.0 + 0.5))
        word_estimate = int(len(text.split()) * 1.3)
        return max(char_estimate, word_estimate)
    except Exception as exc:
        logger.warning("Error estimating schema tokens: %s. Falling back to length heuristic.", exc)
        return max(1, int(len(str(schema_representation)) / 4.0))
