"""Tests for cross-platform file locking and the atomic-write stores.

Guards the Windows-compatibility fix (issue #6): portalocker replaces the
Unix-only fcntl, and os.replace replaces Path.rename (which fails on Windows
when the destination already exists).
"""

import json

import pytest

from src.core.file_lock import LockMode, locked
from src.core.ingestion_registry import IngestionRegistry
from src.core.state import UIStateManager


def test_shared_lock_allows_read(tmp_path):
    p = tmp_path / "data.json"
    p.write_text('{"a": 1}')
    with open(p) as f:
        with locked(f, LockMode.SHARED):
            assert json.load(f) == {"a": 1}


def test_exclusive_lock_allows_write(tmp_path):
    p = tmp_path / "data.json"
    with open(p, "w") as f:
        with locked(f, LockMode.EXCLUSIVE):
            f.write('{"b": 2}')
    assert json.loads(p.read_text()) == {"b": 2}


def test_lock_released_after_exception(tmp_path):
    """The lock must release even if the body raises, or the next open blocks."""
    p = tmp_path / "data.json"
    p.write_text("{}")
    with pytest.raises(ValueError):
        with open(p) as f:
            with locked(f, LockMode.SHARED):
                raise ValueError("boom")
    # Re-acquiring must succeed (lock was released).
    with open(p) as f:
        with locked(f, LockMode.EXCLUSIVE):
            pass


def test_state_save_overwrites_existing_file(tmp_path):
    """os.replace must atomically overwrite a pre-existing destination.

    Path.rename raises FileExistsError on Windows in this case — the exact bug
    the fix closes.
    """
    sm = UIStateManager()
    sm.settings_file = tmp_path / "settings.json"
    sm.settings_file.write_text('{"stale": true}')  # destination already exists

    sm._save_json(sm.settings_file, {"provider": "openrouter"})
    assert sm._load_json(sm.settings_file, {}) == {"provider": "openrouter"}


def test_registry_save_overwrites_existing_file(tmp_path):
    reg = IngestionRegistry()
    reg._path = tmp_path / "reg.json"
    reg._path.write_text("{}")  # destination already exists

    reg._save({"sha1": {"file_name": "a.pdf", "total_chunks": 5}})
    assert reg._load() == {"sha1": {"file_name": "a.pdf", "total_chunks": 5}}
