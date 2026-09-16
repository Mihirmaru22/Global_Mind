"""Trace and Span context propagation using ContextVar.

Provides thread-safe and coroutine-safe context managers for tracing stages,
nested sub-spans, and parallel execution branches (e.g. sql_branch, rag_branch).
"""

from __future__ import annotations

import contextvars
import logging
import time
import uuid
from contextlib import asynccontextmanager, contextmanager
from typing import Any, AsyncGenerator, Generator

from src.models.trace import GuardResult, Span, Trace
from src.utils.error_classification import classify_failure_category

logger = logging.getLogger("trace_context")

_CURRENT_TRACE: contextvars.ContextVar[Trace | None] = contextvars.ContextVar("current_trace", default=None)
_CURRENT_SPAN: contextvars.ContextVar[Span | None] = contextvars.ContextVar("current_span", default=None)
_CURRENT_BRANCH: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_branch", default=None)


def get_current_trace() -> Trace | None:
    """Retrieve the active Trace from the current async execution context."""
    return _CURRENT_TRACE.get()


def set_current_trace(trace: Trace | None) -> contextvars.Token[Trace | None]:
    """Set the active Trace in the current async execution context."""
    return _CURRENT_TRACE.set(trace)


def get_current_span() -> Span | None:
    """Retrieve the active Span from the current async execution context."""
    return _CURRENT_SPAN.get()


def set_current_span(span: Span | None) -> contextvars.Token[Span | None]:
    """Set the active Span in the current async execution context."""
    return _CURRENT_SPAN.set(span)


def get_current_branch() -> str | None:
    """Retrieve the active execution branch (e.g. 'sql_branch', 'rag_branch')."""
    return _CURRENT_BRANCH.get()


def set_current_branch(branch: str | None) -> contextvars.Token[str | None]:
    """Set the active execution branch in the current async execution context."""
    return _CURRENT_BRANCH.set(branch)


def start_trace(
    query: str,
    mode: str = "auto",
    request_id: str | None = None,
    trace_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Trace:
    """Initialize a new root Trace and bind it to the active execution context."""
    trace = Trace(
        trace_id=trace_id or f"tr-{uuid.uuid4().hex[:12]}",
        request_id=request_id or f"req-{uuid.uuid4().hex[:8]}",
        query=query,
        mode=mode,
        metadata=metadata or {},
    )
    # Create root span
    root_span = Span(
        span_id=f"sp-root-{uuid.uuid4().hex[:8]}",
        parent_span_id=None,
        name="root_pipeline",
        start_time_ms=time.time() * 1000,
    )
    root_span.set_input(query)
    trace.root_span = root_span
    set_current_trace(trace)
    set_current_span(root_span)
    return trace


@contextmanager
def branch_context(branch_name: str) -> Generator[str, None, None]:
    """Context manager to set the execution branch for all nested spans."""
    token = set_current_branch(branch_name)
    try:
        yield branch_name
    finally:
        set_current_branch(token.old_value if hasattr(token, "old_value") else None)


@contextmanager
def trace_span(
    name: str,
    branch: str | None = None,
    parent_span_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Generator[Span, None, None]:
    """Synchronous context manager for tracing a stage or unit of work."""
    trace = get_current_trace()
    active_parent = get_current_span()
    active_branch = branch or get_current_branch()
    resolved_parent_id = parent_span_id or (active_parent.span_id if active_parent else None)

    span = Span(
        name=name,
        branch=active_branch,
        parent_span_id=resolved_parent_id,
        start_time_ms=time.time() * 1000,
        metadata=metadata or {},
    )

    span_token = set_current_span(span)
    branch_token = set_current_branch(active_branch)

    try:
        yield span
    except Exception as exc:
        span.status = "ERROR"
        cat = classify_failure_category(exc, stage=name)
        span.failure_category = cat.value
        span.metadata["error"] = str(exc)
        if trace:
            trace.failure_category = cat.value
        raise
    finally:
        span.end_time_ms = time.time() * 1000
        span.latency_ms = span.end_time_ms - span.start_time_ms
        if trace:
            trace.add_span(span)
        set_current_span(span_token.old_value if hasattr(span_token, "old_value") else None)
        set_current_branch(branch_token.old_value if hasattr(branch_token, "old_value") else None)


@asynccontextmanager
async def async_trace_span(
    name: str,
    branch: str | None = None,
    parent_span_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AsyncGenerator[Span, None]:
    """Asynchronous context manager for tracing an async stage or unit of work."""
    with trace_span(name, branch=branch, parent_span_id=parent_span_id, metadata=metadata) as span:
        yield span
