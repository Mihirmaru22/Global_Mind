"""SSE notifications for app-level events."""

from __future__ import annotations

import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from src.services.upload_directory_notifications import directory_notifications

router = APIRouter()


@router.get("/events/stream")
async def stream_events() -> StreamingResponse:
    """Stream app notifications to the frontend."""

    async def event_generator():
        queue, snapshot = await directory_notifications.subscribe()
        try:
            if snapshot is not None:
                yield f"data: {json.dumps(snapshot, ensure_ascii=False)}\n\n"

            while True:
                event = await queue.get()
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            await directory_notifications.unsubscribe(queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

