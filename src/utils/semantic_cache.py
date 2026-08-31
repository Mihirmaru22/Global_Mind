# KNOWN LIMITATION: cache does not survive restarts. Redis layer is v2.
"""Layer 1 — Semantic Cache.

Serves repetitive and near-paraphrase queries with sub-second latency (< 0.8s)
by evaluating vector similarity against cached results with dynamic TTLs.
"""

from __future__ import annotations

import collections
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any

from src.models.schemas import QueryResult
from src.utils.query_classifier import QueryType, TTL_BY_QUERY_TYPE

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 0.95
MAX_ENTRIES_PER_SCOPE = 1000


def _cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """Compute cosine similarity between two float vectors."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for a, b in zip(v1, v2):
        dot += a * b
        norm_a += a * a
        norm_b += b * b
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


@dataclass
class CachedEntry:
    question: str
    embedding: list[float]
    result: QueryResult
    query_type: QueryType
    created_at: float = field(default_factory=time.time)
    hit_count: int = 0


class SemanticCache:
    """Process-scoped in-memory Semantic Cache with dynamic TTL and LRU eviction."""

    _instance: SemanticCache | None = None

    def __init__(self, max_entries_per_scope: int = MAX_ENTRIES_PER_SCOPE) -> None:
        self._max_entries = max_entries_per_scope
        # Mapping: scope_key -> collections.OrderedDict[str, CachedEntry]
        self._scopes: dict[str, collections.OrderedDict[str, CachedEntry]] = {}

    @classmethod
    def get_instance(cls) -> SemanticCache:
        """Singleton accessor for process-scoped SemanticCache."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton instance (primarily for tests)."""
        cls._instance = None

    def _get_scope_dict(self, scope_key: str) -> collections.OrderedDict[str, CachedEntry]:
        if not scope_key or not isinstance(scope_key, str) or not scope_key.strip():
            raise ValueError("scope_key is required and cannot be empty.")
        if scope_key not in self._scopes:
            self._scopes[scope_key] = collections.OrderedDict()
        return self._scopes[scope_key]

    def lookup(
        self,
        question: str,
        embedding: list[float],
        scope_key: str,
    ) -> QueryResult | None:
        """Lookup a cached QueryResult using semantic cosine similarity >= 0.95 and TTL check.

        Args:
            question: Original natural-language question.
            embedding: Dense vector representation of the question.
            scope_key: Tenant / ERP instance / RBAC role identifier.

        Returns:
            Cached QueryResult if found and within TTL, else None.
        """
        if not scope_key or not isinstance(scope_key, str) or not scope_key.strip():
            raise ValueError("scope_key is required and cannot be empty.")

        if not embedding or not question:
            return None

        scope_dict = self._get_scope_dict(scope_key)
        now = time.time()
        best_entry_key: str | None = None
        best_entry: CachedEntry | None = None
        best_sim = -1.0

        # Scan cached entries for this scope
        for entry_key, entry in list(scope_dict.items()):
            # Check dynamic TTL
            ttl = TTL_BY_QUERY_TYPE.get(entry.query_type, 3600)
            if (now - entry.created_at) > ttl:
                # Expired -> Evict
                scope_dict.pop(entry_key, None)
                continue

            sim = _cosine_similarity(embedding, entry.embedding)
            if sim >= SIMILARITY_THRESHOLD and sim > best_sim:
                best_sim = sim
                best_entry_key = entry_key
                best_entry = entry

        if best_entry and best_entry_key:
            # Move to end (MRU in LRU cache)
            scope_dict.move_to_end(best_entry_key)
            best_entry.hit_count += 1
            logger.info(
                "SemanticCache HIT (sim=%.4f, scope=%s, type=%s): '%s' -> matched '%s'",
                best_sim,
                scope_key,
                best_entry.query_type.value,
                question[:60],
                best_entry.question[:60],
            )
            # Return deep copy of QueryResult with zeroed latency metadata
            cached_res = best_entry.result.model_copy(deep=True)
            return cached_res

        logger.debug("SemanticCache MISS (scope=%s): '%s'", scope_key, question[:60])
        return None

    def store(
        self,
        question: str,
        embedding: list[float],
        result: QueryResult,
        scope_key: str,
        query_type: QueryType,
        ast_gate_passed: bool = True,
    ) -> None:
        """Store a QueryResult into SemanticCache with dynamic TTL.

        Args:
            question: Original natural-language question.
            embedding: Dense vector representation of the question.
            result: Result to store.
            scope_key: Tenant / ERP instance / RBAC role identifier.
            query_type: QueryType enum for TTL rules.
            ast_gate_passed: Whether the query successfully passed AST validation.
        """
        if not scope_key or not isinstance(scope_key, str) or not scope_key.strip():
            raise ValueError("scope_key is required and cannot be empty.")

        # Never cache if AST gate failed or if result is missing/error
        if not ast_gate_passed or result is None or not embedding:
            return

        scope_dict = self._get_scope_dict(scope_key)

        # LRU Eviction: drop oldest if at capacity
        while len(scope_dict) >= self._max_entries:
            scope_dict.popitem(last=False)

        # Strip transient identifiers (request IDs, timestamps, session tokens)
        clean_result = result.model_copy(deep=True)

        # Construct unique key based on embedding and question
        rounded_emb_hash = hash(tuple(round(x, 4) for x in embedding[:16]))
        entry_key = f"{scope_key}::{rounded_emb_hash}::{hash(question)}"

        entry = CachedEntry(
            question=question,
            embedding=embedding,
            result=clean_result,
            query_type=query_type,
            created_at=time.time(),
            hit_count=0,
        )

        scope_dict[entry_key] = entry
        logger.info(
            "SemanticCache STORE (scope=%s, type=%s, ttl=%ds): '%s'",
            scope_key,
            query_type.value,
            TTL_BY_QUERY_TYPE.get(query_type, 3600),
            question[:60],
        )


def get_semantic_cache() -> SemanticCache:
    """Get the process singleton SemanticCache instance."""
    return SemanticCache.get_instance()
