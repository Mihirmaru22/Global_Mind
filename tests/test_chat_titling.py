"""Unit tests for chat titling heuristics and cleaners in src.api.ui."""

from src.api.ui import _clean_title, _fallback_title


def test_fallback_title_strips_question_prefixes():
    cases = [
        ("What is the unit name of product CAP03", "Unit Name"),
        ("give me warehouse details of finished goods", "Warehouse Details"),
        ("total qty adjusted for product SHP08", "Total Qty Adjusted"),
        ("what products does Apple sell", "Apple Sell"),
        ("how many stock adjustments happened today", "Stock Adjustments Happened"),
        ("How many parties are in the database", "Parties"),
        ("What specific OCR engines are used in rag", "OCR Engines"),
        ("can you tell me about revenue growth in 2024", "Revenue Growth"),
        ("show me all items in warehouse 1", "Items In Warehouse"),
        ("list distinct vendors in the system", "Vendors"),
    ]
    for prompt, expected in cases:
        result = _fallback_title(prompt)
        assert result == expected, f"Prompt '{prompt}' gave '{result}', expected '{expected}'"


def test_fallback_title_bounds_and_empty():
    assert _fallback_title("") == "New Chat"
    assert _fallback_title("   ") == "New Chat"
    assert _fallback_title("hello") == "Hello"
    assert _fallback_title("hello there friend") == "Hello There Friend"


def test_clean_title_normalizes_llm_output():
    assert _clean_title("Title: Warehouse Inventory Report") == "Warehouse Inventory Report"
    assert _clean_title("Chat Title - Fiscal Year 2025") == "Fiscal Year 2025"
    assert _clean_title('"Apple Tax Rate"') == "Apple Tax Rate"
    assert _clean_title("Overview of Global Operations for 2025") == "Overview of Global"
    assert _clean_title("") == ""
