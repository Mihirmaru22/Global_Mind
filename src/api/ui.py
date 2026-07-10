"""UI API Endpoints — connects the React frontend to the RAG backend."""

from __future__ import annotations

import datetime
import logging
import re
import uuid
import json
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.core.config import settings
from src.core.provider_client import ProviderRouter
from src.core.state import state_manager
from src.pipeline.query import QueryPipeline

logger = logging.getLogger(__name__)
router = APIRouter()


# Human-readable labels + display order for the provider picker. OpenRouter
# leads because it's the default soft pin.
_PROVIDER_LABELS = {
    "openrouter": "OpenRouter",
    "gemini": "Gemini",
    "groq": "Groq",
    "nvidia_nim": "NVIDIA NIM",
}
_PROVIDER_ORDER = ["openrouter", "gemini", "groq", "nvidia_nim"]


_TITLE_PROMPT = """You write short, clear titles for chat conversations.

Given the first exchange below, reply with a concise title of 3 to 6 words that
captures the main topic. Use Title Case. Do NOT use quotes, a trailing period,
or the word "chat". If there is no real topic (e.g. only a greeting), reply with
exactly: New Chat

Conversation:
{conversation}

Title:"""


def _clean_title(raw: str) -> str:
    """Normalize an LLM title response into a clean, bounded title string."""
    text = (raw or "").strip()
    if not text:
        return ""
    # Take the first non-empty line only.
    text = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    # Drop a leading "Title:" / "Chat title -" the model may echo back.
    text = re.sub(r"^(chat\s+)?title\s*[:\-]\s*", "", text, flags=re.IGNORECASE)
    # Strip surrounding quotes and trailing sentence punctuation.
    text = text.strip().strip("\"'“”‘’").strip()
    text = text.rstrip(".!?,;:").strip()
    if len(text) > 60:
        text = text[:57].rstrip() + "..."
    return text


def _fallback_title(prompt: str) -> str:
    """Deterministic fallback when LLM titling is unavailable: trim the prompt."""
    trimmed = (prompt or "").strip()
    if len(trimmed) <= 48:
        return trimmed or "New Chat"
    return trimmed[:45].rstrip() + "..."


def _resolve_provider(requested: str | None) -> str | None:
    """Resolve the effective soft-pin provider for a request.

    Precedence: explicit request value → saved UI setting → app default.
    Returns None (no pin, "auto" routing) when the resolved value is "auto".
    """
    candidate = requested
    if candidate is None:
        candidate = state_manager.get_settings().get("provider")
    if candidate is None:
        candidate = settings.default_provider

    normalized = (candidate or "").strip().lower()
    return normalized if normalized and normalized != "auto" else None


class ChatCreate(BaseModel):
    title: str = "New Chat"

class ChatUpdate(BaseModel):
    title: str

class SendMessage(BaseModel):
    message: str
    # Optional soft-pin provider ("auto", "openrouter", "gemini", ...). When
    # omitted, the saved setting or app default is used.
    provider: str | None = None

class MessageFeedback(BaseModel):
    # "up", "down", or None to clear the rating.
    feedback: str | None = None

class IngestionCard(BaseModel):
    """A persisted ingestion-progress card (the step-by-step upload trace)."""
    id: str
    fileName: str
    status: str
    steps: list[dict[str, Any]]
    summary: dict[str, Any] | None = None
    content: str = ""
    createdAt: str


@router.get("/overview")
async def get_overview() -> dict[str, Any]:
    """Overview stats for the UI dashboard."""
    # Check if providers are available
    provider_router = ProviderRouter()
    has_llm = any(p.is_available for p in provider_router._providers.values())
    
    return {
        "backendStatus": "online",
        "ollamaStatus": "inactive",  # We are using cloud providers
        "vectorStatus": "ready",
        "modelLabel": "Auto-routed via ProviderRouter" if has_llm else "No Providers Configured",
        "contextTokens": 8192,
        "privacyLabel": "Zero-Cost Free Tier API",
    }


@router.get("/chats")
async def get_chats() -> list[dict[str, Any]]:
    """List all chats."""
    return state_manager.get_chats()


@router.post("/chats")
async def create_chat(chat_data: ChatCreate) -> dict[str, Any]:
    """Create a new chat."""
    chat = {
        "id": f"chat-{uuid.uuid4().hex[:8]}",
        "title": chat_data.title,
        "updatedAt": datetime.datetime.now(datetime.UTC).isoformat(),
    }
    state_manager.create_chat(chat)
    return chat


@router.patch("/chats/{chat_id}")
async def update_chat(chat_id: str, chat_data: ChatUpdate) -> dict[str, Any]:
    """Rename a chat."""
    updated = state_manager.update_chat(chat_id, {"title": chat_data.title})
    if not updated:
        raise HTTPException(status_code=404, detail="Chat not found")
    return updated


@router.delete("/chats/{chat_id}")
async def delete_chat(chat_id: str) -> dict[str, str]:
    """Delete a chat."""
    state_manager.delete_chat(chat_id)
    return {"status": "success"}


@router.get("/chats/{chat_id}/messages")
async def get_messages(chat_id: str) -> list[dict[str, Any]]:
    """Get all messages for a chat."""
    return state_manager.get_messages(chat_id)


@router.post("/chats/{chat_id}/messages")
async def send_message(chat_id: str, msg: SendMessage) -> dict[str, Any]:
    """Send a message to a chat, process it via RAG, and return the response."""
    # Save the user's message
    user_message = {
        "id": f"msg-u-{uuid.uuid4().hex[:8]}",
        "role": "user",
        "content": msg.message,
        "createdAt": datetime.datetime.now(datetime.UTC).isoformat(),
        "chatId": chat_id,
    }
    state_manager.add_message(chat_id, user_message)

    try:
        # Fresh pipeline per request — avoids accumulated RateLimiter backoff
        # bleeding across unrelated queries and biasing provider selection.
        pipeline = QueryPipeline(preferred_provider=_resolve_provider(msg.provider))
        result = await pipeline.query(msg.message)


        # Save the assistant's message
        assistant_message = {
            "id": f"msg-a-{uuid.uuid4().hex[:8]}",
            "role": "assistant",
            "content": result.answer,
            "createdAt": datetime.datetime.now(datetime.UTC).isoformat(),
            "chatId": chat_id,
            "citations": [c.model_dump() for c in result.citations],
            "modelUsed": result.model_used,
        }
        state_manager.add_message(chat_id, assistant_message)
        
        # Update chat modified time
        state_manager.update_chat(chat_id, {"updatedAt": datetime.datetime.now(datetime.UTC).isoformat()})
        
        return assistant_message

    except Exception as e:
        logger.exception("Failed to process message")
        error_message = {
            "id": f"msg-e-{uuid.uuid4().hex[:8]}",
            "role": "assistant",
            "content": "Sorry, I wasn't able to process your request. Our AI providers may be temporarily unavailable — please try again in a moment.",
            "createdAt": datetime.datetime.now(datetime.UTC).isoformat(),
            "chatId": chat_id,
        }
        state_manager.add_message(chat_id, error_message)
        return error_message


@router.post("/chats/{chat_id}/messages/stream")
async def send_message_stream(chat_id: str, msg: SendMessage):
    """Send a message to a chat and stream the RAG response via SSE."""
    # Save the user's message
    user_message = {
        "id": f"msg-u-{uuid.uuid4().hex[:8]}",
        "role": "user",
        "content": msg.message,
        "createdAt": datetime.datetime.now(datetime.UTC).isoformat(),
        "chatId": chat_id,
    }
    state_manager.add_message(chat_id, user_message)

    pipeline = QueryPipeline(preferred_provider=_resolve_provider(msg.provider))

    async def event_generator():
        try:
            async for chunk in pipeline.query_stream(msg.message):
                if isinstance(chunk, str):
                    yield f"data: {json.dumps({'type': 'chunk', 'text': chunk})}\n\n"
                else:
                    # Final QueryResult
                    assistant_message = {
                        "id": f"msg-a-{uuid.uuid4().hex[:8]}",
                        "role": "assistant",
                        "content": chunk.answer,
                        "createdAt": datetime.datetime.now(datetime.UTC).isoformat(),
                        "chatId": chat_id,
                        "citations": [c.model_dump() for c in chunk.citations],
                        "modelUsed": chunk.model_used,
                    }
                    state_manager.add_message(chat_id, assistant_message)
                    state_manager.update_chat(chat_id, {"updatedAt": datetime.datetime.now(datetime.UTC).isoformat()})
                    
                    yield f"data: {json.dumps({'type': 'done', 'message': assistant_message})}\n\n"
        except Exception as e:
            logger.exception("Failed to process stream message")
            error_message = {
                "id": f"msg-e-{uuid.uuid4().hex[:8]}",
                "role": "assistant",
                "content": "Sorry, I wasn't able to process your request. Our AI providers may be temporarily unavailable.",
                "createdAt": datetime.datetime.now(datetime.UTC).isoformat(),
                "chatId": chat_id,
            }
            state_manager.add_message(chat_id, error_message)
            yield f"data: {json.dumps({'type': 'error', 'message': error_message})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/chats/{chat_id}/messages/ingestion")
async def persist_ingestion_card(chat_id: str, card: IngestionCard) -> dict[str, Any]:
    """Persist a finished ingestion-progress card so it survives a reload.

    The card streams live during upload (via /upload/stream); once ingestion
    finishes the frontend calls this to keep the step-by-step trace in the chat
    permanently, like a normal message.
    """
    message = {
        "id": card.id,
        "role": "assistant",
        "kind": "ingestion",
        "fileName": card.fileName,
        "status": card.status,
        "steps": card.steps,
        "summary": card.summary,
        "content": card.content,
        "createdAt": card.createdAt,
        "chatId": chat_id,
    }
    state_manager.add_message(chat_id, message)
    state_manager.update_chat(chat_id, {"updatedAt": datetime.datetime.now(datetime.UTC).isoformat()})
    return {"status": "ok"}


@router.post("/chats/{chat_id}/messages/{message_id}/feedback")
async def set_message_feedback(
    chat_id: str, message_id: str, body: MessageFeedback
) -> dict[str, Any]:
    """Persist a thumbs up/down rating on an assistant message.

    Stored in messages.json alongside the message, so it survives reloads and is
    inspectable server-side. ``feedback: null`` clears the rating.
    """
    if body.feedback not in (None, "up", "down"):
        raise HTTPException(status_code=400, detail="feedback must be 'up', 'down', or null")

    updated = state_manager.set_message_feedback(chat_id, message_id, body.feedback)
    if not updated:
        raise HTTPException(status_code=404, detail="Message not found")
    return {"status": "ok", "feedback": body.feedback}


@router.post("/chats/{chat_id}/title")
async def generate_chat_title(chat_id: str) -> dict[str, Any]:
    """Generate a concise, topic-aware title from a chat's first exchange.

    Uses a fast, cheap model (fast_support route) so it never adds meaningful
    latency. Persists the result and returns it. Falls back to a trimmed first
    message if the model is unavailable or returns nothing usable.
    """
    messages = state_manager.get_messages(chat_id)
    first_user = next((m for m in messages if m.get("role") == "user"), None)
    if not first_user or not (first_user.get("content") or "").strip():
        return {"title": None}

    first_assistant = next((m for m in messages if m.get("role") == "assistant"), None)

    conversation = f"User: {first_user['content'][:600]}"
    if first_assistant and (first_assistant.get("content") or "").strip():
        conversation += f"\nAssistant: {first_assistant['content'][:600]}"

    title = ""
    try:
        provider_router = ProviderRouter()
        raw = await provider_router.chat(
            "fast_support",
            messages=[{"role": "user", "content": _TITLE_PROMPT.format(conversation=conversation)}],
            temperature=0.3,
            max_tokens=20,
        )
        title = _clean_title(raw)
    except Exception:
        logger.warning("Title generation LLM call failed — falling back to trimmed prompt")

    if not title or title.lower() == "new chat":
        title = _fallback_title(first_user["content"])

    state_manager.update_chat(chat_id, {"title": title})
    return {"title": title}


@router.get("/documents")
async def get_documents() -> list[dict[str, Any]]:
    """List all ingested documents.

    Reads from the ingestion registry (ingested_files.json) — the single
    source of truth that the ingestion pipeline actually populates. The
    previous implementation read documents.json, which nothing ever wrote
    to, so this endpoint always returned an empty list.
    """
    from src.core.ingestion_registry import IngestionRegistry

    registry = IngestionRegistry()
    entries = registry.get_all().values()

    documents: list[dict[str, Any]] = []
    for entry in entries:
        documents.append(
            {
                "id": entry.get("document_id", ""),
                "name": entry.get("file_name", "Unknown"),
                "sizeBytes": entry.get("file_size_bytes", 0),
                "chunks": entry.get("total_chunks", 0),
                "ingestedAt": entry.get("ingested_at", ""),
            }
        )

    # Newest first
    documents.sort(key=lambda d: d.get("ingestedAt", ""), reverse=True)
    return documents


@router.get("/providers")
async def get_providers() -> dict[str, Any]:
    """List selectable model providers for the settings picker.

    Only providers with a configured API key are offered, plus an always-present
    "Auto" option. OpenRouter leads the list and is the default soft pin; if it
    isn't configured, the effective default degrades to "auto".
    """
    provider_router = ProviderRouter()
    available = {
        name for name, provider in provider_router._providers.items() if provider.is_available
    }
    ordered = [n for n in _PROVIDER_ORDER if n in available] + [
        n for n in sorted(available) if n not in _PROVIDER_ORDER
    ]

    options = [{"id": "auto", "label": "Auto (recommended)"}]
    options += [{"id": n, "label": _PROVIDER_LABELS.get(n, n)} for n in ordered]

    default = (settings.default_provider or "auto").strip().lower()
    if default != "auto" and default not in available:
        default = "auto"

    return {"providers": options, "default": default}


@router.get("/settings")
async def get_settings() -> dict[str, Any]:
    """Get UI settings."""
    return state_manager.get_settings()


@router.post("/settings")
async def save_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """Save UI settings."""
    return state_manager.save_settings(settings)
