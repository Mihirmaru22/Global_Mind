"""UI API Endpoints — connects the React frontend to the RAG backend."""

from __future__ import annotations

import datetime
import logging
import uuid
import json
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.core.provider_client import ProviderRouter
from src.core.state import state_manager
from src.pipeline.query import QueryPipeline

logger = logging.getLogger(__name__)
router = APIRouter()


class ChatCreate(BaseModel):
    title: str = "New Chat"

class ChatUpdate(BaseModel):
    title: str

class SendMessage(BaseModel):
    message: str


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
        pipeline = QueryPipeline()
        result = await pipeline.query(msg.message)

        
        # Save the assistant's message
        assistant_message = {
            "id": f"msg-a-{uuid.uuid4().hex[:8]}",
            "role": "assistant",
            "content": result.answer,
            "createdAt": datetime.datetime.now(datetime.UTC).isoformat(),
            "chatId": chat_id,
            "citations": [c.model_dump() for c in result.citations],
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

    pipeline = QueryPipeline()
    
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


@router.get("/documents")
async def get_documents() -> list[dict[str, Any]]:
    """List all ingested documents."""
    return state_manager.get_documents()


@router.get("/settings")
async def get_settings() -> dict[str, Any]:
    """Get UI settings."""
    return state_manager.get_settings()


@router.post("/settings")
async def save_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """Save UI settings."""
    return state_manager.save_settings(settings)
