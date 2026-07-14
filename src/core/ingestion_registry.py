"""Ingestion Registry — SHA-256-based document deduplication.

Tracks all ingested documents in data/ingested_files.json.
On re-upload:
  - Same file (same hash) → skip entirely (no wasted API calls)
  - Modified file (same name, different hash) → delete old Qdrant vectors + re-ingest
  - New file → normal ingestion
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from src.core.file_lock import LockMode, locked

from src.core.config import DATA_DIR

logger = logging.getLogger(__name__)

_REGISTRY_FILE = DATA_DIR / "ingested_files.json"
_BUFFER_SIZE = 65536  # 64 KB chunks for streaming hash


class RegistryStatus(str, Enum):
    """Result of checking a file against the registry."""
    NEW_FILE = "new_file"
    ALREADY_INGESTED = "already_ingested"
    CONTENT_CHANGED = "content_changed"


@dataclass
class RegistryCheckResult:
    """Result of a registry check with full context."""
    status: RegistryStatus
    sha256: str
    old_document_id: str | None = None  # Set if CONTENT_CHANGED
    old_entry: dict[str, Any] | None = None


class IngestionRegistry:
    """Manages a JSON-based registry of ingested files keyed by SHA-256 hash.

    Thread-safe via cross-platform advisory file locking (same pattern as state.py).
    """

    def __init__(self, registry_path: Path = _REGISTRY_FILE) -> None:
        self._path = registry_path
        # Ensure parent directory exists
        self._path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(self, file_path: str | Path) -> RegistryCheckResult:
        """Compute SHA-256 and check the registry.

        Returns a RegistryCheckResult describing whether this is new,
        already ingested, or a changed version of an existing document.
        """
        path = Path(file_path)
        file_hash = self._sha256(path)
        registry = self._load()

        # Case 1: Exact hash match — already ingested, nothing to do
        if file_hash in registry:
            entry = registry[file_hash]
            logger.info(
                "Registry: '%s' already ingested (hash=%s..., doc_id=%s)",
                path.name,
                file_hash[:12],
                entry.get("document_id", "?"),
            )
            return RegistryCheckResult(
                status=RegistryStatus.ALREADY_INGESTED,
                sha256=file_hash,
                old_entry=entry,
            )

        # Case 2: Same filename, different hash — file content changed
        file_name = path.name
        old_hash = self._find_by_filename(registry, file_name)
        if old_hash:
            old_entry = registry[old_hash]
            logger.info(
                "Registry: '%s' content changed (old hash=%s..., new hash=%s...)",
                file_name,
                old_hash[:12],
                file_hash[:12],
            )
            return RegistryCheckResult(
                status=RegistryStatus.CONTENT_CHANGED,
                sha256=file_hash,
                old_document_id=old_entry.get("document_id"),
                old_entry=old_entry,
            )

        # Case 3: Brand new file
        logger.info("Registry: '%s' is new (hash=%s...)", path.name, file_hash[:12])
        return RegistryCheckResult(
            status=RegistryStatus.NEW_FILE,
            sha256=file_hash,
        )

    def register(
        self,
        file_path: str | Path,
        document_id: str,
        total_chunks: int,
        sha256: str | None = None,
    ) -> None:
        """Record a successfully ingested document in the registry."""
        import datetime

        path = Path(file_path)
        file_hash = sha256 or self._sha256(path)
        registry = self._load()

        # Remove any old entries with the same filename (handles content changes)
        old_hash = self._find_by_filename(registry, path.name)
        if old_hash and old_hash != file_hash:
            del registry[old_hash]
            logger.debug("Registry: removed old entry for '%s'", path.name)

        registry[file_hash] = {
            "document_id": document_id,
            "file_name": path.name,
            "file_path": str(path),
            "file_size_bytes": path.stat().st_size if path.exists() else 0,
            "total_chunks": total_chunks,
            "ingested_at": datetime.datetime.now(datetime.UTC).isoformat(),
        }

        self._save(registry)
        logger.info(
            "Registry: registered '%s' (doc_id=%s, chunks=%d)",
            path.name,
            document_id,
            total_chunks,
        )

    def unregister(self, document_id: str) -> bool:
        """Remove a document from the registry by its document_id.

        Returns True if found and removed, False if not found.
        """
        registry = self._load()
        to_delete = [h for h, e in registry.items() if e.get("document_id") == document_id]
        if not to_delete:
            return False
        for h in to_delete:
            del registry[h]
        self._save(registry)
        logger.info("Registry: unregistered doc_id=%s", document_id)
        return True

    def get_all(self) -> dict[str, Any]:
        """Return the entire registry (sha256 → entry dict)."""
        return self._load()

    def get_by_document_id(self, document_id: str) -> dict[str, Any] | None:
        """Look up a registry entry by document ID."""
        registry = self._load()
        for entry in registry.values():
            if entry.get("document_id") == document_id:
                return entry
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _sha256(path: Path) -> str:
        """Compute SHA-256 hash of file contents in streaming fashion."""
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while True:
                block = f.read(_BUFFER_SIZE)
                if not block:
                    break
                h.update(block)
        return h.hexdigest()

    @staticmethod
    def _find_by_filename(registry: dict, file_name: str) -> str | None:
        """Find the SHA-256 hash key for an entry matching a given filename."""
        for sha, entry in registry.items():
            if entry.get("file_name") == file_name:
                return sha
        return None

    def _load(self) -> dict[str, Any]:
        """Load registry from disk with shared (read) lock."""
        if not self._path.exists():
            return {}
        try:
            with open(self._path, encoding="utf-8") as f:
                with locked(f, LockMode.SHARED):
                    data = json.load(f)
        except json.JSONDecodeError as e:
            logger.warning(
                "Registry: invalid JSON in %s; resetting to empty registry: %s",
                self._path,
                e,
            )
            self._save({})
            return {}
        except FileNotFoundError:
            return {}
        except Exception as e:
            logger.error("Registry: failed to load %s: %s", self._path, e)
            return {}
        if not isinstance(data, dict):
            logger.warning(
                "Registry: expected JSON object in %s but got %s; resetting to empty registry",
                self._path,
                type(data).__name__,
            )
            self._save({})
            return {}
        return data

    def _save(self, data: dict[str, Any]) -> None:
        """Atomically write registry to disk with exclusive (write) lock."""
        try:
            content = json.dumps(data, indent=2, ensure_ascii=False)
            fd, tmp_path = tempfile.mkstemp(
                dir=str(self._path.parent), suffix=".tmp", prefix="registry"
            )
            try:
                with open(fd, "w", encoding="utf-8") as f:
                    with locked(f, LockMode.EXCLUSIVE):
                        f.write(content)
                        f.flush()
                # Atomic on POSIX and Windows (unlike Path.rename on Windows).
                os.replace(tmp_path, self._path)
            except Exception:
                Path(tmp_path).unlink(missing_ok=True)
                raise
        except Exception as e:
            logger.error("Registry: failed to save: %s", e)
