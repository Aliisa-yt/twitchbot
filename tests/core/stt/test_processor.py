"""Tests for STTProcessor."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.stt.processor import ProcessorOptions, STTProcessor
from core.stt.recorder import STTSegment
from core.stt.stt_interface import (
    STTExceptionError,
    STTInput,
    STTNonRetriableError,
    STTNotAvailableError,
    STTResult,
)
from utils.file_utils import FileUtilsError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_segment(path: Path | None = None) -> STTSegment:
    return STTSegment(
        audio_path=path or Path("/tmp/seg.pcm"),
        sample_rate=16000,
        channels=1,
        duration_sec=1.0,
        created_at=0.0,
    )


def _make_engine(*, available: bool = True) -> MagicMock:
    engine = MagicMock()
    engine.is_available = available
    return engine


def _make_stt_input() -> STTInput:
    return STTInput(
        audio_path=Path("/tmp/seg.pcm"),
        language="ja-JP",
        sample_rate=16000,
        channels=1,
    )


# ---------------------------------------------------------------------------
# ProcessorOptions
# ---------------------------------------------------------------------------


class TestProcessorOptions:
    def test_defaults(self) -> None:
        opts = ProcessorOptions()
        assert opts.language == "ja-JP"
        assert opts.retry_max == 3
        assert opts.retry_backoff_ms == 500


# ---------------------------------------------------------------------------
# STTProcessor.run
# ---------------------------------------------------------------------------


class TestSTTProcessorRun:
    async def test_run_exits_immediately_when_terminate_event_is_set(self) -> None:
        queue: asyncio.Queue[STTSegment] = asyncio.Queue()
        event = asyncio.Event()
        event.set()
        processor = STTProcessor(queue, event, None, ProcessorOptions())
        # Should return without blocking.
        await processor.run()

    async def test_run_exits_on_queue_shutdown(self) -> None:
        queue: asyncio.Queue[STTSegment] = asyncio.Queue()
        event = asyncio.Event()
        processor = STTProcessor(queue, event, None, ProcessorOptions())
        with patch.object(queue, "get", new=AsyncMock(side_effect=asyncio.QueueShutDown)):
            await processor.run()

    async def test_run_processes_segment_and_exits_when_event_set(self) -> None:
        queue: asyncio.Queue[STTSegment] = asyncio.Queue()
        event = asyncio.Event()
        segment = _make_segment()
        await queue.put(segment)

        processed: list[STTSegment] = []
        processor = STTProcessor(queue, event, None, ProcessorOptions())

        async def fake_process(seg: STTSegment) -> None:
            processed.append(seg)
            event.set()

        processor._process_segment = fake_process  # type: ignore[method-assign]
        await processor.run()

        assert processed == [segment]


# ---------------------------------------------------------------------------
# STTProcessor._process_segment
# ---------------------------------------------------------------------------


class TestProcessSegment:
    async def test_engine_none_drops_segment_and_cleans_up(self, tmp_path: Path) -> None:
        seg_path = tmp_path / "seg.pcm"
        segment = _make_segment(seg_path)
        on_result = AsyncMock()
        processor = STTProcessor(asyncio.Queue(), asyncio.Event(), None, ProcessorOptions(), on_result)

        with patch("core.stt.processor.FileUtils.remove") as mock_remove:
            await processor._process_segment(segment)

        on_result.assert_not_awaited()
        mock_remove.assert_called_once_with(seg_path)

    async def test_engine_unavailable_drops_segment_and_cleans_up(self, tmp_path: Path) -> None:
        seg_path = tmp_path / "seg.pcm"
        segment = _make_segment(seg_path)
        engine = _make_engine(available=False)
        on_result = AsyncMock()
        processor = STTProcessor(asyncio.Queue(), asyncio.Event(), engine, ProcessorOptions(), on_result)

        with patch("core.stt.processor.FileUtils.remove") as mock_remove:
            await processor._process_segment(segment)

        on_result.assert_not_awaited()
        mock_remove.assert_called_once_with(seg_path)

    async def test_successful_transcription_calls_on_result(self, tmp_path: Path) -> None:
        seg_path = tmp_path / "seg.pcm"
        segment = _make_segment(seg_path)
        result = STTResult(text="hello", language="ja-JP")
        engine = _make_engine()
        on_result = AsyncMock()
        processor = STTProcessor(asyncio.Queue(), asyncio.Event(), engine, ProcessorOptions(), on_result)

        with (
            patch("asyncio.to_thread", new=AsyncMock(return_value=result)),
            patch("core.stt.processor.FileUtils.remove"),
        ):
            await processor._process_segment(segment)

        on_result.assert_awaited_once_with(result)

    async def test_transcription_returns_none_skips_on_result(self, tmp_path: Path) -> None:
        seg_path = tmp_path / "seg.pcm"
        segment = _make_segment(seg_path)
        engine = _make_engine()
        on_result = AsyncMock()
        processor = STTProcessor(asyncio.Queue(), asyncio.Event(), engine, ProcessorOptions(), on_result)

        # STTNonRetriableError causes _transcribe_with_retry to return None.
        with (
            patch("asyncio.to_thread", new=AsyncMock(side_effect=STTNonRetriableError("fail"))),
            patch("core.stt.processor.FileUtils.remove"),
        ):
            await processor._process_segment(segment)

        on_result.assert_not_awaited()

    async def test_no_on_result_callback_no_error(self, tmp_path: Path) -> None:
        seg_path = tmp_path / "seg.pcm"
        segment = _make_segment(seg_path)
        engine = _make_engine()
        processor = STTProcessor(asyncio.Queue(), asyncio.Event(), engine, ProcessorOptions(), on_result=None)

        with (
            patch("asyncio.to_thread", new=AsyncMock(return_value=STTResult(text="hello"))),
            patch("core.stt.processor.FileUtils.remove"),
        ):
            await processor._process_segment(segment)  # Must not raise.

    async def test_cleanup_always_runs_even_when_on_result_raises(self, tmp_path: Path) -> None:
        seg_path = tmp_path / "seg.pcm"
        segment = _make_segment(seg_path)
        engine = _make_engine()
        on_result = AsyncMock(side_effect=RuntimeError("callback failure"))
        processor = STTProcessor(asyncio.Queue(), asyncio.Event(), engine, ProcessorOptions(), on_result)

        with (
            patch("asyncio.to_thread", new=AsyncMock(return_value=STTResult(text="hello"))),
            patch("core.stt.processor.FileUtils.remove") as mock_remove,
            pytest.raises(RuntimeError),
        ):
            await processor._process_segment(segment)

        mock_remove.assert_called_once_with(seg_path)


# ---------------------------------------------------------------------------
# STTProcessor._transcribe_with_retry
# ---------------------------------------------------------------------------


class TestTranscribeWithRetry:
    async def test_engine_none_returns_none(self) -> None:
        processor = STTProcessor(asyncio.Queue(), asyncio.Event(), None, ProcessorOptions())
        result = await processor._transcribe_with_retry(_make_stt_input())
        assert result is None

    async def test_success_on_first_attempt_returns_result(self) -> None:
        expected = STTResult(text="hello", language="ja-JP")
        processor = STTProcessor(asyncio.Queue(), asyncio.Event(), _make_engine(), ProcessorOptions())

        with patch("asyncio.to_thread", new=AsyncMock(return_value=expected)):
            result = await processor._transcribe_with_retry(_make_stt_input())

        assert result == expected

    async def test_non_retriable_error_returns_none_without_retry(self) -> None:
        processor = STTProcessor(asyncio.Queue(), asyncio.Event(), _make_engine(), ProcessorOptions(retry_max=3))

        with patch("asyncio.to_thread", new=AsyncMock(side_effect=STTNonRetriableError("bad"))) as mock_thread:
            result = await processor._transcribe_with_retry(_make_stt_input())

        assert result is None
        assert mock_thread.call_count == 1  # No retry occurred.

    async def test_not_available_error_breaks_loop_returns_none(self) -> None:
        processor = STTProcessor(asyncio.Queue(), asyncio.Event(), _make_engine(), ProcessorOptions(retry_max=3))

        with patch("asyncio.to_thread", new=AsyncMock(side_effect=STTNotAvailableError("offline"))) as mock_thread:
            result = await processor._transcribe_with_retry(_make_stt_input())

        assert result is None
        assert mock_thread.call_count == 1  # Breaks immediately without retry.

    async def test_stt_exception_retries_and_exhausts_returns_none(self) -> None:
        retry_max = 3
        processor = STTProcessor(
            asyncio.Queue(),
            asyncio.Event(),
            _make_engine(),
            ProcessorOptions(retry_max=retry_max, retry_backoff_ms=0),
        )

        with (
            patch("asyncio.to_thread", new=AsyncMock(side_effect=STTExceptionError("transient"))) as mock_thread,
            patch("asyncio.sleep"),
        ):
            result = await processor._transcribe_with_retry(_make_stt_input())

        assert result is None
        assert mock_thread.call_count == retry_max

    async def test_stt_exception_succeeds_on_second_attempt(self) -> None:
        expected = STTResult(text="ok", language="ja-JP")
        processor = STTProcessor(
            asyncio.Queue(),
            asyncio.Event(),
            _make_engine(),
            ProcessorOptions(retry_max=3, retry_backoff_ms=0),
        )

        with (
            patch(
                "asyncio.to_thread",
                new=AsyncMock(side_effect=[STTExceptionError("transient"), expected]),
            ) as mock_thread,
            patch("asyncio.sleep"),
        ):
            result = await processor._transcribe_with_retry(_make_stt_input())

        assert result == expected
        assert mock_thread.call_count == 2

    async def test_unexpected_exception_returns_none_without_retry(self) -> None:
        processor = STTProcessor(asyncio.Queue(), asyncio.Event(), _make_engine(), ProcessorOptions(retry_max=3))

        with patch("asyncio.to_thread", new=AsyncMock(side_effect=ValueError("unexpected"))) as mock_thread:
            result = await processor._transcribe_with_retry(_make_stt_input())

        assert result is None
        assert mock_thread.call_count == 1  # No retry for non-STT exceptions.

    async def test_backoff_sleep_called_with_exponential_delays(self) -> None:
        # retry_max=3 → attempts 1,2,3. Sleeps after attempt 1 and 2 only.
        processor = STTProcessor(
            asyncio.Queue(),
            asyncio.Event(),
            _make_engine(),
            ProcessorOptions(retry_max=3, retry_backoff_ms=500),
        )

        with (
            patch("asyncio.to_thread", new=AsyncMock(side_effect=STTExceptionError("err"))),
            patch("asyncio.sleep") as mock_sleep,
        ):
            await processor._transcribe_with_retry(_make_stt_input())

        # attempt 1 → sleep(0.5 * 2^0 = 0.5), attempt 2 → sleep(0.5 * 2^1 = 1.0), attempt 3 → exhausted (no sleep)
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(0.5)
        mock_sleep.assert_any_call(1.0)

    async def test_retry_max_zero_clamped_to_one_attempt(self) -> None:
        # max(1, 0) == 1, so exactly one attempt is made even when retry_max=0.
        processor = STTProcessor(asyncio.Queue(), asyncio.Event(), _make_engine(), ProcessorOptions(retry_max=0))

        with patch("asyncio.to_thread", new=AsyncMock(side_effect=STTExceptionError("err"))) as mock_thread:
            result = await processor._transcribe_with_retry(_make_stt_input())

        assert result is None
        assert mock_thread.call_count == 1


# ---------------------------------------------------------------------------
# STTProcessor._cleanup_segment_file
# ---------------------------------------------------------------------------


class TestCleanupSegmentFile:
    def test_removes_file_via_file_utils(self, tmp_path: Path) -> None:
        seg_path = tmp_path / "seg.pcm"
        processor = STTProcessor(asyncio.Queue(), asyncio.Event(), None, ProcessorOptions())

        with patch("core.stt.processor.FileUtils.remove") as mock_remove:
            processor._cleanup_segment_file(seg_path)

        mock_remove.assert_called_once_with(seg_path)

    def test_logs_warning_on_file_utils_error_does_not_raise(self, tmp_path: Path) -> None:
        seg_path = tmp_path / "missing.pcm"
        processor = STTProcessor(asyncio.Queue(), asyncio.Event(), None, ProcessorOptions())

        with patch("core.stt.processor.FileUtils.remove", side_effect=FileUtilsError("not found")):
            processor._cleanup_segment_file(seg_path)  # Must not raise.
