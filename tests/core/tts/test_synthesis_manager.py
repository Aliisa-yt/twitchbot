import asyncio
from types import SimpleNamespace
from typing import Any, NoReturn, cast

import pytest

from core.tts.synthesis_manager import SynthesisManager, TTSEngineHandlerMap
from models.voice_models import TTSInfo, TTSParam
from utils.excludable_queue import ExcludableQueue


class DummyHandler:
    def __init__(self) -> None:
        self.execute_called = False
        self.ainit_called_with = None
        self.synthesis_called_with = None
        self.close_called = False
        self.termination_called = False

    async def execute(self) -> None:
        self.execute_called = True

    async def ainit(self, voice_parameters) -> None:
        self.ainit_called_with = voice_parameters

    async def synthesis(self, tts_param) -> None:
        # simulate some work
        self.synthesis_called_with = tts_param

    async def close(self) -> None:
        self.close_called = True

    async def termination(self) -> None:
        self.termination_called = True


class SchedulingErrorHandler:
    def bad(self, *_args, **_kwargs) -> NoReturn:
        # raise synchronously when called (scheduling error)
        msg = "scheduling error"
        raise RuntimeError(msg)


class ExecutionErrorHandler:
    def __init__(self) -> None:
        self.called = False

    async def do(self, *_args, **_kwargs) -> NoReturn:
        self.called = True
        msg = "execution error"
        raise RuntimeError(msg)


@pytest.mark.asyncio
async def test_dispatch_tts_tasks_handles_various_outcomes() -> None:
    # Arrange
    config: Any = SimpleNamespace(
        VOICE_PARAMETERS=SimpleNamespace(get_tts_engine_list=list),
        TRANSLATION=SimpleNamespace(NATIVE_LANGUAGE="en", SECOND_LANGUAGE="ja"),
        TTS=SimpleNamespace(ENABLED_LANGUAGES=None, KATAKANAISE=False, LIMIT_CHARACTERS=None),
        GENERAL=SimpleNamespace(TMP_DIR="."),
    )

    synth_q: ExcludableQueue[TTSParam] = ExcludableQueue()
    play_q: ExcludableQueue[TTSParam] = ExcludableQueue()
    manager = SynthesisManager(config, synth_q, play_q, asyncio.Event())

    ok_handler = SimpleNamespace(do=lambda *_a, **_k: asyncio.sleep(0, result=None))

    sched_handler = SimpleNamespace(do=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("scheduling error")))

    exec_handler = ExecutionErrorHandler()

    handler_map = {
        "ok": ok_handler,
        "sched": sched_handler,
        "exec": exec_handler,
    }

    # Act / Assert
    # Should not raise despite scheduling/execution errors
    await manager._dispatch_tts_tasks(cast("TTSEngineHandlerMap", handler_map), "do", 1, key="v")  # noqa: SLF001
    assert exec_handler.called is True


@pytest.mark.asyncio
async def test_handle_tts_param_dispatches_to_correct_engine_and_handles_invalid() -> None:
    # Arrange
    config: Any = SimpleNamespace(
        VOICE_PARAMETERS=SimpleNamespace(get_tts_engine_list=list),
        TRANSLATION=SimpleNamespace(NATIVE_LANGUAGE="en", SECOND_LANGUAGE="ja"),
        TTS=SimpleNamespace(ENABLED_LANGUAGES=None, KATAKANAISE=False, LIMIT_CHARACTERS=None),
        GENERAL=SimpleNamespace(TMP_DIR="."),
    )

    synth_q: ExcludableQueue[TTSParam] = ExcludableQueue()
    play_q: ExcludableQueue[TTSParam] = ExcludableQueue()
    manager = SynthesisManager(config, synth_q, play_q, asyncio.Event())

    ok_handler: Any = DummyHandler()
    handler_map: TTSEngineHandlerMap = {"ok": ok_handler}

    tts_param = TTSParam(content="hello", content_lang="en", tts_info=TTSInfo(engine="ok"))

    # Act
    await manager._handle_tts_param(tts_param, handler_map)  # noqa: SLF001

    # Assert
    assert ok_handler.synthesis_called_with is tts_param

    # Invalid engine
    tts_param2 = TTSParam(content="x", content_lang="en", tts_info=TTSInfo(engine="nope"))
    # Should not raise
    await manager._handle_tts_param(tts_param2, handler_map)  # noqa: SLF001


@pytest.mark.asyncio
async def test_tts_processing_task_consumes_queue_and_handles_shutdown() -> None:
    # Arrange
    config: Any = SimpleNamespace(
        VOICE_PARAMETERS=SimpleNamespace(get_tts_engine_list=list),
        TRANSLATION=SimpleNamespace(NATIVE_LANGUAGE="en", SECOND_LANGUAGE="ja"),
        TTS=SimpleNamespace(ENABLED_LANGUAGES=None, KATAKANAISE=False, LIMIT_CHARACTERS=None),
        GENERAL=SimpleNamespace(TMP_DIR="."),
    )

    synth_q: ExcludableQueue[TTSParam] = ExcludableQueue()
    play_q: ExcludableQueue[TTSParam] = ExcludableQueue()
    manager = SynthesisManager(config, synth_q, play_q, asyncio.Event())

    # prepare handler that sets events when methods called
    class EHandler:
        def __init__(self) -> None:
            self.synth_event = asyncio.Event()
            self.close_event = asyncio.Event()
            self.term_event = asyncio.Event()

        async def execute(self) -> None:
            return None

        async def ainit(self, _voice_parameters) -> None:
            return None

        async def synthesis(self, _tts_param) -> None:
            # signal that synthesis was called
            self.synth_event.set()

        async def close(self) -> None:
            self.close_event.set()

        async def termination(self) -> None:
            self.term_event.set()

    handler: Any = EHandler()
    handler_map: TTSEngineHandlerMap = {"engine1": handler}

    async def fake_create_handler_map() -> TTSEngineHandlerMap:
        return handler_map

    manager._create_handler_map = fake_create_handler_map  # noqa: SLF001

    # run processing task
    task: asyncio.Task[None] = asyncio.create_task(manager.tts_processing_task())

    # give the task time to start and run ainit/execute
    await asyncio.sleep(0)

    # enqueue a tts param pointing to our engine
    tts_param = TTSParam(content="hello", content_lang="en", tts_info=TTSInfo(engine="engine1"))
    await manager.enqueue_tts_synthesis(tts_param)

    # wait for synthesis to be called
    await asyncio.wait_for(handler.synth_event.wait(), timeout=1.0)

    # shutdown queues to terminate the loop
    manager.synthesis_queue.shutdown()
    manager.playback_queue.shutdown()

    # wait for background task to finish and for close/termination handlers
    await asyncio.wait_for(task, timeout=1.0)

    assert handler.close_event.is_set() or handler.term_event.is_set()
