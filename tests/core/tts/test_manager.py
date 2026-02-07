from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.tts.interface import Interface
from core.tts.manager import TTSManager
from models.config_models import Config
from utils.excludable_queue import ExcludableQueue

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

    from config.loader import Config
    from models.voice_models import TTSParam


def _make_config(tmp_dir: str = "tmp") -> Config:
    return cast(
        "Config",
        SimpleNamespace(
            GENERAL=SimpleNamespace(TMP_DIR=tmp_dir),
            TRANSLATION=SimpleNamespace(NATIVE_LANGUAGE="en", SECOND_LANGUAGE="ja"),
            VOICE_PARAMETERS=MagicMock(),
        ),
    )


def test_init_sets_managers_and_interface_hooks() -> None:
    config: Config = _make_config("tmp_dir")
    prev_callback: Callable[[TTSParam], Awaitable[None]] | None = getattr(Interface, "_play_callback", None)
    prev_dir: Path | None = getattr(Interface, "_base_directory", None)

    with (
        patch("core.tts.manager.ParameterManager") as param_cls,
        patch("core.tts.manager.SynthesisManager") as synth_cls,
        patch("core.tts.manager.AudioPlaybackManager") as playback_cls,
    ):
        synth_inst = MagicMock()
        synth_cls.return_value = synth_inst
        playback_cls.return_value = MagicMock()
        param_cls.return_value = MagicMock()

        manager = TTSManager(config)

        assert isinstance(manager.synthesis_queue, ExcludableQueue)
        assert isinstance(manager.playback_queue, ExcludableQueue)
        assert manager.background_tasks == set()

        param_cls.assert_called_once_with(config)
        synth_cls.assert_called_once_with(
            config,
            manager.synthesis_queue,
            manager.playback_queue,
        )
        playback_cls.assert_called_once_with(
            config, manager.file_manager, manager.playback_queue, manager.task_terminate_event
        )

        assert Interface.play_callback is synth_inst.add_to_playback_queue
        assert Interface.audio_save_directory == config.GENERAL.TMP_DIR

    if prev_callback is not None:
        Interface.play_callback = prev_callback
    if prev_dir is not None:
        Interface.audio_save_directory = prev_dir


@pytest.mark.asyncio
async def test_initialize_creates_tasks_once() -> None:
    config: Config = _make_config()

    with (
        patch("core.tts.manager.ParameterManager"),
        patch("core.tts.manager.SynthesisManager") as synth_cls,
        patch("core.tts.manager.AudioPlaybackManager") as playback_cls,
    ):
        synth_inst = MagicMock()
        synth_inst.tts_processing_task = AsyncMock()
        synth_cls.return_value = synth_inst

        playback_inst = MagicMock()
        playback_inst.playback_queue_processor = AsyncMock()
        playback_cls.return_value = playback_inst

        manager = TTSManager(config)
        await manager.initialize()
        task_names: set[str] = {task.get_name() for task in manager.background_tasks}

        assert task_names == {"audio_file_cleanup_task", "TTS_processing_task", "play_voicefile_task"}

        await manager.initialize()
        assert len(manager.background_tasks) == 3

        for task in manager.background_tasks:
            task.cancel()
        await asyncio.gather(*manager.background_tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_close_sets_events_and_clears_tasks(monkeypatch: pytest.MonkeyPatch) -> None:
    config: Config = _make_config()

    with (
        patch("core.tts.manager.ParameterManager"),
        patch("core.tts.manager.SynthesisManager"),
        patch("core.tts.manager.AudioPlaybackManager"),
    ):
        manager = TTSManager(config)

    task_done: asyncio.Task[None] = asyncio.create_task(asyncio.sleep(0))
    task_pending: asyncio.Task[None] = asyncio.create_task(asyncio.sleep(10))
    manager.background_tasks = {task_done, task_pending}

    async def fake_wait(tasks, timeout) -> tuple[set[asyncio.Task[None]], set[asyncio.Task[None]]]:  # noqa: ASYNC109
        _ = tasks, timeout
        return {task_done}, {task_pending}

    monkeypatch.setattr("core.tts.manager.asyncio.wait", fake_wait)
    manager.synthesis_queue.shutdown = MagicMock()
    manager.playback_queue.shutdown = MagicMock()

    try:
        await manager.close()
    finally:
        task_pending.cancel()
        await asyncio.gather(task_done, task_pending, return_exceptions=True)

    assert manager.task_terminate_event.is_set()
    manager.synthesis_queue.shutdown.assert_called_once()
    manager.playback_queue.shutdown.assert_called_once()
    assert manager.background_tasks == set()


def test_forwarding_methods_call_managers() -> None:
    config: Config = _make_config()

    with (
        patch("core.tts.manager.ParameterManager") as param_cls,
        patch("core.tts.manager.SynthesisManager") as synth_cls,
        patch("core.tts.manager.AudioPlaybackManager"),
    ):
        param_inst = MagicMock()
        synth_inst = MagicMock()
        param_cls.return_value = param_inst
        synth_cls.return_value = synth_inst

        manager = TTSManager(config)

    message = MagicMock()
    manager.select_voice_usertype(message)
    param_inst.select_voice_usertype.assert_called_once_with(message)

    manager.command_voiceparameters(message)
    param_inst.command_voiceparameters.assert_called_once_with(message)

    manager.get_voice_param("en")
    param_inst.get_voice_param.assert_called_once_with("en")

    manager.prepare_tts_content(MagicMock())
    synth_inst.prepare_tts_content.assert_called_once()


@pytest.mark.asyncio
async def test_enqueue_tts_synthesis_delegates() -> None:
    config: Config = _make_config()

    with (
        patch("core.tts.manager.ParameterManager"),
        patch("core.tts.manager.SynthesisManager") as synth_cls,
        patch("core.tts.manager.AudioPlaybackManager"),
    ):
        synth_inst = MagicMock()
        synth_inst.enqueue_tts_synthesis = AsyncMock()
        synth_cls.return_value = synth_inst

        manager = TTSManager(config)

    tts_param = MagicMock()
    await manager.enqueue_tts_synthesis(tts_param)
    synth_inst.enqueue_tts_synthesis.assert_called_once_with(tts_param)


def test_voice_parameters_property_returns_parameter_manager() -> None:
    config: Config = _make_config()

    with (
        patch("core.tts.manager.ParameterManager") as param_cls,
        patch("core.tts.manager.SynthesisManager"),
        patch("core.tts.manager.AudioPlaybackManager"),
    ):
        param_inst = MagicMock()
        param_inst.voice_parameters = MagicMock()
        param_cls.return_value = param_inst

        manager = TTSManager(config)

    assert manager.voice_parameters is param_inst.voice_parameters
