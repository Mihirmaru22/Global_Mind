"""Defensive JSONL telemetry parser grouping events by query_id."""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Fallback regex to extract JSON object from a line containing log headers/prefixes
_JSON_OBJECT_RE = re.compile(r"\{.*\}")


def parse_telemetry_file(file_path: str | Path) -> dict[str, list[dict[str, Any]]]:
    """Parse a JSONL telemetry file and group events by query_id.

    Gracefully handles missing files, malformed JSON lines, and embedded JSON in log prefixes.
    """
    path = Path(file_path)
    if not path.exists():
        logger.warning("Telemetry file not found at %s", path)
        return {}

    grouped_events: dict[str, list[dict[str, Any]]] = defaultdict(list)
    line_number = 0
    parsed_count = 0
    skipped_count = 0

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line_number += 1
            line = line.strip()
            if not line:
                continue

            event_dict: dict[str, Any] | None = None

            # Attempt 1: Direct JSON parse
            try:
                event_dict = json.loads(line)
            except json.JSONDecodeError:
                # Attempt 2: Extract JSON substring if prefixed by logger format
                match = _JSON_OBJECT_RE.search(line)
                if match:
                    try:
                        event_dict = json.loads(match.group(0))
                    except json.JSONDecodeError:
                        event_dict = None

            if not isinstance(event_dict, dict):
                skipped_count += 1
                continue

            # Defensive type normalization
            query_id = str(event_dict.get("query_id") or "unknown_query").strip()
            event_dict["query_id"] = query_id
            event_dict["stage"] = str(event_dict.get("stage") or "unknown")
            event_dict["input_tokens"] = int(event_dict.get("input_tokens") or 0)
            event_dict["output_tokens"] = int(event_dict.get("output_tokens") or 0)
            try:
                event_dict["latency_ms"] = float(event_dict.get("latency_ms") or 0.0)
            except (ValueError, TypeError):
                event_dict["latency_ms"] = 0.0

            event_dict["success"] = bool(event_dict.get("success", True))
            event_dict["failure_type"] = event_dict.get("failure_type")

            grouped_events[query_id].append(event_dict)
            parsed_count += 1

    logger.debug(
        "Parsed %d events across %d queries from %s (skipped %d lines)",
        parsed_count, len(grouped_events), path, skipped_count
    )
    return dict(grouped_events)
