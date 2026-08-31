"""Tests for Phase 12: Zero-Token Query Intent Classifier."""

from __future__ import annotations

import pytest

from src.utils.query_classifier import (
    AGGREGATE_QUERY,
    EXPLANATION_QUERY,
    LIST_QUERY,
    classify_query_intent,
)


def test_list_query_classification():
    """Test 1: List and record retrieval intents are classified as list_query."""
    queries = [
        "List the top 5 customers",
        "Show me the last 10 invoices",
        "Fetch all active products",
        "Give me recent orders",
        "Display order details for customer 101",
        "Find all pending shipments",
        "Get all records from party table",
    ]
    for q in queries:
        assert classify_query_intent(q) == LIST_QUERY, f"Failed for list query: {q}"


def test_aggregate_query_classification():
    """Test 2: Metric aggregation and summary queries are classified as aggregate_query."""
    queries = [
        "Total sales by month",
        "What is the total revenue by region?",
        "How many orders were placed today?",
        "What is the average order value?",
        "Count of customers per state",
        "Revenue breakdown by financial year",
        "Highest selling product this year",
    ]
    for q in queries:
        assert classify_query_intent(q) == AGGREGATE_QUERY, f"Failed for aggregate query: {q}"


def test_explanation_query_classification():
    """Test 3: Explanatory, diagnostic, and causal queries are classified as explanation_query."""
    queries = [
        "Why are sales down this month?",
        "Explain why revenue dropped in Q3",
        "What is the cause of shipment delays?",
        "Diagnose order cancellations",
        "Compare revenue between 2024 and 2025 and explain the trend",
    ]
    for q in queries:
        assert classify_query_intent(q) == EXPLANATION_QUERY, f"Failed for explanation query: {q}"


def test_ambiguous_and_empty_query_fallback():
    """Test 4: Ambiguous, keyword-sparse, or empty queries fail-safe to explanation_query."""
    ambiguous_queries = [
        "Customer data",
        "Orders",
        "Information",
        "",
        "   ",
    ]
    for q in ambiguous_queries:
        assert classify_query_intent(q) == EXPLANATION_QUERY, f"Failed fallback for: {q}"
