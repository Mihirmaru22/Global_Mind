"""In-memory SSE notifications for uploads directory state changes."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any


def _empty_directory_event(path: str) -> dict[str, Any]:
    return {
        "type": "NO_DOCUMENTS_IN_DIRECTORY",
        "message": "No documents found in the uploads directory.",
        "path": path,
    }


def _restored_directory_event() -> dict[str, Any]:
    return {"type": "DOCUMENTS_RESTORED"}


class UploadDirectoryNotificationHub:
    """Fan out directory-state notifications to SSE subscribers."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._lock = asyncio.Lock()
        self._is_empty: bool | None = None
        self._directory_path = ""
        self._file_count = 0

    @property
    def is_empty(self) -> bool | None:
        return self._is_empty

    def current_snapshot(self) -> dict[str, Any] | None:
        if self._is_empty:
            return _empty_directory_event(self._directory_path)
        return None

    async def subscribe(self) -> tuple[asyncio.Queue[dict[str, Any]], dict[str, Any] | None]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        async with self._lock:
            self._subscribers.add(queue)
            snapshot = self.current_snapshot()
        return queue, snapshot

    async def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        async with self._lock:
            self._subscribers.discard(queue)

    async def update_state(
        self,
        *,
        is_empty: bool,
        path: str | Path,
        file_count: int,
    ) -> None:
        previous = self._is_empty
        self._is_empty = is_empty
        self._directory_path = str(path)
        self._file_count = file_count

        should_broadcast = previous is not None and previous != is_empty
        if previous is None and is_empty:
            should_broadcast = True

        if not should_broadcast:
            return

        event = _empty_directory_event(self._directory_path) if is_empty else _restored_directory_event()
        async with self._lock:
            subscribers = tuple(self._subscribers)
        for queue in subscribers:
            queue.put_nowait(event)


directory_notifications = UploadDirectoryNotificationHub()
