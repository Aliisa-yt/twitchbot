from __future__ import annotations

import asyncio
from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING, Any

import numpy as np
import soundfile
from gtts import gTTS, gTTSError
from numpy import dtype

from core.tts.interface import Interface, TTSExceptionError
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging
    from pathlib import Path

    from models.config_models import TTSEngine
    from models.voice_models import TTSParam


__all__: list[str] = ["GoogleText2Speech"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)


def _ensure_float32_array(arr: Any, label: str = "audio data") -> np.ndarray[Any, dtype[np.float32]]:
    """Validate and cast array to float32 ndarray with proper type hints.

    Args:
        arr: Data to validate
        label: Description for error messages

    Returns:
        Validated float32 ndarray

    Raises:
        TypeError: If not ndarray or wrong dtype
    """
    if not isinstance(arr, np.ndarray):
        msg: str = f"Expected ndarray for {label}, got {type(arr)}"
        raise TypeError(msg)
    if arr.dtype != np.float32:
        msg = f"Expected float32 for {label}, got {arr.dtype}"
        raise TypeError(msg)
    return arr


@dataclass
class _AudioData:
    raw_pcm: np.ndarray[Any, dtype[np.float32]]
    samplerate: int

    def __post_init__(self) -> None:
        if not isinstance(self.raw_pcm, np.ndarray):
            msg: str = f"Expected ndarray for raw_pcm, got {type(self.raw_pcm)}"
            raise TypeError(msg)
        if not isinstance(self.samplerate, int):
            msg: str = f"Expected int for samplerate, got {type(self.samplerate)}"
            raise TypeError(msg)


class GoogleText2Speech(Interface):
    """Performs speech synthesis using gTTS

    The original output from gTTS is an mp3 stream.
    The stream data is decoded and saved as a mono, float32 WAV file.
    The sample rate remains unchanged.
    """

    def __init__(self) -> None:
        logger.debug("%s initializing", self.__class__.__name__)
        super().__init__()

    @staticmethod
    def fetch_engine_name() -> str:
        return "gtts"

    def initialize_engine(self, tts_engine: TTSEngine) -> bool:
        super().initialize_engine(tts_engine)
        # Output a message to the console
        print("Loaded speech synthesis engine: Google Text-to-Speech")
        return True

    async def speech_synthesis(self, ttsparam: TTSParam) -> None:
        try:
            mp3_data = BytesIO()
            voicefile: Path = self.create_audio_filename(suffix="wav")
            logger.debug("'TTS file': '%s'", voicefile)

            if ttsparam.content_lang is None:
                mes = "Language coded 'None' is specified."
                raise ValueError(mes)

            gtts: gTTS = gTTS(ttsparam.content, lang=ttsparam.content_lang)
            await asyncio.to_thread(gtts.write_to_fp, mp3_data)

            # When data is set to a file-like object, the file pointer is automatically set to the end.
            # Therefore, if you try to read data without doing anything,
            # you will not be able to read anything because it is already EOF.
            # The solution is to use "seek" to set the file pointer back to the beginning,
            # so that the data can be read correctly.
            # https://github.com/bastibe/python-soundfile/issues/333
            mp3_data.seek(0)

            # Disable type checking because the type checker detects that the data type is float64,
            # even though the data type is float32 and the actual data is also float32.
            raw_pcm, samplerate = soundfile.read(mp3_data, dtype="float32")

            # Validate and cast to float32 ndarray with proper type hints
            raw_pcm = _ensure_float32_array(raw_pcm, "mp3 audio data")
            audiodata = _AudioData(raw_pcm=raw_pcm, samplerate=samplerate)
            logger.debug("sampling rate=%d", audiodata.samplerate)

            _volume: int | None = ttsparam.tts_info.voice.volume
            # Skip volume conversion process when volume is None or 100
            if _volume is not None and _volume != 100:
                # Volume range 0-200(%)
                _vol: float = max(min(_volume, 200), 0) / 100.0
                logger.debug("volume conversion started")
                # The volume conversion process is over 100 times faster when broadcast processing is performed using
                # the NumPy ndarray type than when conversion is performed using list comprehension notation.
                # However, due to Python specifications, the result of the volume conversion process will be float32 or
                # float64 type, regardless of the original data type, as division automatically converts the type to
                # float.
                # Therefore, MP3 decoding needs to be done using the float32 or float64 type.
                # However, pyaudio does not support the float64 type, so it uses the float32 type instead.
                # Using the int type for decoding causes processing to become very slow due to type conversion and
                # overflow.
                audiodata.raw_pcm *= _vol
                logger.debug("volume conversion finished")

            soundfile.write(voicefile, audiodata.raw_pcm, audiodata.samplerate, subtype="FLOAT", format="WAV")
            logger.debug("ttsfile_queue.put '%s'", voicefile)

            ttsparam.filepath = voicefile
            await self.play(ttsparam)
        except TTSExceptionError as err:
            logger.error("'%s': %s", self.fetch_engine_name().upper(), err)
        except (soundfile.LibsndfileError, soundfile.SoundFileRuntimeError) as err:
            logger.error("SoundFile Error: %s", err)
        except gTTSError as err:
            logger.error("gTTS Internal Error: %s", err)
        except (
            AssertionError,
            OSError,
            AttributeError,
            TypeError,
            ValueError,
        ) as err:
            logger.error("An error occurred in the TTS process: %s", err)
