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
}


def _load_flags_from_yaml() -> dict[str, bool]:
    """Load flags from feature_flags.yaml or features.yaml if present."""
    for filename in ("feature_flags.yaml", "features.yaml"):
        file_path = CONFIG_DIR / filename
        if file_path.exists():
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                    if isinstance(data, dict):
                        raw_flags = data.get("features", data)
                        if isinstance(raw_flags, dict):
                            return {k: bool(v) for k, v in raw_flags.items()}
            except Exception as e:
                logger.warning("Failed to load %s: %s — falling back to defaults", file_path, e)
    return {}


def is_feature_enabled(flag_name: str) -> bool:
    """Safely check if a feature flag is enabled.

    Defaults to False if the flag does not exist or if configuration cannot be read.
    """
    file_flags = _load_flags_from_yaml()
    if flag_name in file_flags:
        return file_flags[flag_name]
    return DEFAULT_FLAGS.get(flag_name, False)
