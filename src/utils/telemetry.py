"""Structured telemetry logger, timing helpers, and decorators for the SQL pipeline."""

from __future__ import annotations

import asyncio
import contextvars
import datetime
import functools
import json
import logging
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Generator, TypeVar

from src.utils.error_classification import classify_error
from src.utils.feature_flags import DEFAULT_FLAGS, _load_flags_from_yaml

logger = logging.getLogger("telemetry")

_CURRENT_QUERY_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_query_id", default=None)


def get_current_query_id() -> str | None:
    """Get the active query_id from the current async execution context."""
    return _CURRENT_QUERY_ID.get()


def set_current_query_id(qid: str | None) -> contextvars.Token[str | None]:
    """Set the active query_id in the current async execution context."""
    return _CURRENT_QUERY_ID.set(qid)


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
TELEMETRY_FILE = DATA_DIR / "telemetry_events.jsonl"

ALLOWED_STAGES = frozenset({
    "intent_extraction",
    "schema_retrieval",
    "schema_budget_shadow",
    "schema_budget_applied",
    "schema_compaction_applied",
    "sql_generation",
    "sql_validation",
    "sql_execution",
    "sql_repair",
    "empty_result_handling",
    "synthesis",
    "synthesis_bypassed",
    "micro_synthesis",
    "full_synthesis",
    "final_response",
    "llm_call",
    "unknown",
})

F = TypeVar("F", bound=Callable[..., Any])


def get_or_create_query_id(context: dict[str, Any] | None = None) -> str:
    """Retrieve existing query_id from context, ContextVar, or generate a new UUID4 string."""
    if context is not None:
        qid = context.get("query_id")
        if qid:
            set_current_query_id(str(qid))
            return str(qid)

    current = get_current_query_id()
    if current:
        if context is not None:
            context["query_id"] = current
        return current

    new_id = f"gm-q-{uuid.uuid4()}"
    set_current_query_id(new_id)
    if context is not None:
        context["query_id"] = new_id
    return new_id


def log_telemetry(
    query_id: str | None = None,
    stage: str = "unknown",
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    latency_ms: int | float = 0,
    success: bool = True,
    failure_type: str | None = None,
    repair_attempts: int = 0,
    provider: str | None = None,
    model: str | None = None,
    feature_flags: dict[str, bool] | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Log a structured telemetry event safely without throwing exceptions."""
    try:
        if feature_flags is None:
            active_flags = dict(DEFAULT_FLAGS)
            active_flags.update(_load_flags_from_yaml())
        else:
            active_flags = feature_flags

        event = {
            "query_id": str(query_id) if query_id else get_or_create_query_id(),
            "stage": stage if stage in ALLOWED_STAGES else "unknown",
            "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
            "input_tokens": int(input_tokens or 0),
            "output_tokens": int(output_tokens or 0),
            "latency_ms": round(float(latency_ms or 0), 2),
            "success": bool(success),
            "failure_type": failure_type,
            "repair_attempts": int(repair_attempts or 0),
            "provider": str(provider) if provider else None,
            "model": str(model) if model else None,
            "feature_flags": active_flags,
        }
        if extra:
            event["extra"] = extra

        # 1. Log to standard logger as JSON
        logger.info(json.dumps(event, ensure_ascii=False))

        # 2. Append to telemetry file safely
        try:
            TELEMETRY_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(TELEMETRY_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception:
            pass  # File write failure must never bubble up

    except Exception as e:
        logger.warning("Telemetry logging failed: %s", e)


@contextmanager
def timed_stage(
    stage_name: str,
    query_id: str | None = None,
    *,
    extra: dict[str, Any] | None = None,
) -> Generator[dict[str, Any], None, None]:
    """Context manager to measure latency and record structured telemetry for a stage."""
    qid = query_id or get_or_create_query_id()
    result_holder: dict[str, Any] = {
        "query_id": qid,
        "stage": stage_name,
        "input_tokens": 0,
        "output_tokens": 0,
        "latency_ms": 0,
        "success": True,
        "failure_type": None,
        "provider": None,
        "model": None,
        "extra": extra or {},
    }
    start = time.perf_counter()
    try:
        yield result_holder
    except Exception as exc:
        result_holder["success"] = False
        if not result_holder.get("failure_type"):
            result_holder["failure_type"] = classify_error(exc)
        raise
    finally:
        latency_ms = round((time.perf_counter() - start) * 1000.0, 2)
        result_holder["latency_ms"] = latency_ms
        log_telemetry(
            query_id=result_holder.get("query_id", qid),
            stage=stage_name,
            input_tokens=result_holder.get("input_tokens", 0),
            output_tokens=result_holder.get("output_tokens", 0),
            latency_ms=latency_ms,
            success=result_holder.get("success", True),
            failure_type=result_holder.get("failure_type"),
            provider=result_holder.get("provider"),
            model=result_holder.get("model"),
            extra=result_holder.get("extra"),
        )


def capture_telemetry(stage_name: str) -> Callable[[F], F]:
    """Decorator to measure and log structured telemetry for a function."""

    def decorator(func: F) -> F:
        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                qid = kwargs.get("query_id") or get_or_create_query_id()
                start_time = time.perf_counter()
                success = True
                failure_type = None
                try:
                    return await func(*args, **kwargs)
                except Exception as exc:
                    success = False
                    failure_type = classify_error(exc)
                    raise
                finally:
                    latency_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
                    log_telemetry(
                        query_id=qid,
                        stage=stage_name,
                        latency_ms=latency_ms,
                        success=success,
                        failure_type=failure_type,
                    )

            return async_wrapper  # type: ignore[return-value]

        else:

            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                qid = kwargs.get("query_id") or get_or_create_query_id()
                start_time = time.perf_counter()
                success = True
                failure_type = None
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    success = False
                    failure_type = classify_error(exc)
                    raise
                finally:
                    latency_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
                    log_telemetry(
                        query_id=qid,
                        stage=stage_name,
                        latency_ms=latency_ms,
                        success=success,
                        failure_type=failure_type,
                    )

            return sync_wrapper  # type: ignore[return-value]

    return decorator
