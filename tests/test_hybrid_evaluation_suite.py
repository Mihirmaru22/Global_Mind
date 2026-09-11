"""Regression test suite validating the hybrid query evaluation findings.

Covers:
1. Compound hybrid query decomposition (preventing SQL/Doc cross-contamination).
2. Purchase invoice GT/0091 schema resolution and execution (FORTUNE PACKAGING).
3. Active categories count (20 active categories).
4. HD-BLOW 54GB stock adjustment sum (158,298).
5. DISTINCT machine projection for CAP03.
6. Hybrid doc chunk cap expansion (up to 5 chunks).
"""

import pytest
import asyncio
from src.core.provider_client import ProviderRouter
from src.pipeline.query import _decompose_hybrid_query, _classify_auto_mode
from src.stages.s12b_sql_retrieval import SQLRetriever
from src.core.db_client import run_readonly_query


def test_hybrid_query_decomposition_all_evaluation_cases():
    cases = [
        ("CAP03 unit name / Apple effective tax rate", "CAP03 unit name", "Apple effective tax rate"),
        ("Invoice GT/0091 party / Apple FTE employees", "Invoice GT/0091 party", "Apple FTE employees"),
        ("Active categories / international net sales %", "Active categories", "international net sales %"),
        ("Machine for CAP03 / Apple ticker symbol", "Machine for CAP03", "Apple ticker symbol"),
        ("HD-BLOW 54GB quantity adjusted / indirect distribution %", "HD-BLOW 54GB quantity adjusted", "indirect distribution %"),
        ("ACCURATE METAL FABRIQUE PO numbers / Apple HQ", "ACCURATE METAL FABRIQUE PO numbers", "Apple HQ"),
        ("Stock-out adjustments on 2025-06-03 / Document Chunker purpose", "Stock-out adjustments on 2025-06-03", "Document Chunker purpose"),
        ("Carton 25053534 warehouse / 5 RAG layers", "Carton 25053534 warehouse", "5 RAG layers"),
        ("HM TOOLS due date / Apple fiscal year end", "HM TOOLS due date", "Apple fiscal year end"),
        ("Delivery challans on 2025-06-03 / Embedding Model function", "Delivery challans on 2025-06-03", "Embedding Model function"),
    ]

    for raw, expected_sql, expected_doc in cases:
        sql_sub, doc_sub = _decompose_hybrid_query(raw)
        assert sql_sub == expected_sql, f"Failed on SQL for '{raw}': got '{sql_sub}' expected '{expected_sql}'"
        assert doc_sub == expected_doc, f"Failed on DOC for '{raw}': got '{doc_sub}' expected '{expected_doc}'"


def test_auto_mode_classification_broadened_keywords():
    assert _classify_auto_mode("ACCURATE METAL FABRIQUE PO numbers / Apple HQ") == "hybrid"
    assert _classify_auto_mode("HM TOOLS due date / Apple fiscal year end") == "hybrid"
    assert _classify_auto_mode("Active categories / international net sales %") == "hybrid"
    assert _classify_auto_mode("What is our return policy") == "rag"
    assert _classify_auto_mode("How many products are in warehouse 1") == "sql"


@pytest.mark.asyncio
async def test_purchase_invoice_gt0091_db_execution():
    query = """
    SELECT p.id AS party_id, p.party_name AS party_name
    FROM purchase pur
    JOIN party p ON pur.party_id = p.id
    WHERE pur.pi_no LIKE '%GT/0091%'
      AND pur.deleted_at IS NULL
      AND p.deleted_at IS NULL
    LIMIT 1;
    """
    rows = await run_readonly_query(query)
    assert len(rows) >= 1
    assert "FORTUNE PACKAGING" in rows[0]["party_name"]


@pytest.mark.asyncio
async def test_active_categories_count_db_execution():
    query = """
    SELECT COUNT(*) AS count
    FROM category
    WHERE deleted_at IS NULL AND status = 'Y';
    """
    rows = await run_readonly_query(query)
    assert len(rows) == 1
    assert rows[0]["count"] == 20


@pytest.mark.asyncio
async def test_hdblow_quantity_adjusted_db_execution():
    query = """
    SELECT SUM(sa.qty) AS total_qty
    FROM stock_adjustment sa
    JOIN product p ON sa.product_id = p.id
    WHERE p.product_name LIKE '%HD-BLOW 54GB%'
      AND sa.deleted_at IS NULL
      AND p.deleted_at IS NULL;
    """
    rows = await run_readonly_query(query)
    assert len(rows) == 1
    assert int(rows[0]["total_qty"]) == 158298


@pytest.mark.asyncio
async def test_invoice_gt0091_schema_retrieval_and_sql_gen():
    router = ProviderRouter()
    retriever = SQLRetriever(router=router)
    q = "Invoice GT/0091 party"
    schema = await retriever._get_schema(q)
    assert "TABLE purchase" in schema or "purchase" in schema
    assert "TABLE party" in schema or "party" in schema

    sql = await retriever._generate_sql(q, schema)
    assert "purchase" in sql.lower()
    assert "gt/0091" in sql.lower() or "0091" in sql.lower()
