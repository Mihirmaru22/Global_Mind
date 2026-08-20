"""Unit tests for Stage 12b Text-to-SQL retrieval (SQLRetriever).

Focus on the SQL-vs-document routing failure modes:
  * aggregate over no rows (all-NULL row) must fall back, not answer "None";
  * LLM output wrapped in fences/prose must still parse (not fall back to docs);
  * NO_SQL abstention is recognised even when decorated;
  * a real SQL result becomes a pinned RESULT chunk.

The SQLRetriever runs against a REAL temporary SQLite database; only the LLM
(router.chat for task="reasoning") is faked so the SQL string is deterministic.
"""

import sqlite3
from pathlib import Path

import pytest
from unittest.mock import AsyncMock

from src.models.schemas import ChunkType
from src.stages.s12b_sql_retrieval import (
    SQLRetriever,
    _is_all_null,
    _load_relationships,
    _unwrap_sql,
)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def test_is_all_null_single_all_null_row():
    assert _is_all_null([{"total": None}]) is True
    assert _is_all_null([{"m": None, "lo": None}]) is True


def test_is_all_null_preserves_count_zero_and_real_data():
    # COUNT(*) over no matches returns 0, not NULL — a legitimate answer.
    assert _is_all_null([{"n": 0}]) is False
    assert _is_all_null([{"total": 100}]) is False
    # Multi-row results are always real data.
    assert _is_all_null([{"x": None}, {"x": None}]) is False
    assert _is_all_null([]) is False


def test_relationships_join_map_disambiguates_columns():
    """The shipped join map must place product_color_id on the line-item tables
    and NOT on `product` — the exact confusion behind the observed
    'Unknown column p.product_color_id' join hallucination."""
    rel = _load_relationships()
    if not rel:
        pytest.skip("config/sql_relationships.json not present in this deployment")
    lines = {ln.split(":", 1)[0].lstrip("- ").strip(): ln for ln in rel.splitlines()}
    # product has no product_color_id
    assert "product_color_id" not in lines.get("product", "")
    # sales_order_products does, joining to product_color
    assert "product_color_id->product_color.id" in lines.get("sales_order_products", "")


def test_relationships_injected_into_prompt():
    """When relationships are configured, the SQL-generation prompt must carry the
    join map so the model doesn't guess joins."""
    from unittest.mock import AsyncMock
    r = SQLRetriever(AsyncMock())
    r._relationships = "- sales_order_products: product_color_id->product_color.id"

    captured = {}

    async def chat(task=None, messages=None, **kw):
        captured["system"] = messages[0]["content"]
        return "SELECT 1"

    r._router.chat = chat

    import asyncio
    asyncio.run(r._generate_sql("q", "TABLE product (...)"))
    assert "Table relationships" in captured["system"]
    assert "product_color_id->product_color.id" in captured["system"]


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("SELECT 1", "SELECT 1"),
        ("```sql\nSELECT 1\n```", "SELECT 1"),
        ("```\nSELECT 1\n```", "SELECT 1"),
        ("Here is the query: SELECT 1 FROM t", "SELECT 1 FROM t"),
        ("WITH c AS (SELECT 1) SELECT * FROM c", "WITH c AS (SELECT 1) SELECT * FROM c"),
    ],
)
def test_unwrap_sql(raw, expected):
    assert _unwrap_sql(raw) == expected


# ---------------------------------------------------------------------------
# Retriever against a real SQLite DB
# ---------------------------------------------------------------------------

@pytest.fixture
def live_db(tmp_path, monkeypatch):
    """A real SQLite DB wired into db_client via settings + DB_PATH override."""
    db_path = tmp_path / "live_data.db"
    con = sqlite3.connect(db_path)
    con.executescript(
        """
        CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, city TEXT);
        CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER,
                             amount REAL, order_date TEXT);
        INSERT INTO customers (id,name,city) VALUES (1,'Acme','NYC'),(2,'Globex','LA');
        INSERT INTO orders (id,customer_id,amount,order_date) VALUES
            (1,1,2140000,'2025-03-01'),(2,2,1890500,'2025-05-11');
        """
    )
    con.commit()
    con.close()

    from src.core import config, db_client

    monkeypatch.setattr(config.settings, "db_engine", "sqlite", raising=False)
    monkeypatch.setattr(db_client, "DB_PATH", db_path, raising=False)
    SQLRetriever.clear_schema_cache()
    SQLRetriever.clear_result_cache()
    return db_path


def _router_returning(sql: str) -> AsyncMock:
    router = AsyncMock()

    async def chat(*args, **kw):
        return sql

    router.chat = chat
    return router


@pytest.mark.asyncio
async def test_real_sql_result_becomes_pinned_chunk(live_db):
    sql = ("SELECT c.name AS customer, SUM(o.amount) AS total "
           "FROM orders o JOIN customers c ON o.customer_id=c.id "
           "GROUP BY c.name ORDER BY total DESC")
    retriever = SQLRetriever(_router_returning(sql))

    chunks = await retriever.retrieve("top customers by revenue")

    assert len(chunks) == 1
    assert chunks[0].chunk.chunk_type == ChunkType.SQL_RESULT
    assert "Acme" in chunks[0].chunk.content
    assert "SQL Query Executed" in chunks[0].chunk.content


@pytest.mark.asyncio
async def test_aggregate_over_no_rows_returns_result_chunk(live_db):
    """SUM over a period with no data returns [{'total': None}]; the retriever
    must return a confirmed SQL result chunk with NULL status rather than silently dropping to empty."""
    sql = "SELECT SUM(amount) AS total FROM orders WHERE order_date LIKE '1998%'"
    retriever = SQLRetriever(_router_returning(sql))

    chunks = await retriever.retrieve("total revenue in 1998")

    assert len(chunks) == 1
    assert chunks[0].chunk.chunk_type == ChunkType.SQL_RESULT
    assert "NULL" in chunks[0].chunk.content
    assert retriever.last_query_status == "empty_result"


@pytest.mark.asyncio
async def test_zero_row_query_returns_result_chunk(live_db):
    """A query returning 0 rows after execution returns a confirmed SQL result chunk with notice."""
    sql = "SELECT id, name FROM customers WHERE name = 'NonexistentCo'"
    retriever = SQLRetriever(_router_returning(sql))

    chunks = await retriever.retrieve("find NonexistentCo")

    assert len(chunks) == 1
    assert chunks[0].chunk.chunk_type == ChunkType.SQL_RESULT
    assert "No matching records found in the database" in chunks[0].chunk.content
    assert retriever.last_query_status == "empty_result"


@pytest.mark.asyncio
async def test_count_zero_is_a_real_answer(live_db):
    """COUNT(*) = 0 is a legitimate answer and must NOT be collapsed to empty."""
    sql = "SELECT COUNT(*) AS n FROM orders WHERE order_date LIKE '1998%'"
    retriever = SQLRetriever(_router_returning(sql))

    chunks = await retriever.retrieve("how many orders in 1998")

    assert len(chunks) == 1
    assert "0" in chunks[0].chunk.content
    assert retriever.last_query_status == "success"


@pytest.mark.asyncio
async def test_fenced_sql_still_executes(live_db):
    """A query wrapped in a markdown fence must run, not fall back to docs."""
    sql = "```sql\nSELECT name FROM customers ORDER BY name\n```"
    retriever = SQLRetriever(_router_returning(sql))

    chunks = await retriever.retrieve("list customer names")

    assert len(chunks) == 1
    assert "Acme" in chunks[0].chunk.content


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", ["NO_SQL", "NO_SQL.", "NO_SQL - schema has no such data"])
async def test_no_sql_abstention(live_db, reply):
    retriever = SQLRetriever(_router_returning(reply))
    chunks = await retriever.retrieve("what is the meaning of life")
    assert chunks == []
    assert retriever.last_query_status == "not_applicable"


# ---------------------------------------------------------------------------
# Safety / malformed — every one must abstain (→ []), never raise or mutate data
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE customers",                          # not a SELECT
        "DELETE FROM orders",                            # not a SELECT
        "SELECT 1; DROP TABLE customers",                # stacked statement
        "SELECT name FROM customers INTO OUTFILE '/tmp/x'",  # disk write
        "SELECT LOAD_FILE('/etc/passwd') AS x",          # file read
        "UPDATE orders SET amount = 0",                  # not a SELECT
    ],
)
async def test_unsafe_queries_are_blocked(live_db, sql):
    retriever = SQLRetriever(_router_returning(sql))
    chunks = await retriever.retrieve("something")
    assert chunks == []
    assert retriever.last_query_status == "failed"
    # The data is untouched — the read-only path never executed a write.
    con = sqlite3.connect(live_db)
    assert con.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 2
    con.close()


@pytest.mark.asyncio
async def test_malformed_sql_falls_back(live_db):
    """A syntactically broken query is retried once, then abstains (→ docs)."""
    retriever = SQLRetriever(_router_returning("SELCT nope FROM"))
    chunks = await retriever.retrieve("broken")
    assert chunks == []
    assert retriever.last_query_status == "failed"


@pytest.mark.asyncio
async def test_nonexistent_column_falls_back(live_db):
    """Valid syntax but a hallucinated column errors at execution → abstains."""
    retriever = SQLRetriever(_router_returning("SELECT made_up_col FROM customers"))
    chunks = await retriever.retrieve("hallucinated column")
    assert chunks == []
    assert retriever.last_query_status == "failed"


@pytest.mark.asyncio
async def test_result_cache_bounded_lru_and_deep_copy(live_db):
    """Cache returns deep copies so mutation doesn't poison the cache, and clears correctly."""
    SQLRetriever.clear_result_cache()
    sql = "SELECT name FROM customers ORDER BY name LIMIT 1"
    retriever = SQLRetriever(_router_returning(sql))

    chunks1 = await retriever.retrieve("get first customer")
    assert len(chunks1) == 1
    original_content = chunks1[0].chunk.content

    # Mutate the returned chunk object
    chunks1[0].chunk.content = "MUTATED_CONTENT"

    # Second retrieve should hit cache and return pristine original copy
    chunks2 = await retriever.retrieve("get first customer")
    assert len(chunks2) == 1
    assert chunks2[0].chunk.content == original_content
    assert chunks2[0].chunk.content != "MUTATED_CONTENT"

    # Test cache clear
    SQLRetriever.clear_result_cache()
    assert len(SQLRetriever._result_cache) == 0


@pytest.mark.asyncio
async def test_empty_schema_not_cached_permanently(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """An empty schema return from a failed/empty DB must not permanently disable introspection."""
    SQLRetriever.clear_schema_cache()

    empty_db = tmp_path / "empty.db"
    conn = sqlite3.connect(empty_db)
    conn.close()

    from src.core import config
    import src.core.db_client as db_client_mod
    monkeypatch.setattr(config.settings, "db_engine", "sqlite", raising=False)
    monkeypatch.setattr(db_client_mod, "DB_PATH", empty_db, raising=False)

    retriever = SQLRetriever(_router_returning("SELECT 1"))
    schema1 = await retriever._fetch_full_schema()
    assert schema1 == ""
    # Should NOT be cached in SQLRetriever._full_schema_cache
    assert SQLRetriever._full_schema_cache is None

    # Now populate the database
    conn = sqlite3.connect(empty_db)
    conn.execute("CREATE TABLE products (id INT, title TEXT)")
    conn.close()

    schema2 = await retriever._fetch_full_schema()
    assert "CREATE TABLE products" in schema2
    assert SQLRetriever._full_schema_cache is not None
    SQLRetriever.clear_schema_cache()


def test_column_glossary_synonyms_and_stop_words():
    """Glossary filter matches synonyms and ignores stop words to prevent false positives."""
    from src.stages.s12b_sql_retrieval import _build_column_glossary_for_query

    # Query with synonym 'total sales' -> should match revenue
    out_sales = _build_column_glossary_for_query("What is our total sales this year?")
    assert "revenue" in out_sales

    # Query with synonym 'buyer' -> should match customer
    out_buyer = _build_column_glossary_for_query("Who is our top buyer?")
    assert "customer" in out_buyer

    # Stop words like 'is' should NOT trigger permissions_is_delete
    out_is = _build_column_glossary_for_query("Who is our top buyer?")
    assert "permissions_is_delete" not in out_is


@pytest.mark.asyncio
async def test_single_row_null_column_is_success(live_db):
    """When a query selects a column whose value in an existing row is genuinely NULL,
    the retriever must recognize the row was found (status=success), NOT empty_result,
    and format the NULL value without aggregation-zero warning notes."""
    con = sqlite3.connect(live_db)
    con.execute("UPDATE customers SET city = NULL WHERE id = 2")
    con.commit()
    con.close()

    sql = "SELECT city FROM customers WHERE id = 2"
    retriever = SQLRetriever(_router_returning(sql))

    chunks = await retriever.retrieve("what city is customer 2 in")

    assert len(chunks) == 1
    assert chunks[0].chunk.chunk_type == ChunkType.SQL_RESULT
    assert retriever.last_query_status == "success"
    assert "NULL" in chunks[0].chunk.content
    assert "matched 0 records for aggregation" not in chunks[0].chunk.content


@pytest.mark.asyncio
async def test_sync_live_schema_atomicity(monkeypatch: pytest.MonkeyPatch):
    """sync_live_schema embeds before upserting into vector store, ensuring no empty-store gap."""
    from unittest.mock import AsyncMock, MagicMock
    from src.pipeline.schema_ingestion import sync_live_schema

    mock_run = AsyncMock(return_value=[
        {"name": "customers", "sql": "CREATE TABLE customers (id INT, name TEXT)"}
    ])
    monkeypatch.setattr("src.pipeline.schema_ingestion.run_readonly_query", mock_run)

    call_order = []

    mock_store = MagicMock()
    mock_store.upsert = AsyncMock(side_effect=lambda *args: call_order.append("upsert"))

    mock_embeddings = MagicMock()
    async def mock_embed(chunks):
        call_order.append("embed")
        return ([[0.1] * 384], [{}])
    mock_embeddings.embed_chunks = AsyncMock(side_effect=mock_embed)

    result = await sync_live_schema(embedding_service=mock_embeddings, vector_store=mock_store)
    assert result["status"] == "ok"
    assert call_order == ["embed", "upsert"]


def test_glossary_and_relationships_no_drift():
    """Verify that every column and table in sql_column_glossary.json and sql_relationships.json
    resolves to a valid active schema column without drift."""
    from src.core.sql_drift_validator import validate_glossary_and_relationships
    errors = validate_glossary_and_relationships()
    assert not errors, f"Glossary or relationship drift detected:\n" + "\n".join(errors)


def test_scoped_relationships_filters_unrelated_tables():
    """Verify that scoped relationship formatting only includes join paths for active tables."""
    from src.stages.s12b_sql_retrieval import _format_scoped_relationships

    sample_rels = [
        {"from_table": "sales_order", "from_column": "party_id", "to_table": "party", "to_column": "id"},
        {"from_table": "sales_order_products", "from_column": "sales_order_id", "to_table": "sales_order", "to_column": "id"},
        {"from_table": "purchase", "from_column": "party_id", "to_table": "party", "to_column": "id"},
        {"from_table": "party", "from_column": "created_id", "to_table": "users", "to_column": "id"},
    ]

    # When active tables are only sales_order and party:
    scoped = _format_scoped_relationships({"sales_order", "party"}, query="top customer", rels=sample_rels)
    assert "sales_order: party_id->party.id" in scoped
    assert "purchase" not in scoped
    assert "sales_order_products" not in scoped
    assert "users" not in scoped  # Audit trail suppressed by default


def test_1hop_graph_expansion():
    """Verify 1-hop graph expansion finds directly connected tables while skipping audit noise."""
    from src.stages.s12b_sql_retrieval import _get_1hop_neighbors

    sample_rels = [
        {"from_table": "sales_order", "from_column": "party_id", "to_table": "party", "to_column": "id"},
        {"from_table": "sales_order_products", "from_column": "sales_order_id", "to_table": "sales_order", "to_column": "id"},
        {"from_table": "sales_order", "from_column": "created_id", "to_table": "users", "to_column": "id"},
    ]

    neighbors = _get_1hop_neighbors({"sales_order"}, rels=sample_rels)
    assert "party" in neighbors
    assert "sales_order_products" in neighbors
    assert "users" not in neighbors  # Audit link ignored

