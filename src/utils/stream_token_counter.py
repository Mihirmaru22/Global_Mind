"""Stream Token Counter & Circuit Breaker.

Provides real-time token tracking during streaming LLM calls to cut streams
immediately when token consumption exceeds allocated budget limits, preventing
uncontrolled billing, latency spikes, and provider rate limit exhaustion.
"""

from __future__ import annotations

import logging
import time
from typing import Any

try:
    import tiktoken
except ImportError:
    tiktoken = None  # type: ignore[assignment]

class QueryBudgetExceededError(RuntimeError):
    """Raised when a query exceeds its allocated resource budget."""
    pass


logger = logging.getLogger(__name__)


class TokenBudgetExceededError(QueryBudgetExceededError):
    """Raised when streaming or LLM execution exceeds the allowed token budget."""

    def __init__(self, message: str, count: int = 0, limit: int = 0) -> None:
        super().__init__(message)
        self.count = count
        self.limit = limit


class StreamTokenCounter:
    """Stateful token counter for streaming LLM responses with hard limit enforcement.

    Tracks token consumption per chunk using dynamic tiktoken encoding
    (e.g., o200k_base for Llama 3 / newer models, cl100k_base for GPT-4 / Groq)
    with atomic counter updates and instant interrupt triggering.
    """

    _ENCODER_CACHE: dict[str, Any] = {}

    def __init__(
        self,
        hard_limit: int = 8000,
        model_name: str = "",
        provider_name: str = "",
        tokenizer_model: str = "cl100k_base",
        safety_buffer: int = 200,
    ) -> None:
        self.hard_limit = int(hard_limit)
        self.safety_buffer = int(safety_buffer)
        self.model_name = model_name
        self.provider_name = provider_name
        self.tokenizer_model = self._resolve_tokenizer_name(model_name, provider_name, tokenizer_model)
        
        self.current_count: int = 0
        self.is_exceeded: bool = False
        self.last_checked_at: float = time.time()
        self.chunks_received: int = 0

        self._encoder = self._get_or_load_encoder(self.tokenizer_model)

    @classmethod
    def _resolve_tokenizer_name(cls, model_name: str, provider_name: str, fallback: str) -> str:
        """Dynamically pick the closest tiktoken encoding based on model and provider."""
        model_lower = (model_name or "").lower()
        provider_lower = (provider_name or "").lower()

        if "o200k" in model_lower or "gpt-4o" in model_lower or "o1" in model_lower or "o3" in model_lower:
            return "o200k_base"
        if "llama-3" in model_lower or "llama3" in model_lower or "nvidia" in provider_lower:
            # Llama 3 vocabulary uses 128k BPE; o200k_base is closest match in tiktoken
            return "o200k_base"
        if "gpt-4" in model_lower or "gpt-3.5" in model_lower or "groq" in provider_lower:
            return "cl100k_base"
        
        return fallback or "cl100k_base"

    @classmethod
    def _get_or_load_encoder(cls, encoding_name: str) -> Any:
        """Retrieve or cache tiktoken encoding."""
        if tiktoken is None:
            return None

        if encoding_name not in cls._ENCODER_CACHE:
            try:
                cls._ENCODER_CACHE[encoding_name] = tiktoken.get_encoding(encoding_name)
            except Exception as e:
                logger.debug("Failed to load tiktoken encoding '%s': %s. Falling back to cl100k_base.", encoding_name, e)
                try:
                    cls._ENCODER_CACHE[encoding_name] = tiktoken.get_encoding("cl100k_base")
                except Exception:
                    cls._ENCODER_CACHE[encoding_name] = None

        return cls._ENCODER_CACHE.get(encoding_name)

    def add_chunk(self, text: str) -> int:
        """Encode incoming text chunk, update current token count, and return added tokens."""
        if not text:
            return 0

        tokens_added = 0
        if self._encoder is not None:
            try:
                tokens_added = len(self._encoder.encode(text, disallowed_special=()))
            except Exception as e:
                logger.debug("tiktoken encoding error: %s. Estimating via character count.", e)
                tokens_added = max(1, len(text) // 4)
        else:
            # Fallback estimation (~4 chars per token)
            tokens_added = max(1, len(text) // 4)

        self.current_count += tokens_added
        self.chunks_received += 1
        self.last_checked_at = time.time()

        if self.current_count >= (self.hard_limit + self.safety_buffer):
            self.is_exceeded = True

        return tokens_added

    def check_limit(self) -> bool:
        """Return True if the token count has exceeded hard_limit + safety_buffer."""
        if self.current_count >= (self.hard_limit + self.safety_buffer):
            self.is_exceeded = True
            return True
        return False

    def raise_if_exceeded(self) -> None:
        """Raise TokenBudgetExceededError immediately if limit is breached."""
        if self.check_limit():
            msg = (
                f"Stream token budget exceeded: {self.current_count} tokens consumed "
                f"(hard_limit={self.hard_limit}, buffer={self.safety_buffer}, "
                f"model={self.model_name or self.tokenizer_model})"
            )
            logger.warning(msg)
            raise TokenBudgetExceededError(msg, count=self.current_count, limit=self.hard_limit)

    def get_status(self) -> dict[str, Any]:
        """Return telemetry status dictionary."""
        return {
            "current_count": self.current_count,
            "hard_limit": self.hard_limit,
            "safety_buffer": self.safety_buffer,
            "is_exceeded": self.is_exceeded,
            "chunks_received": self.chunks_received,
            "tokenizer_model": self.tokenizer_model,
            "last_checked_at": self.last_checked_at,
        }
