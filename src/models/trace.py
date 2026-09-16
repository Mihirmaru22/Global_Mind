"""Trace and Span data models for pipeline observability.

Supports hierarchical parent-child execution branches (e.g. sql_branch and rag_branch).
Designed to be completely async-safe and lock-free: child spans are collected by their
respective branches and merged synchronously into the root Trace after `await asyncio.gather()`
completes, avoiding event-loop blocking or deadlock risks.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any


def _hash_payload(payload: Any) -> str:
    """Generate a compact 12-char SHA256 hex hash of a string or JSON-serializable object."""
    if payload is None:
        return ""
    if not isinstance(payload, str):
        try:
            payload = json.dumps(payload, sort_keys=True, default=str)
        except Exception:
            payload = str(payload)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


@dataclass
class GuardResult:
    """Result of evaluating a deterministic guard in shadow or enforced mode."""

    guard_name: str                     # e.g., "sql_safety", "rag_citation", "temporal_filter"
    passed: bool
    mode: str = "SHADOW"                # "SHADOW" or "ENFORCED"
    failure_category: str | None = None # FailureCategory value if failed
    message: str = ""
    latency_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Span:
    """A discrete unit of work within the query pipeline.
    
    Supports parent-child relationships and execution branch tags (e.g. 'sql_branch', 'rag_branch').
    """

    span_id: str = field(default_factory=lambda: f"sp-{uuid.uuid4().hex[:12]}")
    parent_span_id: str | None = None
    name: str = "stage"
    branch: str | None = None           # None (common), "sql_branch", "rag_branch"
    start_time_ms: float = 0.0
    end_time_ms: float = 0.0
    latency_ms: float = 0.0
    input_hash: str = ""
    output_hash: str = ""
    status: str = "OK"                  # "OK", "ERROR", "SHADOW_BLOCKED", "FALLBACK"
    confidence: float | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    guard_results: list[GuardResult] = field(default_factory=list)
    failure_category: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def set_input(self, data: Any) -> None:
        """Hash and record the input payload without retaining large objects in memory."""
        self.input_hash = _hash_payload(data)

    def set_output(self, data: Any) -> None:
        """Hash and record the output payload."""
        self.output_hash = _hash_payload(data)

    def add_guard(self, guard: GuardResult) -> None:
        self.guard_results.append(guard)
        if not guard.passed and guard.failure_category:
            if guard.mode == "ENFORCED":
                if self.failure_category is None:
                    self.failure_category = guard.failure_category
                self.status = "ERROR"
            elif guard.mode == "SHADOW" and self.status == "OK":
                self.status = "SHADOW_BLOCKED"

    def to_dict(self) -> dict[str, Any]:
        return {
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "name": self.name,
            "branch": self.branch,
            "start_time_ms": self.start_time_ms,
            "end_time_ms": self.end_time_ms,
            "latency_ms": round(self.latency_ms, 2),
            "input_hash": self.input_hash,
            "output_hash": self.output_hash,
            "status": self.status,
            "confidence": self.confidence,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "guard_results": [g.to_dict() for g in self.guard_results],
            "failure_category": self.failure_category,
            "metadata": self.metadata,
        }


@dataclass
class Trace:
    """Root trace object capturing the end-to-end lifecycle of a query.
    
    Thread-safe and coroutine-safe for concurrent branch mutations (asyncio.gather).
    """

    trace_id: str = field(default_factory=lambda: f"tr-{uuid.uuid4().hex[:12]}")
    request_id: str = field(default_factory=lambda: f"req-{uuid.uuid4().hex[:8]}")
    query: str = ""
    mode: str = "auto"                  # "auto", "sql", "rag", "hybrid"
    timestamp: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    pipeline_version: str = "1.0.0"
    prompt_version: str = "2026.09-v1"
    model_version: str = "dynamic"
    root_span: Span | None = None
    spans: list[Span] = field(default_factory=list)
    status: str = "RUNNING"             # "SUCCESS", "FALLBACK", "FAILED", "RUNNING"
    failure_category: str | None = None
    total_tokens: int = 0
    total_latency_ms: float = 0.0
    retry_count: int = 0
    retry_improved: bool | None = None
    final_response_preview: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_span(self, span: Span) -> None:
        """Append a span and update cumulative metrics."""
        self.spans.append(span)
        self.total_tokens += (span.input_tokens + span.output_tokens)
        if span.failure_category and self.failure_category is None:
            self.failure_category = span.failure_category

    def merge_branch(self, branch_name: str, branch_spans: list[Span], tokens: int = 0) -> None:
        """Merge a collection of spans produced by a concurrent execution branch (e.g. after gather)."""
        for span in branch_spans:
            if span.branch is None:
                span.branch = branch_name
            self.spans.append(span)
        self.total_tokens += tokens

    def record_tokens(self, input_tokens: int = 0, output_tokens: int = 0) -> None:
        """Increment token count."""
        self.total_tokens += (input_tokens + output_tokens)

    def record_retry(self, stage: str, improved: bool) -> None:
        """Record a retry attempt and whether it resolved the issue."""
        self.retry_count += 1
        self.retry_improved = improved
        self.metadata.setdefault("retries", []).append({
            "stage": stage,
            "improved": improved,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        })

    def complete(
        self,
        status: str = "SUCCESS",
        final_response: str = "",
        failure_category: str | None = None,
    ) -> None:
        """Finalize the trace with status, latency calculation, and response preview."""
        self.status = status
        if failure_category:
            self.failure_category = failure_category
        if final_response:
            self.final_response_preview = final_response[:200]
        if self.spans:
            earliest_start = min((s.start_time_ms for s in self.spans if s.start_time_ms > 0), default=0.0)
            latest_end = max((s.end_time_ms for s in self.spans), default=0.0)
            if earliest_start > 0 and latest_end >= earliest_start:
                self.total_latency_ms = round(latest_end - earliest_start, 2)

    def to_dict(self) -> dict[str, Any]:
        """Convert trace to a serializable dictionary."""
        return {
            "trace_id": self.trace_id,
            "request_id": self.request_id,
            "query": self.query[:500],
            "mode": self.mode,
            "timestamp": self.timestamp,
            "pipeline_version": self.pipeline_version,
            "prompt_version": self.prompt_version,
            "model_version": self.model_version,
            "root_span": self.root_span.to_dict() if self.root_span else None,
            "spans": [s.to_dict() for s in self.spans],
            "status": self.status,
            "failure_category": self.failure_category,
            "total_tokens": self.total_tokens,
            "total_latency_ms": round(self.total_latency_ms, 2),
            "retry_count": self.retry_count,
            "retry_improved": self.retry_improved,
            "final_response_preview": self.final_response_preview,
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        """Serialize trace to JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False)
