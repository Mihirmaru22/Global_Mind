"""Dynamic Schema Token Budget selector.

Selects candidate schema tables/chunks sequentially in relevance priority order
until the strict token budget is exhausted.
"""

from __future__ import annotations

import logging
from typing import Any

from src.utils.schema_token_estimator import estimate_schema_tokens

logger = logging.getLogger(__name__)

DEFAULT_SCHEMA_TOKEN_BUDGET = 1500


def select_schema_within_budget(
    candidates: list[dict[str, Any] | str | Any],
    token_budget: int = DEFAULT_SCHEMA_TOKEN_BUDGET,
    id_key: str = "table_name",
) -> tuple[list[Any], list[Any]]:
    """Iterate through candidate tables/chunks and select them until token_budget is reached.

    Args:
        candidates: List of schema candidate chunks, DDL strings, or metadata dicts.
        token_budget: Maximum allowed token ceiling for selected schema (default: 1500).
        id_key: Key name used to extract identifier from dictionary candidates.

    Returns:
        tuple[list[Any], list[Any]]:
            - selected_candidates: List of candidates fitting within budget.
            - dropped_candidates: List of candidates excluded due to budget constraints.
    """
    if not candidates:
        return [], []

    selected: list[Any] = []
    dropped: list[Any] = []
    current_tokens = 0

    for idx, cand in enumerate(candidates):
        try:
            cost = estimate_schema_tokens(cand)
        except Exception as err:
            logger.warning("Failed to estimate schema tokens for candidate %r: %s", cand, err)
            cost = 100

        cand_id = cand.get(id_key) if isinstance(cand, dict) else f"item_{idx}"

        # Rule: Always include the very first candidate even if it alone exceeds budget
        if idx == 0 and cost > token_budget:
            logger.warning(
                "First candidate '%s' cost (%d tokens) exceeds total budget (%d tokens). Including to avoid empty schema.",
                cand_id, cost, token_budget,
            )
            selected.append(cand)
            current_tokens += cost
            continue

        if current_tokens + cost <= token_budget:
            selected.append(cand)
            current_tokens += cost
        else:
            logger.debug(
                "Schema token budget reached (%d + %d > %d). Dropping candidate '%s'.",
                current_tokens, cost, token_budget, cand_id,
            )
            dropped.append(cand)

    return selected, dropped
