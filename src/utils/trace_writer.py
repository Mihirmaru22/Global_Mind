"""Non-blocking background trace emitter and in-memory rolling aggregator.

Ensures:
1. Disk I/O never blocks the FastAPI/asyncio hot path (Guardrail 2).
2. API queries never parse 50MB+ JSONL files on the request thread (Guardrail 4).
"""

from __future__ import annotations

import asyncio
import collections
import datetime
import json
import logging
import threading
from pathlib import Path
from typing import Any

from src.core.config import DATA_DIR
from src.models.trace import Trace

logger = logging.getLogger("trace_writer")

TRACES_FILE = DATA_DIR / "traces.jsonl"


class InMemoryTelemetryAggregator:
    """Rolling in-memory cache and statistical aggregator for pipeline telemetry."""

    def __init__(self, max_traces: int = 1000) -> None:
        self._lock = threading.RLock()
        self._max_traces = max_traces
        self._recent_traces: collections.deque[dict[str, Any]] = collections.deque(maxlen=max_traces)

        # Counters
        self._total_requests = 0
        self._status_counts: dict[str, int] = collections.defaultdict(int)
        self._failure_counts: dict[str, int] = collections.defaultdict(int)
        self._stage_failure_counts: dict[str, int] = collections.defaultdict(int)
        self._guard_stats: dict[str, dict[str, int]] = collections.defaultdict(
            lambda: {"checks": 0, "shadow_blocks": 0, "enforced_blocks": 0}
        )
        self._latencies: collections.deque[float] = collections.deque(maxlen=max_traces)
        self._retries_total = 0
        self._retries_improved = 0

    def record_trace(self, trace_data: dict[str, Any]) -> None:
        """Thread-safely record a serialized trace and update aggregated metrics."""
        with self._lock:
            self._recent_traces.appendleft(trace_data)
            self._total_requests += 1

            status = trace_data.get("status", "UNKNOWN")
            self._status_counts[status] += 1

            failure_cat = trace_data.get("failure_category")
            if failure_cat:
                self._failure_counts[failure_cat] += 1

            latency = trace_data.get("total_latency_ms", 0.0)
            if latency > 0:
                self._latencies.append(latency)

            retries = trace_data.get("retry_count", 0)
            if retries > 0:
                self._retries_total += retries
                if trace_data.get("retry_improved") is True:
                    self._retries_improved += 1

            # Extract guard and span metrics
            for span in trace_data.get("spans", []):
                span_name = span.get("name", "unknown")
                if span.get("status") == "ERROR" and span.get("failure_category"):
                    self._stage_failure_counts[span_name] += 1

                for g in span.get("guard_results", []):
                    g_name = g.get("guard_name", "unknown")
                    stats = self._guard_stats[g_name]
                    stats["checks"] += 1
                    if not g.get("passed"):
                        mode = g.get("mode", "SHADOW")
                        if mode == "ENFORCED":
                            stats["enforced_blocks"] += 1
                        else:
                            stats["shadow_blocks"] += 1

    def get_overview(self) -> dict[str, Any]:
        """Return high-level summary metrics in < 1ms."""
        with self._lock:
            latencies = sorted(self._latencies)
            p50 = latencies[len(latencies) // 2] if latencies else 0.0
            p95_idx = int(len(latencies) * 0.95)
            p95 = latencies[p95_idx] if latencies and p95_idx < len(latencies) else p50

            success_rate = (
                (self._status_counts.get("SUCCESS", 0) / self._total_requests * 100)
                if self._total_requests > 0
                else 100.0
            )
            fallback_rate = (
                (self._status_counts.get("FALLBACK", 0) / self._total_requests * 100)
                if self._total_requests > 0
                else 0.0
            )
            retry_recovery_rate = (
                (self._retries_improved / self._retries_total * 100)
                if self._retries_total > 0
                else 0.0
            )

            return {
                "total_requests": self._total_requests,
                "status_breakdown": dict(self._status_counts),
                "success_rate_percent": round(success_rate, 1),
                "fallback_rate_percent": round(fallback_rate, 1),
                "retry_recovery_rate_percent": round(retry_recovery_rate, 1),
                "retries_total": self._retries_total,
                "retries_improved": self._retries_improved,
                "latency_p50_ms": round(p50, 1),
                "latency_p95_ms": round(p95, 1),
                "sample_size": len(self._recent_traces),
            }

    def get_failures(self) -> dict[str, Any]:
        """Return failure distribution by semantic category and stage."""
        with self._lock:
            return {
                "by_category": dict(self._failure_counts),
                "by_stage": dict(self._stage_failure_counts),
                "total_failures": sum(self._failure_counts.values()),
            }

    def get_guards(self) -> dict[str, Any]:
        """Return guard trigger and block metrics."""
        with self._lock:
            res: dict[str, Any] = {}
            for name, stats in self._guard_stats.items():
                checks = stats["checks"]
                shadow = stats["shadow_blocks"]
                enforced = stats["enforced_blocks"]
                res[name] = {
                    "checks": checks,
                    "shadow_blocks": shadow,
                    "enforced_blocks": enforced,
                    "block_rate_percent": round(((shadow + enforced) / checks * 100), 2) if checks > 0 else 0.0,
                }
            return res

    def get_traces(self, limit: int = 50, status: str | None = None) -> list[dict[str, Any]]:
        """Return recent trace snapshots filtered by status."""
        with self._lock:
            results: list[dict[str, Any]] = []
            for t in self._recent_traces:
                if status and t.get("status") != status:
                    continue
                results.append(t)
                if len(results) >= limit:
                    break
            return results


_GLOBAL_AGGREGATOR = InMemoryTelemetryAggregator()


def get_telemetry_aggregator() -> InMemoryTelemetryAggregator:
    return _GLOBAL_AGGREGATOR


class AsyncTraceWriter:
    """Non-blocking trace writer draining an asyncio queue into DATA_DIR / traces.jsonl."""

    def __init__(self, queue_maxsize: int = 5000) -> None:
        self._queue: asyncio.Queue[dict[str, Any]] | None = None
        self._queue_maxsize = queue_maxsize
        self._worker_task: asyncio.Task[None] | None = None
        self._running = False
        self._aggregator = _GLOBAL_AGGREGATOR

    def _ensure_worker(self) -> None:
        if self._queue is None:
            self._queue = asyncio.Queue(maxsize=self._queue_maxsize)
        if (self._worker_task is None or self._worker_task.done()) and self._running:
            loop = asyncio.get_running_loop()
            self._worker_task = loop.create_task(self._worker())

    async def _worker(self) -> None:
        batch: list[dict[str, Any]] = []
        while self._running or (self._queue and not self._queue.empty()):
            try:
                # Wait for items with a 1.0s timeout to allow periodic batch flush
                item = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                batch.append(item)
                self._queue.task_done()
                while len(batch) < 50 and not self._queue.empty():
                    batch.append(self._queue.get_nowait())
                    self._queue.task_done()
            except asyncio.TimeoutError:
                pass
            except Exception as e:
                logger.warning("Trace queue read exception: %s", e)

            if batch:
                await self._flush_batch(batch)
                batch.clear()

    async def _flush_batch(self, batch: list[dict[str, Any]]) -> None:
        """Write a batch of traces asynchronously to disk without blocking the loop."""
        try:
            TRACES_FILE.parent.mkdir(parents=True, exist_ok=True)
            lines = "\n".join(json.dumps(item, ensure_ascii=False) for item in batch) + "\n"
            await asyncio.to_thread(self._sync_append, TRACES_FILE, lines)
        except Exception as e:
            logger.warning("Failed to write trace batch: %s", e)

    @staticmethod
    def _sync_append(path: Path, content: str) -> None:
        with open(path, "a", encoding="utf-8") as f:
            f.write(content)

    def emit(self, trace: Trace | dict[str, Any]) -> None:
        """Emit trace non-blockingly. Updates memory cache immediately and queues disk I/O."""
        data = trace.to_dict() if isinstance(trace, Trace) else trace
        self._aggregator.record_trace(data)

        try:
            loop = asyncio.get_running_loop()
            self._running = True
            self._ensure_worker()
            if self._queue and not self._queue.full():
                self._queue.put_nowait(data)
            else:
                logger.warning("Trace queue full (%d items); dropping disk write", self._queue_maxsize)
        except RuntimeError:
            # No running event loop (e.g. synchronous test or script)
            self._sync_append(TRACES_FILE, json.dumps(data, ensure_ascii=False) + "\n")

    async def close(self) -> None:
        """Gracefully drain remaining traces and stop the worker."""
        self._running = False
        if self._worker_task and not self._worker_task.done():
            try:
                await asyncio.wait_for(self._worker_task, timeout=3.0)
            except Exception:
                pass


_GLOBAL_WRITER = AsyncTraceWriter()


def emit_trace(trace: Trace | dict[str, Any]) -> None:
    """Public helper to emit a trace safely without blocking."""
    _GLOBAL_WRITER.emit(trace)
