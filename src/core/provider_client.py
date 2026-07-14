"""Provider-agnostic LLM/vision client with automatic cross-provider fallback.

This is the load-bearing infrastructure layer. Every LLM and vision call in the
pipeline goes through ProviderRouter, which:
  1. Selects the best available provider for a given task type
  2. Falls back to the next provider on rate-limit (429) or server error (5xx)
  3. Tracks per-provider rate limits via the RateLimiter
  4. Presents a uniform interface regardless of provider-specific API quirks

Design decision: we use the OpenAI-compatible client for NIM, Groq, and OpenRouter
(they all support the OpenAI chat completions format). Gemini uses its own REST API
via httpx. This avoids pulling in provider-specific SDKs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Protocol, runtime_checkable

import httpx
from openai import AsyncOpenAI

from src.core.config import settings
from src.core.rate_limiter import RateLimiter
from src.models.schemas import TokenUsage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared HTTP clients (created once per process, reused across requests)
# ---------------------------------------------------------------------------
# A ProviderRouter is built fresh per request (so each query gets an isolated
# RateLimiter). If every provider also spun up its own AsyncOpenAI / httpx
# client, those connection pools would never be closed and would accumulate
# across requests, leaking sockets/file descriptors. Instead, the underlying
# clients live at module scope and are shared by all provider instances that
# target the same endpoint — the correct long-lived pattern for httpx clients.

_shared_openai_clients: dict[tuple[str, str], "AsyncOpenAI"] = {}
_shared_gemini_http: "httpx.AsyncClient | None" = None


# ---------------------------------------------------------------------------
# Rate-limit detection
# ---------------------------------------------------------------------------

_MAX_BACKOFF_SECONDS = 60.0


def _rate_limit_retry_after(exc: Exception) -> float | None:
    """Return a backoff duration (seconds) if ``exc`` is a 429, else ``None``.

    Detects a rate-limit response from either the OpenAI SDK (which exposes
    ``status_code``) or a raw ``httpx`` error (``exc.response.status_code``),
    and honours a ``Retry-After`` header when present. Returning ``None`` for
    anything that isn't a 429 keeps ordinary failures (5xx, timeouts) out of
    the cooldown path so they can still be retried normally on the next call.
    """
    status = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    if status is None and response is not None:
        status = getattr(response, "status_code", None)
    if status != 429:
        return None

    retry_after = 5.0
    headers = getattr(response, "headers", None)
    if headers is not None:
        raw = None
        try:
            raw = headers.get("retry-after") or headers.get("Retry-After")
        except Exception:
            raw = None
        if raw:
            try:
                retry_after = float(raw)
            except (TypeError, ValueError):
                retry_after = 5.0
    return min(max(retry_after, 0.0), _MAX_BACKOFF_SECONDS)


# ---------------------------------------------------------------------------
# Token-usage normalization
# ---------------------------------------------------------------------------
# Each provider reports usage in its own shape. These helpers write a single
# per-call TokenUsage sink so the router can accumulate a uniform total. The
# sink is always freshly created per call, so plain assignment (not +=) is
# correct here — accumulation happens one level up in the router.

def _apply_openai_usage(sink: TokenUsage, usage_obj: Any, *, provider: str, model: str) -> None:
    """Fill a sink from an OpenAI-style usage object.

    ``completion_tokens`` already *includes* any reasoning tokens, so the
    visible output is completion minus reasoning. Reasoning is exposed (when
    present) under ``completion_tokens_details.reasoning_tokens``.
    """
    if usage_obj is None:
        return
    prompt = getattr(usage_obj, "prompt_tokens", 0) or 0
    completion = getattr(usage_obj, "completion_tokens", 0) or 0
    reasoning = 0
    details = getattr(usage_obj, "completion_tokens_details", None)
    if details is not None:
        reasoning = getattr(details, "reasoning_tokens", 0) or 0
    sink.input_tokens = prompt
    sink.output_tokens = max(completion - reasoning, 0)
    sink.thinking_tokens = reasoning
    sink.provider = provider
    sink.model = model


def _apply_gemini_usage(sink: TokenUsage, meta: dict[str, Any] | None, *, provider: str, model: str) -> None:
    """Fill a sink from a Gemini ``usageMetadata`` block.

    Gemini reports thinking separately (``thoughtsTokenCount``) — it is NOT
    folded into ``candidatesTokenCount`` — which matches our shape exactly.
    """
    if not meta:
        return
    sink.input_tokens = meta.get("promptTokenCount", 0) or 0
    sink.output_tokens = meta.get("candidatesTokenCount", 0) or 0
    sink.thinking_tokens = meta.get("thoughtsTokenCount", 0) or 0
    sink.provider = provider
    sink.model = model


# ---------------------------------------------------------------------------
# Provider Protocol — the interface all providers implement
# ---------------------------------------------------------------------------

@runtime_checkable
class LLMProvider(Protocol):
    """Protocol for LLM providers — any new provider just implements this."""

    @property
    def name(self) -> str: ...

    @property
    def is_available(self) -> bool: ...

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        response_format: dict[str, str] | None = None,
        usage: TokenUsage | None = None,
    ) -> str: ...

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        usage: TokenUsage | None = None,
    ) -> AsyncGenerator[str, None]: ...

    async def vision(
        self,
        image_data: bytes,
        prompt: str,
        *,
        model: str,
        mime_type: str = "image/png",
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> str: ...


# ---------------------------------------------------------------------------
# Concrete providers
# ---------------------------------------------------------------------------

class OpenAICompatibleProvider:
    """Provider for any OpenAI-compatible API (NIM, Groq, OpenRouter)."""

    def __init__(self, name: str, base_url: str, api_key: str, rate_limiter: RateLimiter) -> None:
        self._name = name
        self._api_key = api_key
        self._rate_limiter = rate_limiter
        self._client: AsyncOpenAI | None = None
        self._base_url = base_url

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_available(self) -> bool:
        return bool(self._api_key)

    def _get_client(self) -> AsyncOpenAI:
        # An injected/pre-set client (tests) always wins. Otherwise reuse a
        # process-wide client keyed by endpoint+key so per-request routers don't
        # each leak a fresh connection pool.
        if self._client is not None:
            return self._client
        key = (self._base_url, self._api_key)
        client = _shared_openai_clients.get(key)
        if client is None:
            client = AsyncOpenAI(
                base_url=self._base_url,
                api_key=self._api_key,
                timeout=60.0,
            )
            _shared_openai_clients[key] = client
        self._client = client
        return client

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        response_format: dict[str, str] | None = None,
        usage: TokenUsage | None = None,
    ) -> str:
        await self._rate_limiter.acquire(self._name)
        client = self._get_client()
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            kwargs["response_format"] = response_format
        response = await client.chat.completions.create(**kwargs)
        if usage is not None:
            _apply_openai_usage(usage, getattr(response, "usage", None), provider=self._name, model=model)
        return response.choices[0].message.content or ""

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        usage: TokenUsage | None = None,
    ) -> AsyncGenerator[str, None]:
        await self._rate_limiter.acquire(self._name)
        client = self._get_client()
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        # Usage is not sent during a stream unless explicitly requested; it then
        # arrives in a final chunk whose `choices` list is empty.
        if usage is not None:
            kwargs["stream_options"] = {"include_usage": True}
        response = await client.chat.completions.create(**kwargs)
        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
            if usage is not None and getattr(chunk, "usage", None):
                _apply_openai_usage(usage, chunk.usage, provider=self._name, model=model)

    async def vision(
        self,
        image_data: bytes,
        prompt: str,
        *,
        model: str,
        mime_type: str = "image/png",
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> str:
        import base64

        await self._rate_limiter.acquire(self._name)
        client = self._get_client()
        b64 = base64.b64encode(image_data).decode()
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{b64}"},
                    },
                ],
            }
        ]
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content or ""


class GeminiProvider:
    """Provider for Google Gemini via the REST API (AI Studio free tier)."""

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self, rate_limiter: RateLimiter) -> None:
        self._api_key = settings.gemini_api_key
        self._rate_limiter = rate_limiter
        self._http: httpx.AsyncClient | None = None

    @property
    def name(self) -> str:
        return "gemini"

    @property
    def is_available(self) -> bool:
        return bool(self._api_key)

    def _get_http(self) -> httpx.AsyncClient:
        # An injected/pre-set client (tests) always wins. Otherwise reuse a
        # process-wide httpx client so per-request routers don't each leak a
        # fresh connection pool.
        if self._http is not None:
            return self._http
        global _shared_gemini_http
        if _shared_gemini_http is None:
            _shared_gemini_http = httpx.AsyncClient(timeout=120.0)
        self._http = _shared_gemini_http
        return _shared_gemini_http

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        response_format: dict[str, str] | None = None,
        usage: TokenUsage | None = None,
    ) -> str:
        await self._rate_limiter.acquire(self.name)
        http = self._get_http()

        # Convert OpenAI-style messages to Gemini format
        contents = []
        system_instruction = None
        for msg in messages:
            if msg["role"] == "system":
                system_instruction = msg["content"]
            else:
                role = "user" if msg["role"] == "user" else "model"
                contents.append({"role": role, "parts": [{"text": msg["content"]}]})

        # Floor the output budget so short callers (e.g. max_tokens=10) still
        # get a usable answer. Thinking is disabled below, so this budget is
        # spent entirely on the visible response.
        effective_max_tokens = max(max_tokens, 1024)

        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": effective_max_tokens,
                # Gemini 2.5 thinking models draw reasoning tokens from the
                # maxOutputTokens budget, so leaving thinking enabled starves
                # and truncates the visible answer mid-sentence. Disable it for
                # text generation so the entire budget goes to the response.
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }
        if system_instruction:
            body["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        if response_format and response_format.get("type") == "json_object":
            body["generationConfig"]["responseMimeType"] = "application/json"

        url = f"{self.BASE_URL}/models/{model}:generateContent"
        headers = {"x-goog-api-key": self._api_key}
        resp = await http.post(url, json=body, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        if usage is not None:
            _apply_gemini_usage(usage, data.get("usageMetadata"), provider=self.name, model=model)
        return self._extract_gemini_text(data)

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        usage: TokenUsage | None = None,
    ) -> AsyncGenerator[str, None]:
        import json
        await self._rate_limiter.acquire(self.name)
        http = self._get_http()

        contents = []
        system_instruction = None
        for msg in messages:
            if msg["role"] == "system":
                system_instruction = msg["content"]
            else:
                role = "user" if msg["role"] == "user" else "model"
                contents.append({"role": role, "parts": [{"text": msg["content"]}]})

        effective_max_tokens = max(max_tokens, 1024)

        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": effective_max_tokens,
                # Gemini 2.5 thinking models draw reasoning tokens from the
                # maxOutputTokens budget, so leaving thinking enabled starves
                # and truncates the visible answer mid-sentence. Disable it for
                # text generation so the entire budget goes to the response.
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }
        if system_instruction:
            body["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        url = f"{self.BASE_URL}/models/{model}:streamGenerateContent?alt=sse"
        headers = {"x-goog-api-key": self._api_key}

        async with http.stream("POST", url, json=body, headers=headers) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        continue
                    try:
                        data = json.loads(data_str)
                        text = self._extract_gemini_text(data)
                        if text:
                            yield text
                        # Gemini streams cumulative usage on each SSE frame; the
                        # last one carries the final totals, so overwriting as we
                        # go leaves the correct end state.
                        if usage is not None and "usageMetadata" in data:
                            _apply_gemini_usage(usage, data["usageMetadata"], provider=self.name, model=model)
                    except json.JSONDecodeError:
                        pass

    async def vision(
        self,
        image_data: bytes,
        prompt: str,
        *,
        model: str,
        mime_type: str = "image/png",
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> str:
        import base64

        await self._rate_limiter.acquire(self.name)
        http = self._get_http()
        b64 = base64.b64encode(image_data).decode()

        body: dict[str, Any] = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": prompt},
                        {"inlineData": {"mimeType": mime_type, "data": b64}},
                    ],
                }
            ],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max(max_tokens, 1024),
            },
        }

        url = f"{self.BASE_URL}/models/{model}:generateContent"
        headers = {"x-goog-api-key": self._api_key}
        resp = await http.post(url, json=body, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        return self._extract_gemini_text(data)

    @staticmethod
    def _extract_gemini_text(data: dict[str, Any]) -> str:
        """Extract text from a Gemini response, handling thinking-model multi-part output.

        Thinking models (2.5 Flash) return parts like:
          [{"thought": true, ...}, {"text": "actual response"}]
        We want the last part that has a 'text' key and is NOT a thought.
        """
        try:
            parts = data["candidates"][0]["content"]["parts"]
            # Find the last non-thought text part
            for part in reversed(parts):
                if "text" in part and not part.get("thought", False):
                    return part["text"]
            # Fallback: any part with text
            for part in parts:
                if "text" in part:
                    return part["text"]
            return ""
        except (KeyError, IndexError):
            logger.error("Unexpected Gemini response structure: %s", data)
            return ""


# ---------------------------------------------------------------------------
# Task-based routing configuration
# ---------------------------------------------------------------------------

@dataclass
class ProviderOption:
    """A single provider+model pair for a specific task."""
    provider_name: str
    model: str
    priority: int = 0


@dataclass
class TaskRoute:
    """Ordered fallback chain for a specific task type."""
    options: list[ProviderOption] = field(default_factory=list)


# Tasks that require a vision-capable model. When a user pins a provider that
# isn't already in one of these routes (e.g. OpenRouter), we must select a
# vision model, not a text model, or the call will fail.
_VISION_TASKS = frozenset({
    "ocr_vision",
    "layout_analysis",
    "table_extraction",
    "chart_analysis",
    "image_understanding",
})


# Default routing — the "Frankenstein pipeline" from Section 7 of the arch doc.
DEFAULT_ROUTES: dict[str, TaskRoute] = {
    "semantic_classification": TaskRoute([
        ProviderOption("gemini", "gemini-2.5-flash-lite", 1),
        ProviderOption("groq", "llama-3.1-8b-instant", 2),
    ]),
    "ocr_vision": TaskRoute([
        ProviderOption("gemini", "gemini-2.5-flash", 1),
        ProviderOption("nvidia_nim", "meta/llama-3.2-90b-vision-instruct", 2),
    ]),
    "layout_analysis": TaskRoute([
        ProviderOption("gemini", "gemini-2.5-flash", 1),
        ProviderOption("nvidia_nim", "meta/llama-3.2-90b-vision-instruct", 2),
    ]),
    "table_extraction": TaskRoute([
        ProviderOption("gemini", "gemini-2.5-flash", 1),
        ProviderOption("nvidia_nim", "meta/llama-3.2-90b-vision-instruct", 2),
    ]),
    "chart_analysis": TaskRoute([
        ProviderOption("gemini", "gemini-2.5-flash", 1),
        ProviderOption("nvidia_nim", "meta/llama-3.2-90b-vision-instruct", 2),
        ProviderOption("nvidia_nim", "nvidia/nemotron-nano-12b-v2-vl", 3),
    ]),
    "image_understanding": TaskRoute([
        ProviderOption("gemini", "gemini-2.5-flash", 1),
        ProviderOption("nvidia_nim", "nvidia/nemotron-nano-12b-v2-vl", 2),
    ]),
    "general_qa": TaskRoute([
        ProviderOption("gemini", "gemini-2.5-flash", 1),
        ProviderOption("groq", "llama-3.3-70b-versatile", 2),
        ProviderOption("nvidia_nim", "qwen/qwen3.5-397b-a17b", 3),
    ]),
    "reasoning": TaskRoute([
        ProviderOption("groq", "llama-3.3-70b-versatile", 1),
        ProviderOption("gemini", "gemini-2.5-flash", 2),
        ProviderOption("nvidia_nim", "meta/llama3-70b-instruct", 3),
    ]),
    "extraction": TaskRoute([
        ProviderOption("nvidia_nim", "qwen/qwen3.5-397b-a17b", 1),
        ProviderOption("gemini", "gemini-2.5-flash", 2),
        ProviderOption("groq", "llama-3.1-8b-instant", 3),
    ]),
    "summarization": TaskRoute([
        ProviderOption("nvidia_nim", "moonshotai/kimi-k2.6", 1),
        ProviderOption("gemini", "gemini-2.5-flash", 2),
    ]),
    "fast_support": TaskRoute([
        ProviderOption("groq", "llama-3.1-8b-instant", 1),
        ProviderOption("gemini", "gemini-2.5-flash-lite", 2),
    ]),
}


# ---------------------------------------------------------------------------
# Router — the main entry point for all LLM/vision calls
# ---------------------------------------------------------------------------

class ProviderRouter:
    """Routes LLM/vision calls to the best available provider with auto-fallback.

    Usage:
        router = ProviderRouter()
        result = await router.chat("semantic_classification", messages=[...])
        result = await router.vision("chart_analysis", image_data=img, prompt="Describe this chart")
    """

    def __init__(
        self,
        routes: dict[str, TaskRoute] | None = None,
        preferred_provider: str | None = None,
    ) -> None:
        self._rate_limiter = RateLimiter()
        self._routes = routes or self._load_yaml_routes() or DEFAULT_ROUTES
        # A soft pin: the caller's preferred provider is promoted to the front
        # of every task chain, but the rest of the chain stays intact as
        # fallback. "auto" (or empty) means no pin — use the routes as authored.
        pref = (preferred_provider or "").strip().lower()
        self._preferred_provider: str | None = pref if pref and pref != "auto" else None
        # The provider/model that served the most recent successful call, e.g.
        # "gemini/gemini-2.5-flash". Callers read this to report which model
        # actually answered (after fallback), instead of the task name.
        self.last_used: str = ""
        # Running token total for every LLM call made through this router. A
        # router is created fresh per request, so this naturally scopes to one
        # query — contextualize + intent + generation all fold in here, giving
        # the true cost of producing the answer. Callers read it at the end.
        self.usage: TokenUsage = TokenUsage()
        self._providers: dict[str, LLMProvider] = {}
        self._init_providers()

    @staticmethod
    def _load_yaml_routes() -> dict[str, TaskRoute] | None:
        """Load routing config from config/providers.yaml.

        Returns None if the file is missing or malformed, so the caller
        falls back to DEFAULT_ROUTES.
        """
        from src.core.config import load_provider_config

        try:
            raw = load_provider_config()
            tasks = raw.get("tasks")
            if not tasks:
                return None

            routes: dict[str, TaskRoute] = {}
            for task_name, task_cfg in tasks.items():
                providers = task_cfg.get("providers", [])
                options = [
                    ProviderOption(
                        provider_name=p["provider"],
                        model=p["model"],
                        priority=p.get("priority", 0),
                    )
                    for p in providers
                ]
                routes[task_name] = TaskRoute(options)

            logger.info("Loaded %d task routes from providers.yaml", len(routes))
            return routes
        except Exception as e:
            logger.warning("Failed to parse providers.yaml: %s — using defaults", e)
            return None

    def _init_providers(self) -> None:
        """Initialize all provider instances."""
        if settings.gemini_api_key:
            self._providers["gemini"] = GeminiProvider(self._rate_limiter)

        if settings.nvidia_nim_api_key:
            self._providers["nvidia_nim"] = OpenAICompatibleProvider(
                name="nvidia_nim",
                base_url="https://integrate.api.nvidia.com/v1",
                api_key=settings.nvidia_nim_api_key,
                rate_limiter=self._rate_limiter,
            )

        if settings.groq_api_key:
            self._providers["groq"] = OpenAICompatibleProvider(
                name="groq",
                base_url="https://api.groq.com/openai/v1",
                api_key=settings.groq_api_key,
                rate_limiter=self._rate_limiter,
            )

        if settings.openrouter_api_key:
            self._providers["openrouter"] = OpenAICompatibleProvider(
                name="openrouter",
                base_url="https://openrouter.ai/api/v1",
                api_key=settings.openrouter_api_key,
                rate_limiter=self._rate_limiter,
            )

    def _get_route(self, task: str) -> TaskRoute:
        """Get the fallback chain for a task, falling back to general_qa.

        Applies the soft provider pin (if any) so the preferred provider is
        tried first while the rest of the chain remains as fallback.
        """
        base = self._routes.get(task, self._routes.get("general_qa", TaskRoute()))
        return self._apply_preference(base, task)

    def _apply_preference(self, route: TaskRoute, task: str) -> TaskRoute:
        """Promote the pinned provider to the front of a task's fallback chain.

        Soft-pin semantics:
          * If the pinned provider already appears in the route, its option(s)
            move to the front and everything else stays as fallback.
          * If it doesn't appear but is OpenRouter (an aggregator with no fixed
            per-task model), inject a configurable OpenRouter model — a vision
            model for vision tasks, a text model otherwise.
          * If it can't serve this task at all, leave the route untouched so the
            task still succeeds via its normal chain.
        """
        pref = self._preferred_provider
        if not pref:
            return route

        options = list(route.options)
        existing = [o for o in options if o.provider_name == pref]
        others = [o for o in options if o.provider_name != pref]

        if existing:
            promoted = existing
        elif pref == "openrouter":
            model = (
                settings.openrouter_vision_model
                if task in _VISION_TASKS
                else settings.openrouter_text_model
            )
            if not model:
                return route
            promoted = [ProviderOption("openrouter", model)]
        else:
            # Pinned provider has no model for this task — keep the original
            # chain rather than break the task.
            return route

        # Renumber so promoted options sort ahead of the fallback chain while
        # each group keeps its relative order.
        merged = [
            ProviderOption(opt.provider_name, opt.model, priority=i)
            for i, opt in enumerate(promoted + others)
        ]
        return TaskRoute(merged)

    async def chat(
        self,
        task: str,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        response_format: dict[str, str] | None = None,
    ) -> str:
        """Route a chat completion through the provider fallback chain."""
        route = self._get_route(task)
        errors: list[str] = []

        for option in sorted(route.options, key=lambda o: o.priority):
            provider = self._providers.get(option.provider_name)
            if provider is None or not provider.is_available:
                continue

            try:
                call_usage = TokenUsage()
                result = await provider.chat(
                    messages,
                    model=option.model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format=response_format,
                    usage=call_usage,
                )
                self.last_used = f"{option.provider_name}/{option.model}"
                self.usage.add_call(call_usage)
                logger.debug(
                    "Task '%s' completed via %s/%s", task, option.provider_name, option.model
                )
                return result
            except Exception as e:
                self._note_rate_limit(option.provider_name, e)
                error_msg = f"{option.provider_name}/{option.model}: {e}"
                errors.append(error_msg)
                logger.warning("Provider failed for task '%s': %s", task, error_msg)
                continue

        raise RuntimeError(
            f"All providers exhausted for task '{task}'. Errors: {'; '.join(errors)}"
        )

    def _note_rate_limit(self, provider_name: str, exc: Exception) -> None:
        """Record a provider cooldown when a call failed with HTTP 429.

        Without this, a provider that just returned 429 would be re-tried at the
        front of the chain on the *next* task in the same request — burning
        another doomed request (and free-tier quota) every time. Marking it
        rate-limited makes ``RateLimiter.acquire`` reject it for the backoff
        window, so the router falls straight through to the next provider.
        """
        retry_after = _rate_limit_retry_after(exc)
        if retry_after is not None:
            self._rate_limiter.report_429(provider_name, retry_after)

    async def chat_stream(
        self,
        task: str,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> AsyncGenerator[str, None]:
        """Route a chat completion stream through the provider fallback chain."""
        route = self._get_route(task)
        errors: list[str] = []

        for option in sorted(route.options, key=lambda o: o.priority):
            provider = self._providers.get(option.provider_name)
            if provider is None or not provider.is_available:
                continue

            emitted = False
            try:
                # We yield from the provider's generator
                call_usage = TokenUsage()
                async for chunk in provider.chat_stream(
                    messages,
                    model=option.model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    usage=call_usage,
                ):
                    emitted = True
                    yield chunk

                self.last_used = f"{option.provider_name}/{option.model}"
                self.usage.add_call(call_usage)
                logger.debug(
                    "Task stream '%s' completed via %s/%s", task, option.provider_name, option.model
                )
                return
            except Exception as e:
                self._note_rate_limit(option.provider_name, e)
                error_msg = f"{option.provider_name}/{option.model}: {e}"
                errors.append(error_msg)
                logger.warning("Provider stream failed for task '%s': %s", task, error_msg)
                # Once we've streamed partial text to the caller, falling back to
                # another provider would append a second, duplicate answer on top
                # of the first — garbled output. Fail hard instead; only fall
                # back when nothing has been emitted yet.
                if emitted:
                    logger.error(
                        "Stream for task '%s' failed after emitting output — not falling back to avoid duplication",
                        task,
                    )
                    raise
                continue

        raise RuntimeError(
            f"All providers exhausted for task '{task}'. Errors: {'; '.join(errors)}"
        )

    async def vision(
        self,
        task: str,
        image_data: bytes,
        prompt: str,
        *,
        mime_type: str = "image/png",
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> str:
        """Route a vision call through the provider fallback chain."""
        route = self._get_route(task)
        errors: list[str] = []

        for option in sorted(route.options, key=lambda o: o.priority):
            provider = self._providers.get(option.provider_name)
            if provider is None or not provider.is_available:
                continue

            try:
                result = await provider.vision(
                    image_data,
                    prompt,
                    model=option.model,
                    mime_type=mime_type,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                self.last_used = f"{option.provider_name}/{option.model}"
                logger.debug(
                    "Vision task '%s' completed via %s/%s",
                    task,
                    option.provider_name,
                    option.model,
                )
                return result
            except Exception as e:
                self._note_rate_limit(option.provider_name, e)
                error_msg = f"{option.provider_name}/{option.model}: {e}"
                errors.append(error_msg)
                logger.warning("Vision provider failed for task '%s': %s", task, error_msg)
                continue

        raise RuntimeError(
            f"All vision providers exhausted for task '{task}'. Errors: {'; '.join(errors)}"
        )
