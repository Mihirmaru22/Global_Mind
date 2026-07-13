"""Tests for the lineage/versioning ingestion registry.

Exercises the state machine that guards the two headline invariants:

  * content-addressed dedup (identity is content, not filename), and
  * safe replacement with an atomic cutover that never leaves a document with
    zero active versions.
"""

import json

import pytest

from src.core.ingestion_registry import IngestionRegistry, RegistryStatus


def _write(path, content: bytes = b"hello"):
    path.write_bytes(content)
    return path


@pytest.fixture
def registry(tmp_path):
    return IngestionRegistry(registry_path=tmp_path / "reg.json")


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def test_new_file_is_new(registry, tmp_path):
    f = _write(tmp_path / "a.pdf", b"alpha")
    result = registry.check(f)
    assert result.status == RegistryStatus.NEW_FILE
    assert result.sha256 == result.content_hash


def test_identical_content_is_deduped(registry, tmp_path):
    f = _write(tmp_path / "a.pdf", b"alpha")
    check = registry.check(f)
    registry.register(f, document_id="doc-a", total_chunks=3, sha256=check.sha256)

    # Same bytes, different name → already ingested.
    g = _write(tmp_path / "copy.pdf", b"alpha")
    result = registry.check(g)
    assert result.status == RegistryStatus.ALREADY_INGESTED
    assert result.old_document_id == "doc-a"


def test_same_name_different_content_are_two_documents(registry, tmp_path):
    """Two people's resume.pdf must both survive."""
    a = _write(tmp_path / "resume.pdf", b"person-one")
    ca = registry.check(a)
    registry.register(a, document_id="doc-1", total_chunks=1, sha256=ca.sha256)

    b = _write(tmp_path / "resume.pdf", b"person-two")
    cb = registry.check(b)
    assert cb.status == RegistryStatus.NEW_FILE  # new content, same name
    registry.register(b, document_id="doc-2", total_chunks=1, sha256=cb.sha256)

    active = registry.get_active_ids()
    assert active == {"doc-1", "doc-2"}


# ---------------------------------------------------------------------------
# Versioning / atomic cutover
# ---------------------------------------------------------------------------

def test_create_version_starts_new_lineage(registry, tmp_path):
    f = _write(tmp_path / "spec.md", b"v1")
    entry = registry.create_version(f, content_hash="h1", total_chunks=2)
    assert entry["active"] is True
    assert entry["supersedes"] is None
    assert entry["lineage_root"] == entry["document_id"]


def test_replace_keeps_old_active_until_cutover(registry, tmp_path):
    """The invariant: old stays active until supersede() flips it."""
    v1 = _write(tmp_path / "spec.md", b"v1")
    e1 = registry.create_version(v1, content_hash="h1", total_chunks=2)

    # New version indexed and registered — BEFORE the cutover both are active.
    v2 = _write(tmp_path / "spec.md", b"v2")
    e2 = registry.create_version(
        v2, content_hash="h2", total_chunks=3, supersedes=e1["document_id"]
    )
    assert registry.get_by_document_id(e1["document_id"])["active"] is True
    assert registry.get_by_document_id(e2["document_id"])["active"] is True
    # Never zero active versions at any point.
    assert len(registry.get_active_ids()) >= 1

    # Cutover.
    assert registry.supersede(e1["document_id"], e2["document_id"]) is True
    old = registry.get_by_document_id(e1["document_id"])
    new = registry.get_by_document_id(e2["document_id"])
    assert old["active"] is False
    assert old["superseded_by"] == e2["document_id"]
    assert new["active"] is True
    assert new["supersedes"] == e1["document_id"]
    assert new["lineage_root"] == e1["document_id"]


def test_lineage_root_is_stable_across_three_versions(registry, tmp_path):
    e1 = registry.create_version(_write(tmp_path / "d.md", b"1"), content_hash="a", total_chunks=1)
    e2 = registry.create_version(
        _write(tmp_path / "d.md", b"2"), content_hash="b", total_chunks=1,
        supersedes=e1["document_id"],
    )
    registry.supersede(e1["document_id"], e2["document_id"])
    e3 = registry.create_version(
        _write(tmp_path / "d.md", b"3"), content_hash="c", total_chunks=1,
        supersedes=e2["document_id"],
    )
    registry.supersede(e2["document_id"], e3["document_id"])

    root = e1["document_id"]
    versions = registry.get_versions(root)
    assert [v["document_id"] for v in versions] == [
        e1["document_id"], e2["document_id"], e3["document_id"]
    ]
    assert registry.get_active_ids() == {e3["document_id"]}
    assert registry.get_superseded_ids() == {e1["document_id"], e2["document_id"]}


def test_superseded_content_can_be_reingested(registry, tmp_path):
    """Re-uploading content that was superseded is NOT a dedup hit."""
    e1 = registry.create_version(_write(tmp_path / "d.md", b"v1"), content_hash="h1", total_chunks=1)
    e2 = registry.create_version(
        _write(tmp_path / "d.md", b"v2"), content_hash="h2", total_chunks=1,
        supersedes=e1["document_id"],
    )
    registry.supersede(e1["document_id"], e2["document_id"])

    # h1 is now inactive; re-uploading v1 bytes should be treated as new.
    again = _write(tmp_path / "again.md", b"v1")
    check = registry.check(again)
    assert check.status == RegistryStatus.NEW_FILE


def test_supersede_unknown_ids_is_noop(registry, tmp_path):
    e1 = registry.create_version(_write(tmp_path / "d.md", b"1"), content_hash="a", total_chunks=1)
    assert registry.supersede("nope", e1["document_id"]) is False
    assert registry.supersede(e1["document_id"], "nope") is False
    assert registry.get_by_document_id(e1["document_id"])["active"] is True


def test_unregister_reactivates_predecessor(registry, tmp_path):
    """Deleting the current version brings its predecessor back to active."""
    e1 = registry.create_version(_write(tmp_path / "d.md", b"1"), content_hash="a", total_chunks=1)
    e2 = registry.create_version(
        _write(tmp_path / "d.md", b"2"), content_hash="b", total_chunks=1,
        supersedes=e1["document_id"],
    )
    registry.supersede(e1["document_id"], e2["document_id"])

    assert registry.unregister(e2["document_id"]) is True
    restored = registry.get_by_document_id(e1["document_id"])
    assert restored["active"] is True
    assert restored["superseded_by"] is None
    assert registry.get_active_ids() == {e1["document_id"]}


def test_find_active_by_filename(registry, tmp_path):
    registry.create_version(_write(tmp_path / "report.pdf", b"1"), content_hash="a", total_chunks=1)
    match = registry.find_active_by_filename("report.pdf")
    assert match is not None and match["content_hash"] == "a"
    assert registry.find_active_by_filename("missing.pdf") is None


# ---------------------------------------------------------------------------
# Migration from the legacy sha256-keyed schema
# ---------------------------------------------------------------------------

def test_legacy_registry_is_migrated(tmp_path):
    legacy = {
        "a" * 64: {
            "document_id": "old-doc",
            "file_name": "old.pdf",
            "file_path": "/uploads/old.pdf",
            "file_size_bytes": 10,
            "total_chunks": 5,
            "ingested_at": "2026-01-01T00:00:00+00:00",
        }
    }
    path = tmp_path / "reg.json"
    path.write_text(json.dumps(legacy))

    reg = IngestionRegistry(registry_path=path)
    entry = reg.get_by_document_id("old-doc")
    assert entry is not None
    assert entry["content_hash"] == "a" * 64
    assert entry["filename"] == "old.pdf"
    assert entry["active"] is True
    assert entry["lineage_root"] == "old-doc"
    assert entry["created_at"] == "2026-01-01T00:00:00+00:00"

    # Persisted upgrade → keyed by document_id now, not sha256.
    on_disk = json.loads(path.read_text())
    assert "old-doc" in on_disk
    assert "a" * 64 not in on_disk


def test_migration_is_idempotent(tmp_path):
    path = tmp_path / "reg.json"
    reg = IngestionRegistry(registry_path=path)
    f = _write(tmp_path / "x.md", b"x")
    reg.register(f, document_id="d1", total_chunks=1)

    reloaded = IngestionRegistry(registry_path=path)
    assert reloaded.get_by_document_id("d1") is not None
    assert reloaded.get_active_ids() == {"d1"}
