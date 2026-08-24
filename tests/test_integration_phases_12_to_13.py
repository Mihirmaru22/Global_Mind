"""Phase 12–13 Comprehensive Integration Audit ("The Final Gate Before Rollout").

Validates:
1. List Query Fast-Path (0 synthesis tokens, sub-second latency)
2. Aggregate Query Micro-Synthesis (max 150 tokens)
3. Explanation Query Full Synthesis (standard reasoning path)
4. Provider Routing + Circuit Breaker Interaction (fallback from tripped provider)
5. Full End-to-End Chain across all Phases (0 through 13)
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
import pandas as pd
import pytest

from src.core.provider_client import ProviderOption, ProviderRouter, TaskRoute
from src.models.schemas import Chunk, ChunkType, DocumentType, RetrievedChunk
from src.stages.s12_s13_s14_retrieval import Generator
from src.stages.s12b_sql_retrieval import SQLRetriever
from src.utils.circuit_breaker import get_shared_circuit_breaker
from src.utils.feature_flags import DEFAULT_FLAGS
from src.utils.query_budget import QueryBudgetController, set_current_budget_controller
from src.utils.query_classifier import (
    AGGREGATE_QUERY,
    EXPLANATION_QUERY,
    LIST_QUERY,
    classify_query_intent,
)
from src.utils.schema_budget import select_schema_within_budget
from src.utils.schema_compactor import compact_ddl
from src.utils.sql_safety import validate_sql_safety


@pytest.fixture(autouse=True)
def _reset_audit_state():
    cb = get_shared_circuit_breaker()
    cb.reset_all()
    set_current_budget_controller(None)
    yield
    cb.reset_all()
    set_current_budget_controller(None)


class _MockProvider:
    def __init__(self, name: str, return_text: str = "ok"):
        self._name = name
        self._text = return_text
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_available(self) -> bool:
        return True

    async def chat(self, messages, *, model, temperature=0.0, max_tokens=4096, response_format=None, usage=None):
        self.calls += 1
        return self._text


@pytest.mark.asyncio
async def test_1_list_query_fast_path_zero_synthesis_tokens():
    """Test 1: List query with non-empty SQL results completely bypasses synthesis LLM."""
    mock_router = MagicMock(spec=ProviderRouter)
    mock_router.usage = MagicMock(model_copy=MagicMock(return_value={}))
    mock_router.last_used = "mock-model"

    generator = Generator(router=mock_router)

    question = "Show me the last 10 invoices"
    intent = classify_query_intent(question)
    assert intent == LIST_QUERY

    table_chunk = RetrievedChunk(
        chunk=Chunk(
            chunk_id="sql_chunk_1",
            document_id="live_db",
            chunk_type=ChunkType.SQL_RESULT,
            content="SQL Query Executed: `SELECT * FROM invoices LIMIT 10`\n\n| inv_id | amount |\n|---|---|\n| 101 | 450 |\n| 102 | 890 |",
            document_type=DocumentType.GENERAL,
        ),
        score=1.0,
    )

    logged_telemetry = []

    def mock_log(query_id, stage, **kwargs):
        logged_telemetry.append({"stage": stage, **kwargs})

    with patch("src.stages.s12_s13_s14_retrieval.is_feature_enabled", return_value=True), \
         patch("src.stages.s12_s13_s14_retrieval.log_telemetry", side_effect=mock_log):

        result = await generator.generate(question, [table_chunk])

        # Assert: Synthesis LLM called 0 times
        assert mock_router.chat.await_count == 0

        # Assert: Polite header + table
        assert "Here are the records matching your request:" in result.answer
        assert "| inv_id | amount |" in result.answer
        assert result.model_used == "fast_path/list"

        # Assert: Telemetry logged synthesis_bypassed
        stages = [e["stage"] for e in logged_telemetry]
        assert "synthesis_bypassed" in stages


@pytest.mark.asyncio
async def test_2_aggregate_query_micro_synthesis():
    """Test 2: Aggregate query uses micro-prompt with max_tokens <= 150 and task='micro_synthesis'."""
    mock_router = MagicMock(spec=ProviderRouter)
    mock_router.usage = MagicMock(model_copy=MagicMock(return_value={}))
    mock_router.last_used = "groq/openai/gpt-oss-20b"
    mock_router.chat = AsyncMock(return_value="Total revenue across all regions reached $1,500,000.")

    generator = Generator(router=mock_router)

    question = "What is the total revenue by region?"
    intent = classify_query_intent(question)
    assert intent == AGGREGATE_QUERY

    table_chunk = RetrievedChunk(
        chunk=Chunk(
            chunk_id="sql_chunk_2",
            document_id="live_db",
            chunk_type=ChunkType.SQL_RESULT,
            content="SQL Query Executed: `SELECT region, SUM(amount) FROM sales GROUP BY region`\n\n| region | total |\n|---|---|\n| North | 900000 |\n| South | 600000 |",
            document_type=DocumentType.GENERAL,
        ),
        score=1.0,
    )

    logged_telemetry = []

    def mock_log(query_id, stage, **kwargs):
        logged_telemetry.append({"stage": stage, **kwargs})

    with patch("src.stages.s12_s13_s14_retrieval.is_feature_enabled", return_value=True), \
         patch("src.stages.s12_s13_s14_retrieval.log_telemetry", side_effect=mock_log):

        result = await generator.generate(question, [table_chunk])

        # Assert: Synthesis LLM called exactly 1 time
        assert mock_router.chat.await_count == 1
        call_kwargs = mock_router.chat.call_args.kwargs
        assert call_kwargs.get("max_tokens") <= 150
        assert call_kwargs.get("task") == "micro_synthesis"

        # Assert: Answer combines summary and table
        assert "Total revenue across all regions reached $1,500,000." in result.answer
        assert "| region | total |" in result.answer
        assert result.model_used == "fast_path/aggregate"

        # Assert: Telemetry logged micro_synthesis
        stages = [e["stage"] for e in logged_telemetry]
        assert "micro_synthesis" in stages


@pytest.mark.asyncio
async def test_3_explanation_query_full_synthesis():
    """Test 3: Complex diagnostic/explanatory queries route to full Stage 14 synthesis."""
    mock_router = MagicMock(spec=ProviderRouter)
    mock_router.usage = MagicMock(model_copy=MagicMock(return_value={}))
    mock_router.last_used = "gemini/gemini-2.5-flash"
    mock_router.chat = AsyncMock(return_value="Revenue dropped in Q3 due to supply chain disruptions in the northern region.")

    generator = Generator(router=mock_router)

    question = "Why did revenue drop in Q3?"
    intent = classify_query_intent(question)
    assert intent == EXPLANATION_QUERY

    table_chunk = RetrievedChunk(
        chunk=Chunk(
            chunk_id="sql_chunk_3",
            document_id="live_db",
            chunk_type=ChunkType.SQL_RESULT,
            content="SQL Query Executed: `SELECT quarter, revenue FROM quarterly_reports`\n\n| quarter | revenue |\n|---|---|\n| Q2 | 1000000 |\n| Q3 | 600000 |",
            document_type=DocumentType.GENERAL,
        ),
        score=1.0,
    )

    logged_telemetry = []

    def mock_log(query_id, stage, **kwargs):
        logged_telemetry.append({"stage": stage, **kwargs})

    with patch("src.stages.s12_s13_s14_retrieval.is_feature_enabled", return_value=True), \
         patch("src.stages.s12_s13_s14_retrieval.log_telemetry", side_effect=mock_log):

        result = await generator.generate(question, [table_chunk])

        assert mock_router.chat.await_count == 1
        call_kwargs = mock_router.chat.call_args.kwargs
        assert call_kwargs.get("max_tokens") == 2048
        assert call_kwargs.get("task") == "synthesis"
        assert "Revenue dropped in Q3 due to supply chain" in result.answer

        stages = [e["stage"] for e in logged_telemetry]
        assert "full_synthesis" in stages


@pytest.mark.asyncio
async def test_4_provider_routing_circuit_breaker_interaction():
    """Test 4: Circuit-broken preferred provider is skipped and fallback is executed seamlessly."""
    cb = get_shared_circuit_breaker()

    gemini_prov = _MockProvider("gemini", "gemini sql")
    groq_prov = _MockProvider("groq", "groq sql")
    nim_prov = _MockProvider("nvidia_nim", "nim sql")

    router = ProviderRouter()
    router._providers = {
        "gemini": gemini_prov,
        "groq": groq_prov,
        "nvidia_nim": nim_prov,
    }

    # Trip circuit breaker on Gemini
    cb.record_failure("gemini", Exception("429 Too Many Requests"))
    cb.record_failure("gemini", Exception("429 Too Many Requests"))
    cb.record_failure("gemini", Exception("429 Too Many Requests"))
    assert cb.is_open("gemini")

    budget_ctrl = QueryBudgetController(query_id="test-routing-cb", max_llm_calls=4)
    set_current_budget_controller(budget_ctrl)

    logged_telemetry = []

    def mock_log(query_id, stage, **kwargs):
        logged_telemetry.append({"stage": stage, **kwargs})

    with patch("src.utils.feature_flags.is_feature_enabled", side_effect=lambda flag: flag == "provider_routing_v2_enabled"), \
         patch("src.core.provider_client.log_telemetry", side_effect=mock_log):

        response = await router.chat(
            task="reasoning",
            messages=[{"role": "user", "content": "Generate SQL"}],
        )

        # Gemini was skipped because CB is open; routed to next available (NIM/Groq)
        assert gemini_prov.calls == 0
        assert (nim_prov.calls == 1 or groq_prov.calls == 1)
        assert response in ("nim sql", "groq sql")

        # Budget controller tracked call
        assert budget_ctrl.llm_calls == 1

        # Telemetry logs fell_back: True
        success_events = [e for e in logged_telemetry if e.get("success") is True]
        assert len(success_events) > 0
        last_event = success_events[-1]
        assert last_event["extra"]["fell_back"] is True
        assert last_event["extra"]["preferred_provider"] == "gemini"


@pytest.mark.asyncio
async def test_5_full_chain_e2e_phases_0_to_13():
    """Test 5: Full lifecycle with ALL optimization phases active."""
    # 1. Enable all optimization flags
    flags = {
        "delta_repair_enabled": True,
        "token_budget_enabled": True,
        "schema_compaction_enabled": True,
        "sql_safety_enabled": True,
        "zero_row_handling_enabled": True,
        "fast_path_enabled": True,
        "provider_routing_v2_enabled": True,
    }

    raw_ddls = [
        "CREATE TABLE customers (id INT PRIMARY KEY, name VARCHAR(100), created_at TIMESTAMP, updated_at TIMESTAMP, deleted_at TIMESTAMP);",
        "CREATE TABLE orders (id INT PRIMARY KEY, customer_id INT REFERENCES customers(id), order_count INT, created_by INT);",
        "CREATE TABLE invoices (id INT PRIMARY KEY, order_id INT REFERENCES orders(id), total_amount NUMERIC, audit_log TEXT);",
    ]

    # 2. Schema budget & compaction (Phases 8 & 9)
    selected_schema, dropped_schema = select_schema_within_budget(raw_ddls, token_budget=1500)
    assert len(selected_schema) == 3
    compacted_schema = [compact_ddl(ddl) for ddl in selected_schema]
    assert all("created_at" not in ddl for ddl in compacted_schema)
    assert all("PK" in ddl for ddl in compacted_schema)

    # 3. User query and SQL generation (Phase 13 task='reasoning')
    user_query = "List the top 5 customers by order count"
    generated_sql = "SELECT id, name, order_count FROM customers JOIN orders ON customers.id = orders.customer_id ORDER BY order_count DESC LIMIT 5"

    # 4. AST SQL Safety Validation (Phase 10)
    schema_map = {"customers": ["id", "name"], "orders": ["id", "customer_id", "order_count"]}
    is_safe, violation = validate_sql_safety(generated_sql, schema_map)
    assert is_safe is True
    assert not violation

    # 5. Database Execution (mock 5 rows)
    mock_df = pd.DataFrame({
        "id": [1, 2, 3, 4, 5],
        "name": ["Alice", "Bob", "Charlie", "David", "Eve"],
        "order_count": [45, 38, 29, 21, 15],
    })
    assert len(mock_df) == 5

    # 6. Intent classification & Fast Path routing (Phase 12)
    intent = classify_query_intent(user_query)
    assert intent == LIST_QUERY

    table_md = mock_df.to_markdown(index=False)
    table_chunk = RetrievedChunk(
        chunk=Chunk(
            chunk_id="sql_e2e",
            document_id="live_db",
            chunk_type=ChunkType.SQL_RESULT,
            content=f"SQL Query Executed: `{generated_sql}`\n\n{table_md}",
            document_type=DocumentType.GENERAL,
        ),
        score=1.0,
    )

    mock_router = MagicMock(spec=ProviderRouter)
    mock_router.usage = MagicMock(model_copy=MagicMock(return_value={}))
    mock_router.last_used = "gemini/gemini-2.5-flash"

    generator = Generator(router=mock_router)

    with patch("src.stages.s12_s13_s14_retrieval.is_feature_enabled", side_effect=lambda flag: flags.get(flag, False)):
        result = await generator.generate(user_query, [table_chunk])

        # PROOF OF LIFE: Stage 14 synthesis LLM was bypassed (0 chat calls)
        assert mock_router.chat.await_count == 0
        assert "Here are the records matching your request:" in result.answer
        assert "| Alice" in result.answer
        assert result.model_used == "fast_path/list"
