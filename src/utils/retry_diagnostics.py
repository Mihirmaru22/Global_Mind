"""Compact, structured retry diagnostics for bounded pipeline repair.

Engineered to prevent prompt bloat and conserve tokenizer budget (< 40 tokens)
when re-prompting models with strict rate limits (e.g. Groq 6k TPM).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from src.utils.error_classification import FailureCategory


@dataclass
class RetryDiagnostic:
    """Structured diagnostic payload for bounded 1-retry repair attempts."""

    stage: str
    failure_category: FailureCategory
    error_summary: str
    target_constraint: str
    allowed_objects: list[str] | dict[str, list[str]] = field(default_factory=list)
    action_instruction: str = ""
    attempt: int = 1
    max_attempts: int = 1

    def to_compact_prompt(self) -> str:
        """Produce a token-efficient plain text instruction string (< 40-50 tokens).
        
        Avoids verbose JSON syntax overhead (brackets, quotes) for LLM consumption.
        """
        category_name = self.failure_category.value if isinstance(self.failure_category, FailureCategory) else str(self.failure_category)
        parts = [f"RETRY [{category_name}]: {self.error_summary}"]
        if self.target_constraint:
            parts.append(f"Fix: {self.target_constraint}")
        if self.allowed_objects:
            if isinstance(self.allowed_objects, dict):
                obj_str = "; ".join(f"{k}: [{', '.join(v[:6])}]" for k, v in list(self.allowed_objects.items())[:2])
            else:
                obj_str = ", ".join(str(x) for x in self.allowed_objects[:6])
            parts.append(f"Allowed: [{obj_str}]")

        if self.action_instruction:
            parts.append(self.action_instruction)
        return " | ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        """Convert diagnostic to a dictionary for structured trace telemetry."""
        category_name = self.failure_category.value if isinstance(self.failure_category, FailureCategory) else str(self.failure_category)
        return {
            "stage": self.stage,
            "failure_category": category_name,
            "error_summary": self.error_summary,
            "target_constraint": self.target_constraint,
            "allowed_objects": self.allowed_objects,
            "action_instruction": self.action_instruction,
            "attempt": self.attempt,
            "max_attempts": self.max_attempts,
        }
