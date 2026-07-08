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

logger = logging.getLogger(__name__)


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
    ) -> str: ...

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        temperature: float = 0.0,
        max_tokens: int = 4096,
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
        if self._client is None:
            self._client = AsyncOpenAI(
                base_url=self._base_url,
                api_key=self._api_key,
                timeout=60.0
            )
        return self._client

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        response_format: dict[str, str] | None = None,
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
        return response.choices[0].message.content or ""

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> AsyncGenerator[str, None]:
        await self._rate_limiter.acquire(self._name)
        client = self._get_client()
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True
        )
        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

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
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=120.0)
        return self._http

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        response_format: dict[str, str] | None = None,
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

        return self._extract_gemini_text(data)

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        temperature: float = 0.0,
        max_tokens: int = 4096,
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

    def __init__(self, routes: dict[str, TaskRoute] | None = None) -> None:
        self._rate_limiter = RateLimiter()
        self._routes = routes or self._load_yaml_routes() or DEFAULT_ROUTES
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
        """Get the fallback chain for a task, falling back to general_qa."""
        return self._routes.get(task, self._routes.get("general_qa", TaskRoute()))

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
                result = await provider.chat(
                    messages,
                    model=option.model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format=response_format,
                )
                logger.debug(
                    "Task '%s' completed via %s/%s", task, option.provider_name, option.model
                )
                return result
            except Exception as e:
                error_msg = f"{option.provider_name}/{option.model}: {e}"
                errors.append(error_msg)
                logger.warning("Provider failed for task '%s': %s", task, error_msg)
                continue

        raise RuntimeError(
            f"All providers exhausted for task '{task}'. Errors: {'; '.join(errors)}"
        )

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

            try:
                # We yield from the provider's generator
                async for chunk in provider.chat_stream(
                    messages,
                    model=option.model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                ):
                    yield chunk
                
                logger.debug(
                    "Task stream '%s' completed via %s/%s", task, option.provider_name, option.model
                )
                return
            except Exception as e:
                error_msg = f"{option.provider_name}/{option.model}: {e}"
                errors.append(error_msg)
                logger.warning("Provider stream failed for task '%s': %s", task, error_msg)
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
                logger.debug(
                    "Vision task '%s' completed via %s/%s",
                    task,
                    option.provider_name,
                    option.model,
                )
                return result
            except Exception as e:
                error_msg = f"{option.provider_name}/{option.model}: {e}"
                errors.append(error_msg)
                logger.warning("Vision provider failed for task '%s': %s", task, error_msg)
                continue

        raise RuntimeError(
            f"All vision providers exhausted for task '{task}'. Errors: {'; '.join(errors)}"
        )
