"""Watchdog-based upload directory monitor."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from src.core.config import PROJECT_ROOT, settings
from src.services.ingestion_service import start_ingestion
from src.services.upload_directory_notifications import directory_notifications
from src.services.upload_directory_status import (
    count_supported_upload_files,
    is_supported_upload_file,
)

logger = logging.getLogger(__name__)


class _DocumentEventHandler(FileSystemEventHandler):
    def __init__(self, watcher: "DocumentWatcher") -> None:
        self._watcher = watcher

    def on_created(self, event: FileSystemEvent) -> None:
        self._watcher.handle_event(event)
        self._watcher.schedule_directory_refresh()

    def on_deleted(self, event: FileSystemEvent) -> None:
        self._watcher.handle_removed_event(event)

    def on_moved(self, event: FileSystemEvent) -> None:
        self._watcher.handle_event(event)
        self._watcher.handle_removed_event(event)
        self._watcher.schedule_directory_refresh()


class DocumentWatcher:
    """Monitor the uploads folder and trigger ingestion when files stabilize."""

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        enabled: bool = True,
        stable_seconds: float = 1.0,
        poll_interval: float = 0.5,
        settle_timeout: float = 60.0,
        retry_delay: float | None = None,
        max_retry_attempts: int = 3,
    ) -> None:
        self._path = Path(path or settings.upload_dir)
        self._enabled = enabled
        self._stable_seconds = stable_seconds
        self._poll_interval = poll_interval
        self._settle_timeout = settle_timeout
        self._retry_delay = (
            retry_delay if retry_delay is not None else max(stable_seconds, poll_interval)
        )
        self._max_retry_attempts = max_retry_attempts
        self._observer = Observer()
        self._handler = _DocumentEventHandler(self)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._in_flight: set[str] = set()
        self._lock = threading.Lock()
        self._started = False
        self._directory_has_supported_files: bool | None = None

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        if not self._enabled:
            logger.info("Document watcher disabled")
            return
        if self._started:
            return

        self._loop = loop
        self._path.mkdir(parents=True, exist_ok=True)
        self._observer.schedule(self._handler, str(self._path), recursive=False)
        self._observer.start()
        self._started = True
        logger.info("Document watcher started for %s", self._path)

    async def stop(self) -> None:
        if not self._started:
            return

        logger.info("Stopping document watcher")
        self._observer.stop()
        await asyncio.to_thread(self._observer.join, 5)
        self._started = False

    def schedule_directory_refresh(self) -> None:
        if self._loop is None:
            logger.warning("Watcher has no event loop; skipping directory refresh")
            return
        asyncio.run_coroutine_threadsafe(self.refresh_directory_state(), self._loop)

    def handle_removed_event(self, event: FileSystemEvent) -> None:
        if getattr(event, "is_directory", False):
            return

        raw_path = getattr(event, "src_path", None)
        if not raw_path:
            return

        path = Path(raw_path)
        if path.parent.resolve() != self._path.resolve():
            return

        logger.info("Watcher saw removal event for: %s", path.name)
        self.schedule_directory_refresh()

    def handle_event(self, event: FileSystemEvent) -> None:
        if getattr(event, "is_directory", False):
            return

        raw_path = getattr(event, "dest_path", None) or getattr(event, "src_path", None)
        if not raw_path:
            return

        path = Path(raw_path)
        if path.parent.resolve() != self._path.resolve():
            return

        if not is_supported_upload_file(path):
            logger.info("Watcher skipped unsupported file: %s", path.name)
            return

        key = str(path.resolve())
        with self._lock:
            if key in self._in_flight:
                return
            self._in_flight.add(key)

        logger.info("Watcher detected candidate file: %s", path.name)

        if self._loop is None:
            logger.warning("Watcher has no event loop; dropping '%s'", path.name)
            with self._lock:
                self._in_flight.discard(key)
            return

        asyncio.run_coroutine_threadsafe(self._process_path(path, key), self._loop)

    async def refresh_directory_state(self) -> bool:
        try:
            file_count = count_supported_upload_files(self._path)
        except Exception:
            logger.exception("Failed to inspect uploads directory at %s", self._path)
            return bool(self._directory_has_supported_files)

        has_files = file_count > 0
        previous = self._directory_has_supported_files
        self._directory_has_supported_files = has_files

        if previous is None:
            if has_files:
                logger.info(
                    "Startup upload directory check found %d supported file(s) in %s",
                    file_count,
                    self._path,
                )
            else:
                logger.info("Startup upload directory check found no supported files in %s", self._path)
        elif previous != has_files:
            if has_files:
                logger.info(
                    "Upload directory restored with %d supported file(s) in %s",
                    file_count,
                    self._path,
                )
            else:
                logger.info("Upload directory became empty: %s", self._path)
        else:
            logger.debug(
                "Upload directory state unchanged (%d supported file(s) in %s)",
                file_count,
                self._path,
            )

        try:
            await directory_notifications.update_state(
                is_empty=not has_files,
                path=self._notification_path_label(),
                file_count=file_count,
            )
        except Exception:
            logger.exception("Failed to publish uploads directory state for %s", self._path)

        return has_files

    async def _process_path(self, path: Path, key: str) -> None:
        try:
            for attempt in range(1, self._max_retry_attempts + 1):
                if await self._wait_for_stable_file(path):
                    break

                if attempt >= self._max_retry_attempts:
                    logger.info("Watcher skipped unstable file: %s", path.name)
                    return

                logger.info(
                    "Watcher re-checking unstable file: %s (attempt %d/%d)",
                    path.name,
                    attempt + 1,
                    self._max_retry_attempts,
                )
                await asyncio.sleep(self._retry_delay)

            if not path.exists():
                logger.info("Watcher skipped missing file: %s", path.name)
                return

            logger.info("Watcher triggering ingestion for stable file: %s", path.name)
            await start_ingestion(path)
        except Exception:
            logger.exception("Watcher ingestion failed for '%s'", path.name)
        finally:
            with self._lock:
                self._in_flight.discard(key)

    async def _wait_for_stable_file(self, path: Path) -> bool:
        last_size = None
        stable_since = time.monotonic()
        deadline = stable_since + self._settle_timeout

        while time.monotonic() < deadline:
            try:
                size = path.stat().st_size
            except FileNotFoundError:
                return False
            except OSError:
                await asyncio.sleep(self._poll_interval)
                continue

            now = time.monotonic()
            if last_size == size:
                if now - stable_since >= self._stable_seconds:
                    return True
            else:
                last_size = size
                stable_since = now
            await asyncio.sleep(self._poll_interval)

        return False

    def _notification_path_label(self) -> str:
        try:
            return str(self._path.resolve().relative_to(PROJECT_ROOT.resolve()))
        except Exception:
            return str(self._path)
