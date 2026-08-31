"""Unit tests for Layer 1 SemanticCache (dynamic TTL, similarity threshold, LRU eviction, scope isolation)."""

import time
import pytest
from src.models.schemas import QueryResult
from src.utils.query_classifier import QueryType, classify_query
from src.utils.semantic_cache import (
    SemanticCache,
    SIMILARITY_THRESHOLD,
    _cosine_similarity,
    get_semantic_cache,
)


@pytest.fixture(autouse=True)
def reset_cache():
    SemanticCache.reset()
    yield
    SemanticCache.reset()


def make_dummy_result(answer: str = "Test answer") -> QueryResult:
    return QueryResult(
        query="dummy question",
        answer=answer,
        chunks_retrieved=1,
        citations=[],
        thinking_steps=[],
    )


def test_singleton_instance():
    cache1 = get_semantic_cache()
    cache2 = get_semantic_cache()
    assert cache1 is cache2
    assert isinstance(cache1, SemanticCache)


def test_exact_match_hit():
    cache = get_semantic_cache()
    emb = [1.0, 0.0, 0.0, 0.0]
    result = make_dummy_result("There are 15 customers.")

    cache.store("How many customers?", emb, result, scope_key="tenant_1", query_type=QueryType.COUNT)

    hit = cache.lookup("How many customers?", emb, scope_key="tenant_1")
    assert hit is not None
    assert hit.answer == "There are 15 customers."


def test_paraphrase_similarity_hit():
    cache = get_semantic_cache()
    # v1 and v2 have cosine similarity ~0.999
    emb1 = [1.0, 0.05, 0.0, 0.0]
    emb2 = [1.0, 0.04, 0.0, 0.0]
    assert _cosine_similarity(emb1, emb2) >= SIMILARITY_THRESHOLD

    result = make_dummy_result("Total revenue is 50000.")
    cache.store("What is total revenue?", emb1, result, scope_key="tenant_1", query_type=QueryType.SUM)

    hit = cache.lookup("Give me total revenue", emb2, scope_key="tenant_1")
    assert hit is not None
    assert hit.answer == "Total revenue is 50000."


def test_sub_threshold_miss():
    cache = get_semantic_cache()
    emb1 = [1.0, 0.0, 0.0, 0.0]
    emb2 = [0.5, 0.5, 0.5, 0.5]
    assert _cosine_similarity(emb1, emb2) < SIMILARITY_THRESHOLD

    result = make_dummy_result("Policy doc content")
    cache.store("What is refund policy?", emb1, result, scope_key="tenant_1", query_type=QueryType.POLICY)

    miss = cache.lookup("Show me list of vendors", emb2, scope_key="tenant_1")
    assert miss is None


def test_scope_isolation():
    cache = get_semantic_cache()
    emb = [1.0, 0.0, 0.0, 0.0]
    result = make_dummy_result("Tenant 1 secret data")

    cache.store("How many orders?", emb, result, scope_key="tenant_A", query_type=QueryType.COUNT)

    # Lookup from different tenant scope must return None
    miss = cache.lookup("How many orders?", emb, scope_key="tenant_B")
    assert miss is None

    # Lookup from correct tenant scope must succeed
    hit = cache.lookup("How many orders?", emb, scope_key="tenant_A")
    assert hit is not None
    assert hit.answer == "Tenant 1 secret data"


def test_scope_key_required():
    cache = get_semantic_cache()
    emb = [1.0, 0.0]
    result = make_dummy_result()

    with pytest.raises(ValueError):
        cache.store("Q", emb, result, scope_key="", query_type=QueryType.OTHER)

    with pytest.raises(ValueError):
        cache.lookup("Q", emb, scope_key="")


def test_dynamic_ttl_eviction_count_query(monkeypatch):
    cache = get_semantic_cache()
    emb = [1.0, 0.0, 0.0]
    result = make_dummy_result("42 items")

    current_time = 1000.0
    monkeypatch.setattr(time, "time", lambda: current_time)

    cache.store("Count items", emb, result, scope_key="default", query_type=QueryType.COUNT)

    # 30 seconds later -> within 60s TTL -> hit
    current_time = 1030.0
    assert cache.lookup("Count items", emb, scope_key="default") is not None

    # 65 seconds later -> expired -> miss
    current_time = 1065.0
    assert cache.lookup("Count items", emb, scope_key="default") is None


def test_dynamic_ttl_policy_query_24h(monkeypatch):
    cache = get_semantic_cache()
    emb = [1.0, 0.0, 0.0]
    result = make_dummy_result("Standard policy details")

    current_time = 1000.0
    monkeypatch.setattr(time, "time", lambda: current_time)

    cache.store("Return policy", emb, result, scope_key="default", query_type=QueryType.POLICY)

    # 12 hours later -> within 24h TTL -> hit
    current_time = 1000.0 + (12 * 3600)
    assert cache.lookup("Return policy", emb, scope_key="default") is not None

    # 25 hours later -> expired -> miss
    current_time = 1000.0 + (25 * 3600)
    assert cache.lookup("Return policy", emb, scope_key="default") is None


def test_ast_gate_failed_not_cached():
    cache = get_semantic_cache()
    emb = [1.0, 0.0]
    result = make_dummy_result("Dangerous query output")

    # ast_gate_passed=False must prevent storage
    cache.store("DROP TABLE users", emb, result, scope_key="default", query_type=QueryType.OTHER, ast_gate_passed=False)

    assert cache.lookup("DROP TABLE users", emb, scope_key="default") is None


def test_lru_eviction_at_capacity():
    cache = SemanticCache(max_entries_per_scope=3)
    emb1 = [1.0, 0.0, 0.0]
    emb2 = [0.0, 1.0, 0.0]
    emb3 = [0.0, 0.0, 1.0]
    emb4 = [1.0, 1.0, 0.0]

    cache.store("Q1", emb1, make_dummy_result("A1"), scope_key="default", query_type=QueryType.OTHER)
    cache.store("Q2", emb2, make_dummy_result("A2"), scope_key="default", query_type=QueryType.OTHER)
    cache.store("Q3", emb3, make_dummy_result("A3"), scope_key="default", query_type=QueryType.OTHER)

    assert len(cache._scopes["default"]) == 3

    # Storing 4th entry evicts Q1 (oldest)
    cache.store("Q4", emb4, make_dummy_result("A4"), scope_key="default", query_type=QueryType.OTHER)
    assert len(cache._scopes["default"]) == 3

    # Q1 is evicted
    assert cache.lookup("Q1", emb1, scope_key="default") is None
    # Q2, Q3, Q4 are present
    assert cache.lookup("Q2", emb2, scope_key="default") is not None
    assert cache.lookup("Q3", emb3, scope_key="default") is not None
    assert cache.lookup("Q4", emb4, scope_key="default") is not None
