"""Ingestion Registry — content-addressed identity with document lineage.

Every ingested document has a stable identity and a place in a *lineage* — a
chain of versions that share the same logical document but differ in content
over time. This gives us three guarantees at once:

  1. **Deduplication.** Identity is the SHA-256 of the file's *content*, never
     its name. Re-uploading identical bytes (any filename) is a no-op.

  2. **No data loss.** Two different files that happen to share a name (two
     people's ``resume.pdf``) are two independent documents; both are kept.

  3. **Safe replacement / versioning.** "Replace document X with this new file"
     is an explicit operation that creates a *new version* and supersedes the
     old one. The cutover is ordered so the old version stays live until the new
     one is fully indexed:

         index new content → create new (active) version → supersede old version

     A failure anywhere before the supersede leaves the old version fully
     active. There is never a window with zero active versions — the failure
     mode where "an embedding error leaves the document with no active version"
     is structurally impossible.

Storage schema (``data/ingested_files.json``), keyed by ``document_id`` (UUID):

    {
      "<document_id>": {
        "document_id":     "<uuid>",       # stable identity of THIS version
        "content_hash":    "<sha256>",     # content fingerprint / dedup key
        "filename":        "resume.pdf",   # display label only
        "file_path":       "/uploads/ab/resume.pdf",
        "file_size_bytes": 12345,
        "total_chunks":    42,
        "created_at":      "2026-07-13T…",
        "supersedes":      "<uuid|null>",  # the version this one replaced
        "superseded_by":   "<uuid|null>",  # the version that replaced this one
        "active":          true,           # is this the current live version?
        "lineage_root":    "<uuid>"        # first version in this lineage
      },
      ...
    }

Registries written by the previous (sha256-keyed) schema are migrated
transparently on first load.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
import tempfile
import uuid
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
    CONTENT_CHANGED = "content_changed"  # retained for API compatibility; unused


@dataclass
class RegistryCheckResult:
    """Result of a registry check with full context."""
    status: RegistryStatus
    sha256: str
    old_document_id: str | None = None
    old_entry: dict[str, Any] | None = None

    @property
    def content_hash(self) -> str:
        """Alias for ``sha256`` under the lineage vocabulary."""
        return self.sha256


def _new_document_id() -> str:
    """Mint a fresh, globally-unique document identity."""
    return str(uuid.uuid4())


def _utcnow_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


class IngestionRegistry:
    """JSON-backed registry of ingested documents with lineage/versioning.

    Keyed by ``document_id`` (UUID). Thread-safe via cross-platform advisory
    file locking (same pattern as state.py). All mutating operations are a
    read-modify-write under an exclusive lock, so a version cutover
    (``create_version`` + ``supersede``) is durably ordered on disk.
    """

    def __init__(self, registry_path: Path = _REGISTRY_FILE) -> None:
        self._path = registry_path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Deduplication check
    # ------------------------------------------------------------------

    def check(self, file_path: str | Path) -> RegistryCheckResult:
        """Compute the content SHA-256 and check for an active duplicate.

        Identity is content-based. An exact content match against an **active**
        version is a duplicate to skip. Anything else — brand-new content, or
        content whose only match is a superseded (inactive) version — is treated
        as a new, distinct document. Filename never decides identity.
        """
        path = Path(file_path)
        file_hash = self._sha256(path)
        registry = self._load()

        active_dupe = self._find_active_by_hash(registry, file_hash)
        if active_dupe is not None:
            entry = registry[active_dupe]
            logger.info(
                "Registry: '%s' already ingested (hash=%s..., doc_id=%s)",
                path.name,
                file_hash[:12],
                active_dupe,
            )
            return RegistryCheckResult(
                status=RegistryStatus.ALREADY_INGESTED,
                sha256=file_hash,
                old_document_id=active_dupe,
                old_entry=entry,
            )

        same_name = self._find_active_by_filename(registry, path.name)
        if same_name is not None:
            logger.info(
                "Registry: '%s' is new content under an existing name — "
                "adding as a separate document",
                path.name,
            )
        else:
            logger.info("Registry: '%s' is new (hash=%s...)", path.name, file_hash[:12])
        return RegistryCheckResult(status=RegistryStatus.NEW_FILE, sha256=file_hash)

    # ------------------------------------------------------------------
    # Version lifecycle
    # ------------------------------------------------------------------

    def create_version(
        self,
        file_path: str | Path,
        content_hash: str,
        total_chunks: int,
        document_id: str | None = None,
        supersedes: str | None = None,
    ) -> dict[str, Any]:
        """Record a freshly-indexed document as a new **active** version.

        This is step 1 of the atomic cutover and is always called *after* the
        content has been fully embedded and stored. It does not touch the
        version being replaced — call :meth:`supersede` for that, immediately
        after, to flip the old version inactive.

        If ``supersedes`` names an existing version, the new version inherits
        that version's ``lineage_root`` (it joins the same lineage). Otherwise
        it starts a new lineage rooted at itself.

        Returns the stored entry.
        """
        path = Path(file_path)
        registry = self._load()

        doc_id = document_id or _new_document_id()
        lineage_root = doc_id
        if supersedes:
            prior = registry.get(supersedes)
            if prior is not None:
                lineage_root = prior.get("lineage_root", supersedes)
            else:
                logger.warning(
                    "Registry: create_version supersedes unknown doc_id=%s "
                    "— starting a fresh lineage",
                    supersedes,
                )
                supersedes = None

        entry = {
            "document_id": doc_id,
            "content_hash": content_hash,
            "filename": path.name,
            "file_path": str(path),
            "file_size_bytes": path.stat().st_size if path.exists() else 0,
            "total_chunks": total_chunks,
            "created_at": _utcnow_iso(),
            "supersedes": supersedes,
            "superseded_by": None,
            "active": True,
            "lineage_root": lineage_root,
        }
        registry[doc_id] = entry
        self._save(registry)
        logger.info(
            "Registry: created version doc_id=%s (chunks=%d, supersedes=%s, root=%s)",
            doc_id,
            total_chunks,
            supersedes,
            lineage_root,
        )
        return entry

    def supersede(self, old_document_id: str, new_document_id: str) -> bool:
        """Flip the old version inactive — step 2 (final) of the cutover.

        Atomically marks ``old_document_id`` inactive and links the two
        versions (``old.superseded_by = new``, ``new.supersedes = old``, and the
        new version adopts the old lineage root). Because it is a single
        read-modify-write under an exclusive lock, retrieval never observes a
        half-applied cutover.

        Returns True if the old version existed and was updated.
        """
        registry = self._load()
        old = registry.get(old_document_id)
        new = registry.get(new_document_id)
        if old is None:
            logger.warning("Registry: supersede — unknown old doc_id=%s", old_document_id)
            return False
        if new is None:
            logger.warning("Registry: supersede — unknown new doc_id=%s", new_document_id)
            return False

        old["active"] = False
        old["superseded_by"] = new_document_id
        new["supersedes"] = old_document_id
        new["lineage_root"] = old.get("lineage_root", old_document_id)
        registry[old_document_id] = old
        registry[new_document_id] = new
        self._save(registry)
        logger.info(
            "Registry: superseded doc_id=%s → %s (lineage=%s)",
            old_document_id,
            new_document_id,
            new["lineage_root"],
        )
        return True

    def register(
        self,
        file_path: str | Path,
        document_id: str,
        total_chunks: int,
        sha256: str | None = None,
    ) -> dict[str, Any]:
        """Register a newly-ingested document (no replacement).

        Convenience wrapper over :meth:`create_version` for the common
        "brand-new document" path, preserving the historical signature used by
        the ingestion pipeline. The pipeline passes the ``document_id`` derived
        from the chunks so registry identity matches the vector-store payloads.
        """
        path = Path(file_path)
        content_hash = sha256 or self._sha256(path)
        return self.create_version(
            file_path=path,
            content_hash=content_hash,
            total_chunks=total_chunks,
            document_id=document_id,
            supersedes=None,
        )

    def unregister(self, document_id: str) -> bool:
        """Remove a document version from the registry by its document_id.

        If the removed version was superseding another (i.e. some older version
        points to it via ``superseded_by``), that back-link is cleared so the
        older version isn't left dangling. Returns True if found and removed.
        """
        registry = self._load()
        if document_id not in registry:
            return False
        del registry[document_id]
        for entry in registry.values():
            if entry.get("superseded_by") == document_id:
                entry["superseded_by"] = None
                entry["active"] = True  # its replacement is gone — reactivate
            if entry.get("supersedes") == document_id:
                entry["supersedes"] = None
        self._save(registry)
        logger.info("Registry: unregistered doc_id=%s", document_id)
        return True

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_all(self) -> dict[str, Any]:
        """Return the entire registry (document_id → entry dict)."""
        return self._load()

    def get_by_document_id(self, document_id: str) -> dict[str, Any] | None:
        """Look up a single version by its document_id."""
        return self._load().get(document_id)

    def get_active(self) -> list[dict[str, Any]]:
        """Return all currently-active document versions."""
        return [e for e in self._load().values() if e.get("active", True)]

    def get_active_ids(self) -> set[str]:
        """Return the set of active document_ids (for retrieval filtering)."""
        return {
            e["document_id"]
            for e in self._load().values()
            if e.get("active", True) and e.get("document_id")
        }

    def get_superseded_ids(self) -> set[str]:
        """Return the set of inactive (superseded) document_ids.

        Retrieval prefers filtering *out* this typically-small set over
        enumerating every active id.
        """
        return {
            e["document_id"]
            for e in self._load().values()
            if not e.get("active", True) and e.get("document_id")
        }

    def get_versions(self, lineage_root: str) -> list[dict[str, Any]]:
        """Return every version in a lineage, oldest first."""
        versions = [
            e for e in self._load().values() if e.get("lineage_root") == lineage_root
        ]
        return sorted(versions, key=lambda e: e.get("created_at", ""))

    def find_active_by_filename(self, filename: str) -> dict[str, Any] | None:
        """Return the active version whose display name matches, if any.

        Used by the replace flow to resolve "replace the document called X".
        Ambiguous when two active documents share a name; returns the most
        recently created match in that case.
        """
        matches = [
            e
            for e in self._load().values()
            if e.get("active", True) and e.get("filename") == filename
        ]
        if not matches:
            return None
        return max(matches, key=lambda e: e.get("created_at", ""))

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
    def _find_active_by_hash(registry: dict, content_hash: str) -> str | None:
        """Return the document_id of an active entry with this content hash."""
        for doc_id, entry in registry.items():
            if entry.get("content_hash") == content_hash and entry.get("active", True):
                return doc_id
        return None

    @staticmethod
    def _find_active_by_filename(registry: dict, filename: str) -> str | None:
        """Return the document_id of an active entry with this filename."""
        for doc_id, entry in registry.items():
            if entry.get("filename") == filename and entry.get("active", True):
                return doc_id
        return None

    # ---- persistence -------------------------------------------------

    def _load(self) -> dict[str, Any]:
        """Load registry from disk with a shared (read) lock, migrating if needed."""
        if not self._path.exists():
            return {}
        try:
            with open(self._path, encoding="utf-8") as f:
                with locked(f, LockMode.SHARED):
                    raw = json.load(f)
        except Exception as e:
            logger.error("Registry: failed to load %s: %s", self._path, e)
            return {}

        migrated, changed = self._migrate(raw)
        if changed:
            # Persist the upgraded schema so we only migrate once.
            self._save(migrated)
        return migrated

    @staticmethod
    def _migrate(raw: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Upgrade a legacy (sha256-keyed) registry to the lineage schema.

        Legacy entries look like::

            {"<sha256>": {"document_id", "file_name", "file_path",
                          "file_size_bytes", "total_chunks", "ingested_at"}}

        Detection: legacy entries lack a ``content_hash`` field. Each becomes a
        standalone active lineage rooted at itself. Idempotent.
        """
        if not raw:
            return {}, False
        # Already lineage schema? (every entry has content_hash)
        if all("content_hash" in e for e in raw.values() if isinstance(e, dict)):
            return raw, False

        upgraded: dict[str, Any] = {}
        for key, entry in raw.items():
            if not isinstance(entry, dict):
                continue
            if "content_hash" in entry:
                # Already-new entry mixed in — keep as-is, key by its doc_id.
                doc_id = entry.get("document_id") or _new_document_id()
                upgraded[doc_id] = entry
                continue
            doc_id = entry.get("document_id") or _new_document_id()
            upgraded[doc_id] = {
                "document_id": doc_id,
                "content_hash": key,  # legacy key WAS the sha256
                "filename": entry.get("file_name", ""),
                "file_path": entry.get("file_path", ""),
                "file_size_bytes": entry.get("file_size_bytes", 0),
                "total_chunks": entry.get("total_chunks", 0),
                "created_at": entry.get("ingested_at", _utcnow_iso()),
                "supersedes": None,
                "superseded_by": None,
                "active": True,
                "lineage_root": doc_id,
            }
        logger.info("Registry: migrated %d legacy entries to lineage schema", len(upgraded))
        return upgraded, True

    def _save(self, data: dict[str, Any]) -> None:
        """Atomically write registry to disk with an exclusive (write) lock."""
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
