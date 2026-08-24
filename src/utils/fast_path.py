"""Fast-Path synthesis formatters and micro-prompt builder.

Allows simple data pulls to bypass or minimize LLM synthesis for sub-second latency.
"""

from __future__ import annotations

from typing import Any


def format_list_fast_path(markdown_table: str) -> str:
    """Format direct list queries without calling the synthesis LLM."""
    clean_table = markdown_table.strip()
    return f"Here are the records matching your request:\n\n{clean_table}"


def build_aggregate_micro_prompt(user_question: str, markdown_table: str) -> list[dict[str, str]]:
    """Build a compact micro-prompt asking for a single-sentence executive summary."""
    clean_table = markdown_table.strip()
    return [
        {
            "role": "system",
            "content": (
                "You are a concise business analyst. Given the question and tabular data, "
                "provide a direct, single-sentence summary of the key metric. Do not repeat the table rows."
            ),
        },
        {
            "role": "user",
            "content": f"Question: {user_question}\n\nData:\n{clean_table}\n\nExecutive Summary (1 sentence):",
        },
    ]


def format_aggregate_fast_path(summary: str, markdown_table: str) -> str:
    """Format aggregate response combining 1-sentence micro-summary with markdown table."""
    clean_summary = summary.strip()
    clean_table = markdown_table.strip()
    if clean_summary:
        return f"{clean_summary}\n\n{clean_table}"
    return clean_table
