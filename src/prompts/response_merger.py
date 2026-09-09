"""Prompt 3: Hybrid Response Merger for the GlobalMind Execution Pipeline."""

HYBRID_MERGER_PROMPT = """You are the GlobalMind Response Coordinator. Merge SQL data and RAG text into a unified executive answer.

### Input
<USER_QUESTION>{{USER_QUESTION}}</USER_QUESTION>
<SQL_RESULT>{{SQL_RESULT_JSON}}</SQL_RESULT>
<RAG_RESULT>{{RAG_RESULT_JSON}}</RAG_RESULT>
<ROUTE_TYPE>{{ROUTE_TYPE}}</ROUTE_TYPE>

### Logic
- If BOTH exist: Combine metrics with policy context. Use transitions like "According to policy..."
- If SQL only: Present data clearly. Note that no documents were found.
- If RAG only: Present document answer. Note that no database records matched.
- If NEITHER: Politely explain no information was found.

### Output Format
Return ONLY valid JSON. No markdown fences outside the JSON:
{
  "unified_answer": "The final natural language response in Markdown...",
  "data_summary": {"row_count": 1, "key_metrics": {}},
  "sources_cited": [{"file": "doc.pdf", "page": 1}],
  "confidence_score": 0.0-1.0,
  "follow_up_suggestions": ["Suggestion 1", "Suggestion 2"]
}
"""

# Backward compatibility alias
HYBRID_RESPONSE_MERGER_PROMPT = HYBRID_MERGER_PROMPT


def build_hybrid_response_merger_prompt(
    user_question: str,
    sql_result_json: str,
    rag_result_json: str,
    route_type: str = "HYBRID_PARALLEL",
) -> str:
    """Format Prompt 3 for the hybrid response merger."""
    return (
        HYBRID_MERGER_PROMPT
        .replace("{{USER_QUESTION}}", user_question.strip())
        .replace("{{SQL_RESULT_JSON}}", sql_result_json.strip())
        .replace("{{RAG_RESULT_JSON}}", rag_result_json.strip())
        .replace("{{ROUTE_TYPE}}", route_type.strip())
    )


# Backward compatibility alias
def build_response_merger_prompt(
    user_question: str,
    sql_result_json: str,
    rag_result_json: str,
    route_type: str = "HYBRID_PARALLEL",
) -> str:
    return build_hybrid_response_merger_prompt(user_question, sql_result_json, rag_result_json, route_type)
