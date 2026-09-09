"""Hybrid Response Merger: Combines SQL and RAG outputs into a unified response."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from src.core.provider_client import ProviderRouter
from src.prompts.response_merger import build_hybrid_response_merger_prompt

logger = logging.getLogger(__name__)


def _format_rows_as_markdown_table(rows: list[dict[str, Any]]) -> str:
    """Format a list of dictionary rows into a clean Markdown table."""
    if not rows:
        return ""
    headers = list(rows[0].keys())
    header_line = "| " + " | ".join(str(h) for h in headers) + " |"
    separator_line = "| " + " | ".join("---" for _ in headers) + " |"
    data_lines = []
    for r in rows[:15]:  # cap at 15 rows for display
        data_lines.append("| " + " | ".join(str(r.get(h, "")) for h in headers) + " |")
    return "\n".join([header_line, separator_line] + data_lines)


def _clean_json_response(raw_text: str) -> dict[str, Any]:
    """Strip markdown formatting and parse JSON safely."""
    text = raw_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text.strip())
        if "final_answer" in data and "unified_answer" not in data:
            data["unified_answer"] = data["final_answer"]
        elif "unified_answer" in data and "final_answer" not in data:
            data["final_answer"] = data["unified_answer"]
        return data
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse JSON directly (%s); attempting regex extraction", e)
        match = re.search(r"(\{.*\})", text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                if "final_answer" in data and "unified_answer" not in data:
                    data["unified_answer"] = data["final_answer"]
                elif "unified_answer" in data and "final_answer" not in data:
                    data["final_answer"] = data["unified_answer"]
                return data
            except json.JSONDecodeError:
                pass
        return {
            "unified_answer": text,
            "final_answer": text,
            "data_summary": None,
            "sources_cited": [],
            "confidence_score": 0.7,
            "follow_up_suggestions": [],
        }


async def merge_hybrid_responses(
    user_question: str,
    sql_result: dict[str, Any] | None,
    rag_result: dict[str, Any] | None,
    route_type: str = "HYBRID_PARALLEL",
    router: ProviderRouter | None = None,
) -> dict[str, Any]:
    """Merge Step 2 SQL execution results and RAG synthesis into a unified response.

    Handles all edge cases:
    - Both SQL and RAG succeed (blends metrics + policy context via LLM)
    - SQL succeeds, RAG has no data (formats table, notes no documents found)
    - RAG succeeds, SQL has no data (presents document answer, notes no DB records)
    - Both fail / return empty (polite zero-token fallback)
    - Low confidence calibration
    """
    if router is None:
        router = ProviderRouter()

    has_sql_data = bool(
        sql_result and (
            sql_result.get("rows")
            or sql_result.get("sql_query")
            or sql_result.get("table_markdown")
        )
    )
    rag_ans = (rag_result.get("answer") or "") if rag_result else ""
    has_rag_data = bool(
        rag_ans
        and "cannot find" not in rag_ans.lower()
        and "no relevant" not in rag_ans.lower()
    )

    # Edge Case 1: Both failed or returned no usable data (Zero-token fast path)
    if not has_sql_data and not has_rag_data:
        msg = (
            "I was unable to find matching database records or document guidance for your question. "
            "Please verify any entity names or consider uploading relevant documentation."
        )
        return {
            "unified_answer": msg,
            "final_answer": msg,
            "data_summary": {"row_count": 0, "key_metrics": {}},
            "sources_cited": [],
            "confidence_score": 0.0,
            "follow_up_suggestions": [
                "Verify spelling of company or product names",
                "Upload related policy or procedure documents",
            ],
        }

    # Edge Case 2: SQL Only (RAG empty/failed)
    if has_sql_data and not has_rag_data:
        parts = []
        if sql_result.get("explanation"):
            parts.append(f"**Database Findings:** {sql_result['explanation']}")
        if sql_result.get("table_markdown"):
            parts.append(sql_result["table_markdown"])
        elif sql_result.get("rows") and isinstance(sql_result["rows"], list):
            parts.append(_format_rows_as_markdown_table(sql_result["rows"]))

        parts.append("\n*Note: No relevant documents or policy manuals were found in the knowledge base.*")
        answer_text = "\n\n".join(parts)
        row_count = len(sql_result.get("rows", [])) if isinstance(sql_result.get("rows"), list) else 1
        return {
            "unified_answer": answer_text,
            "final_answer": answer_text,
            "data_summary": {"row_count": row_count, "key_metrics": {}},
            "sources_cited": [],
            "confidence_score": 0.95,
            "follow_up_suggestions": [
                "Filter these results by date range",
                "View detailed ledger entries",
            ],
        }

    # Edge Case 3: RAG Only (SQL empty/failed)
    if has_rag_data and not has_sql_data:
        sources = rag_result.get("sources", []) if rag_result else []
        answer_text = f"{rag_ans}\n\n*Note: No matching transactional database records were found for this query.*"
        return {
            "unified_answer": answer_text,
            "final_answer": answer_text,
            "data_summary": {"row_count": 0, "key_metrics": {}},
            "sources_cited": sources,
            "confidence_score": rag_result.get("confidence", 0.9) if rag_result else 0.9,
            "follow_up_suggestions": [
                "Search for related SOP or policy documents",
            ],
        }

    # Edge Case 4: Both Succeeded -> Call LLM Merger Prompt to blend naturally
    sql_json_str = json.dumps(sql_result or {"status": "no_data"}, indent=2)
    rag_json_str = json.dumps(rag_result or {"status": "no_data"}, indent=2)

    prompt = build_hybrid_response_merger_prompt(
        user_question=user_question,
        sql_result_json=sql_json_str,
        rag_result_json=rag_json_str,
        route_type=route_type,
    )

    try:
        raw_response = await router.chat(
            task="synthesis",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )
        merged = _clean_json_response(raw_response)

        # Edge Case 5: Low confidence calibration
        confidence = merged.get("confidence_score", 1.0)
        if confidence < 0.4:
            caveat = "\n\n> ⚠️ *Note: This response has lower confidence due to partial or missing information in the underlying sources.*"
            if "unified_answer" in merged and caveat not in merged["unified_answer"]:
                merged["unified_answer"] += caveat
                merged["final_answer"] = merged["unified_answer"]

        return merged

    except Exception as e:
        logger.error("Failed to execute hybrid response merger LLM call: %s", e)
        # Fallback deterministic merger
        answer_parts = []
        if sql_result:
            if sql_result.get("explanation"):
                answer_parts.append(f"**Operational Data:** {sql_result['explanation']}")
            if sql_result.get("table_markdown"):
                answer_parts.append(sql_result["table_markdown"])
            elif sql_result.get("rows"):
                answer_parts.append(_format_rows_as_markdown_table(sql_result["rows"]))
        if rag_result and rag_result.get("answer"):
            answer_parts.append(f"**Policy / Document Guidance:** {rag_result['answer']}")

        fallback_text = "\n\n".join(answer_parts) if answer_parts else "Unable to synthesize response."
        return {
            "unified_answer": fallback_text,
            "final_answer": fallback_text,
            "data_summary": {"row_count": len(sql_result.get("rows", [])) if sql_result and isinstance(sql_result.get("rows"), list) else 0, "key_metrics": {}},
            "sources_cited": rag_result.get("sources", []) if rag_result else [],
            "confidence_score": 0.7,
            "follow_up_suggestions": [],
        }
