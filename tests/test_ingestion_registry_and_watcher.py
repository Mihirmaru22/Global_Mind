from __future__ import annotations

from pathlib import Path

import pytest

from src.core.ingestion_registry import IngestionRegistry
from src.services import document_watcher
from src.services.document_watcher import DocumentWatcher


@pytest.mark.parametrize("initial_content", ["", "{not valid json"])
def test_ingestion_registry_repairs_empty_or_corrupt_json(tmp_path, initial_content):
    registry_path = tmp_path / "ingested_files.json"
    registry_path.write_text(initial_content, encoding="utf-8")

    registry = IngestionRegistry(registry_path=registry_path)

    assert registry._load() == {}
    assert registry_path.read_text(encoding="utf-8") == "{}"


@pytest.mark.asyncio
async def test_wait_for_stable_file_uses_consecutive_equal_sizes(tmp_path, monkeypatch):
    watcher = DocumentWatcher(
        path=tmp_path,
        stable_seconds=1.0,
        poll_interval=0.5,
        settle_timeout=2.0,
    )
    path = tmp_path / "report.docx"
    path.write_text("data", encoding="utf-8")

    class FakeClock:
        def __init__(self) -> None:
            self.now = 0.0

        def monotonic(self) -> float:
            return self.now

        async def sleep(self, seconds: float) -> None:
            self.now += seconds

    clock = FakeClock()

    class FakeStat:
        st_size = 10

    def fake_stat(self: Path) -> FakeStat:
        return FakeStat()

    monkeypatch.setattr(document_watcher.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(document_watcher.asyncio, "sleep", clock.sleep)
    monkeypatch.setattr(document_watcher.Path, "stat", fake_stat, raising=False)

    assert await watcher._wait_for_stable_file(path) is True


@pytest.mark.asyncio
async def test_process_path_retries_unstable_file_before_ingestion(tmp_path, monkeypatch):
    watcher = DocumentWatcher(
        path=tmp_path,
        stable_seconds=1.0,
        poll_interval=0.1,
        settle_timeout=1.0,
        retry_delay=0.0,
        max_retry_attempts=2,
    )
    path = tmp_path / "retry.docx"
    path.write_text("data", encoding="utf-8")

    attempts = 0
    ingested: list[Path] = []

    async def fake_wait_for_stable_file(_path: Path) -> bool:
        nonlocal attempts
        attempts += 1
        return attempts >= 2

    async def fake_start_ingestion(file_path: str | Path, pipeline=None):
        ingested.append(Path(file_path))
        return object()

    async def noop_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(watcher, "_wait_for_stable_file", fake_wait_for_stable_file)
    monkeypatch.setattr(document_watcher, "start_ingestion", fake_start_ingestion)
    monkeypatch.setattr(document_watcher.asyncio, "sleep", noop_sleep)

    await watcher._process_path(path, str(path.resolve()))

    assert ingested == [path]
