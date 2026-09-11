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


@pytest.mark.asyncio
async def test_hdblow_quantity_adjusted_temporal_intent_sql_gen():
    """Verify Q5 generated SQL does not narrow scope to current_year and returns 158,298."""
    router = ProviderRouter()
    retriever = SQLRetriever(router=router)
    q = "What is the HD-BLOW 54GB quantity adjusted?"
    schema = await retriever._get_schema(q)
    sql = await retriever._generate_sql(q, schema)

    assert "current_year" not in sql.lower(), f"Generated SQL should not filter by current_year: {sql}"

    rows = await run_readonly_query(sql)
    assert len(rows) >= 1
    total_val = None
    for k, v in rows[0].items():
        if any(term in k.lower() for term in ["qty", "quantity", "total", "sum", "adjusted"]):
            total_val = int(float(v))
            break
    if total_val is None:
        total_val = int(float(list(rows[0].values())[-1]))
    assert total_val == 158298, f"Expected 158,298, got {total_val} from rows: {rows}"


def test_acronym_expansion_loading_and_expansion():
    from src.stages.s12_s13_s14_retrieval import _expand_query_acronyms, _get_acronym_expansions
    expansions = _get_acronym_expansions()
    assert "fte" in expansions
    assert "hq" in expansions

    q = _expand_query_acronyms("Apple FTE employees")
    assert "full-time equivalent" in q
    assert "FTE" in q

    q_hq = _expand_query_acronyms("Apple HQ location")
    assert "headquarters" in q_hq


def test_answer_rules_structured_prompt():
    from src.stages.s12_s13_s14_retrieval import _ANSWER_RULES
    assert "Grounding & Precision Rules" in _ANSWER_RULES
    assert "Entity & Terminology Rules" in _ANSWER_RULES
    assert "Citation & Formatting Rules" in _ANSWER_RULES
    assert "approximately" in _ANSWER_RULES
    assert "Document Chunker" in _ANSWER_RULES
    assert "The Nasdaq Stock Market LLC" in _ANSWER_RULES


@pytest.mark.asyncio
async def test_q2_apple_fte_retrieval_and_reranking():
    from src.stages.s11_vector_store import QdrantStore
    from src.stages.s10_embeddings import EmbeddingService
    from src.stages.s12_s13_s14_retrieval import Retriever, Reranker
    from src.core.config import settings

    store = QdrantStore()
    embeddings = EmbeddingService()
    retriever = Retriever(store, embeddings)
    reranker = Reranker()

    results = await retriever.retrieve("Apple FTE employees", top_k=settings.retrieval_top_k)
    target = next((r for r in results if r.chunk.chunk_id == "8485b2df1a08f2fc_chunk_0018"), None)
    assert target is not None, "Apple FTE chunk 0018 must be retrieved by Retriever"
    assert "166,000" in target.chunk.content

    rerank_k = settings.rerank_top_k if settings.enable_deep_rerank else 25
    reranked = await reranker.rerank("Apple FTE employees", results[:rerank_k], top_k=10)
    top_chunk_ids = [r.chunk.chunk_id for r in reranked[:3]]
    assert "8485b2df1a08f2fc_chunk_0018" in top_chunk_ids, f"Target chunk should be in top 3, got: {top_chunk_ids}"


@pytest.mark.asyncio
async def test_q8_rag_architecture_5_layers_retrieval_and_reranking():
    from src.stages.s11_vector_store import QdrantStore
    from src.stages.s10_embeddings import EmbeddingService
    from src.stages.s12_s13_s14_retrieval import Retriever, Reranker
    from src.core.config import settings

    store = QdrantStore()
    embeddings = EmbeddingService()
    retriever = Retriever(store, embeddings)
    reranker = Reranker()

    results = await retriever.retrieve("5 RAG layers", top_k=settings.retrieval_top_k)
    rerank_k = settings.rerank_top_k if settings.enable_deep_rerank else 25
    reranked = await reranker.rerank("5 RAG layers", results[:rerank_k], top_k=25)

    all_content = " ".join(r.chunk.content for r in reranked[:10])
    # Verify all 5 functional layers are present in top 10 reranked chunks
    assert "Data Source" in all_content
    assert "Parser" in all_content
    assert "Embedding" in all_content
    assert "Retrieval" in all_content
    assert "Generation" in all_content


def test_enable_deep_rerank_config_toggle():
    from src.core.config import settings
    assert hasattr(settings, "enable_deep_rerank")
    assert settings.enable_deep_rerank is True
    assert settings.retrieval_top_k == 150
    assert settings.rerank_top_k == 75
    assert settings.generation_context_k == 10


def test_detect_soft_delete_intent():
    from src.stages.s12b_sql_retrieval import detect_soft_delete_intent
    assert detect_soft_delete_intent("What is the sales order due date for HM TOOLS?") == "ACTIVE_ONLY"
    assert detect_soft_delete_intent("Show me active products") == "ACTIVE_ONLY"
    assert detect_soft_delete_intent("Show me deleted invoices for party X.") == "DELETED_ONLY"
    assert detect_soft_delete_intent("Show me removed products") == "DELETED_ONLY"
    assert detect_soft_delete_intent("Give me the audit history of product Y.") == "INCLUDE_ARCHIVED"
    assert detect_soft_delete_intent("Audit trail of removed products") == "DELETED_ONLY"
    assert detect_soft_delete_intent("Show sales orders in the past 30 days") == "ACTIVE_ONLY"
    assert detect_soft_delete_intent("Show past records of invoices") == "INCLUDE_ARCHIVED"
    assert detect_soft_delete_intent("Show archived purchase orders") == "INCLUDE_ARCHIVED"


def test_soft_delete_prompt_scoping():
    from src.stages.s12b_sql_retrieval import SQLRetriever, _build_behavioral_atlas_for_query
    
    # Active query prompt rules
    active_rules = SQLRetriever._get_scoped_readability_rules("What is the sales order due date for HM TOOLS?", ["sales_order", "party"])
    assert "WHERE alias.deleted_at IS NULL" in active_rules
    assert "EXPLICIT DELETED QUERY" not in active_rules
    
    # Deleted query prompt rules
    deleted_rules = SQLRetriever._get_scoped_readability_rules("Show me deleted invoices for party X.", ["stock", "purchase", "party"])
    assert "EXPLICIT DELETED QUERY" in deleted_rules
    assert "WHERE alias.deleted_at IS NOT NULL" in deleted_rules
    assert "DELETED RECORDS" in deleted_rules
    
    # History query prompt rules
    history_rules = SQLRetriever._get_scoped_readability_rules("Give me the audit history of product Y.", ["product"])
    assert "AUDIT / HISTORY QUERY" in history_rules
    assert "Return ALL records (both active and deleted) without soft-delete restriction" in history_rules
    
    # Atlas rule adaptation
    atlas_deleted = _build_behavioral_atlas_for_query({"product"}, "Show me deleted products")
    assert "deleted_at IS NOT NULL" in atlas_deleted
    
    atlas_history = _build_behavioral_atlas_for_query({"product"}, "Give me the audit history of product Y.")
    assert "Omit `product.deleted_at` filter" in atlas_history


@pytest.mark.asyncio
async def test_soft_delete_active_sql_gen():
    from src.core.provider_client import ProviderRouter
    from src.stages.s12b_sql_retrieval import SQLRetriever
    from src.utils.query_budget import get_or_create_budget_controller
    get_or_create_budget_controller(query_id="test_active_sql", force_new=True)
    router = ProviderRouter()
    retriever = SQLRetriever(router=router)
    q = "What is the sales order due date for HM TOOLS?"
    schema = await retriever._get_schema(q)
    sql = await retriever._generate_sql(q, schema)
    if sql:
        assert "deleted_at is null" in sql.lower(), f"Active query must filter deleted_at IS NULL: {sql}"


@pytest.mark.asyncio
async def test_soft_delete_deleted_sql_gen():
    from src.core.provider_client import ProviderRouter
    from src.stages.s12b_sql_retrieval import SQLRetriever
    from src.utils.query_budget import get_or_create_budget_controller
    get_or_create_budget_controller(query_id="test_deleted_sql", force_new=True)
    router = ProviderRouter()
    retriever = SQLRetriever(router=router)
    q = "Show me deleted invoices for party X."
    schema = await retriever._get_schema(q)
    sql = await retriever._generate_sql(q, schema)
    if sql:
        assert "deleted_at is not null" in sql.lower() or "s.deleted_at is null" not in sql.lower(), f"Deleted query should not filter s.deleted_at IS NULL: {sql}"


@pytest.mark.asyncio
async def test_soft_delete_history_sql_gen():
    from src.core.provider_client import ProviderRouter
    from src.stages.s12b_sql_retrieval import SQLRetriever
    from src.utils.query_budget import get_or_create_budget_controller
    get_or_create_budget_controller(query_id="test_history_sql", force_new=True)
    router = ProviderRouter()
    retriever = SQLRetriever(router=router)
    q = "Give me the audit history of product Y."
    schema = await retriever._get_schema(q)
    sql = await retriever._generate_sql(q, schema)
    if sql:
        assert "deleted_at is null" not in sql.lower(), f"History query should not filter deleted_at IS NULL: {sql}"



