"""Unit tests for core.tts.file_manager module."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.tts.file_manager import TTSFileManager
from utils.file_utils import FileUtils


@pytest.mark.asyncio
async def test_file_deletion_worker_processes_queue_and_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    path1: Path = Path("file1.wav")
    path2: Path = Path("file2.wav")

    class FakeQueue:
        def __init__(self) -> None:
            self.items: list[Path] = [path1, path2]
            self.calls = 0
            self.task_done = MagicMock()

        async def get(self) -> Path:
            if self.calls == 0:
                self.calls += 1
                return self.items.pop(0)
            raise asyncio.QueueShutDown

        def empty(self) -> bool:
            return not self.items

        def get_nowait(self) -> Path:
            if not self.items:
                raise asyncio.QueueEmpty
            return self.items.pop(0)

    deletion_queue = FakeQueue()
    manager: TTSFileManager = TTSFileManager(cast("asyncio.Queue[Path]", deletion_queue))
    delete_mock: AsyncMock = AsyncMock()
    monkeypatch.setattr(manager, "_delete_file_with_retry", delete_mock)

    await manager.audio_file_cleanup_task()

    assert delete_mock.await_count == 2
    deletion_queue.task_done.assert_called()


def test_enqueue_file_deletion_puts_item(tmp_path: Path) -> None:
    deletion_queue: asyncio.Queue[Path] = asyncio.Queue()
    manager: TTSFileManager = TTSFileManager(deletion_queue)
    file_path: Path = tmp_path / "audio.wav"

    manager.enqueue_file_deletion(file_path)

    assert deletion_queue.get_nowait() == file_path


def test_enqueue_file_deletion_handles_queue_full(tmp_path: Path) -> None:
    deletion_queue: asyncio.Queue[Path] = asyncio.Queue(maxsize=1)
    manager: TTSFileManager = TTSFileManager(deletion_queue)
    file_path: Path = tmp_path / "audio.wav"
    deletion_queue.put_nowait(file_path)

    manager.enqueue_file_deletion(file_path)

    assert deletion_queue.qsize() == 1


def test_enqueue_file_deletion_handles_shutdown(tmp_path: Path) -> None:
    deletion_queue: asyncio.Queue[Path] = asyncio.Queue()
    manager: TTSFileManager = TTSFileManager(deletion_queue)
    file_path: Path = tmp_path / "audio.wav"

    deletion_queue.shutdown()
    manager.enqueue_file_deletion(file_path)

    assert deletion_queue.qsize() == 0


@pytest.mark.asyncio
async def test_delete_file_with_retry_succeeds_after_permission_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    deletion_queue: asyncio.Queue[Path] = asyncio.Queue()
    manager: TTSFileManager = TTSFileManager(deletion_queue)

    file_path: Path = tmp_path / "audio.wav"
    file_path.write_bytes(b"data")  # noqa: ASYNC240

    monkeypatch.setattr(FileUtils, "check_file_status", MagicMock(return_value=True))

    call_state = SimpleNamespace(count=0)
    original_unlink = Path.unlink

    def fake_unlink(*_args, **_kwargs) -> None:
        if call_state.count == 0:
            call_state.count += 1
            msg = "locked"
            raise PermissionError(msg)
        original_unlink(file_path, missing_ok=True)

    monkeypatch.setattr(Path, "unlink", fake_unlink)

    await manager._delete_file_with_retry(file_path, max_retries=2, delay=0)

    assert not file_path.exists()  # noqa: ASYNC240


@pytest.mark.asyncio
async def test_delete_file_with_retry_skips_when_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    deletion_queue: asyncio.Queue[Path] = asyncio.Queue()
    manager: TTSFileManager = TTSFileManager(deletion_queue)
    file_path: Path = Path("missing.wav")

    monkeypatch.setattr(FileUtils, "check_file_status", MagicMock(return_value=False))
    unlink_mock: MagicMock = MagicMock()
    monkeypatch.setattr(Path, "unlink", unlink_mock)

    await manager._delete_file_with_retry(file_path, max_retries=0, delay=0)

    unlink_mock.assert_not_called()
