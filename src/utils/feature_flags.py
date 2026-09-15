"""Feature flag infrastructure for SQL pipeline optimization."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"

DEFAULT_FLAGS: dict[str, bool] = {
    "delta_repair_enabled": False,
    "token_budget_enabled": False,
    "schema_compaction_enabled": False,
    "sql_safety_enabled": False,
    "zero_row_handling_enabled": False,
    "fast_path_enabled": False,
    "provider_routing_v2_enabled": False,
    # V1 Measurement & Safety Flags
    "enable_branching_traces": True,
    "guard_sql_safety_enforce": True,
    "guard_sql_soft_delete_enforce": True,
    "guard_sql_temporal_shadow": True,
    "guard_sql_temporal_enforce": False,
    "guard_schema_sufficiency_shadow": True,
    "guard_schema_sufficiency_enforce": False,
    "guard_rag_citation_shadow": True,
    "guard_rag_citation_enforce": True,
    "guard_decomposition_shadow": True,
    "enable_fallback_on_guard_failure": True,
}


_FLAGS_CACHE: dict[str, bool] | None = None
_CACHE_MTIME: float = 0.0


def _load_flags_from_yaml() -> dict[str, bool]:
    """Load flags from feature_flags.yaml or features.yaml if present, cached by mtime."""
    global _FLAGS_CACHE, _CACHE_MTIME
    target_file = None
    for filename in ("feature_flags.yaml", "features.yaml"):
        file_path = CONFIG_DIR / filename
        if file_path.exists():
            target_file = file_path
            break

    if target_file is None:
        return {}

    try:
        mtime = target_file.stat().st_mtime
        if _FLAGS_CACHE is not None and mtime == _CACHE_MTIME:
            return _FLAGS_CACHE

        with open(target_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            if isinstance(data, dict):
                raw_flags = data.get("features", data)
                if isinstance(raw_flags, dict):
                    _FLAGS_CACHE = {k: bool(v) for k, v in raw_flags.items()}
                    _CACHE_MTIME = mtime
                    return _FLAGS_CACHE
    except Exception as e:
        logger.warning("Failed to load %s: %s — falling back to defaults", target_file, e)

    return _FLAGS_CACHE or {}


def is_feature_enabled(flag_name: str) -> bool:
    """Safely check if a feature flag is enabled.

    Defaults to False if the flag does not exist or if configuration cannot be read.
    """
    file_flags = _load_flags_from_yaml()
    if flag_name in file_flags:
        return file_flags[flag_name]
    return DEFAULT_FLAGS.get(flag_name, False)
