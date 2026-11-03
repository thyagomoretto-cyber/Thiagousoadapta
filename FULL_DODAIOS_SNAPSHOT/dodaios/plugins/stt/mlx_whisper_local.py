"""Whisper on the Apple Silicon GPU through MLX, the fastest local voice input on a Mac.

Measured 2026-11-03 on an M1 with 8 GB, on 8 s of the owner's real speech: 0.49 s
with the correct sentence, against 1.6 s for faster-whisper ``small`` on the CPU
with the same accuracy.

MLX keeps its default stream per thread, so a model loaded on one thread can
refuse to run on another. ``asyncio.to_thread`` gives no thread guarantee, so
every call into MLX runs on one worker thread, shared by all instances: each
voice call builds a new provider, and a thread per call would reload the model.

macOS on Apple Silicon only. Elsewhere ``mlx_stt_unavailable_reason`` in the
package ``__init__`` crosses to faster-whisper before this class is built.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np

from dodaios.audio.capture import pcm_bytes_to_np
from dodaios.core.protocols import AudioChunk, Transcript
from dodaios.speech.local_voice import MLX_WARM_GATE, record_timing

log = logging.getLogger(__name__)

AUTO_LANGUAGE = "auto"
DEFAULT_MODEL = "mlx-community/whisper-small-mlx"
_SAMPLE_RATE = 16_000
_INT16_FULL_SCALE = 32768.0
_NO_SPEECH_LIMIT = 0.6
_WORKER = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mlx-whisper")
_WARM_MODELS: set[str] = set()


class MlxWhisperSTT:
    """Structural ``STTProvider``; whole utterance in, one transcript out."""

    name = "mlx-whisper"
    supports_streaming = False
    runs_on_device = True
    #: Whisper uses names in its prompt to tell "Cachoeirinha" from "cachorrinha".
    accepts_bias_prompt = True

    def __init__(
        self, language: str | None = None, model: str = "", prompt: str = ""
    ) -> None:
        self._language = language or None
        self._prompt = (prompt or "").strip()
        self._model = (model or "").strip() or DEFAULT_MODEL
        _WORKER.submit(self._warm_quietly)

    def _run(self, samples: np.ndarray, language: str | None) -> dict[str, Any]:
        """Decode on the worker thread. Never call this from anywhere else."""
        try:
            import mlx_whisper  # noqa: PLC0415 — optional engine, lazy on purpose
        except ImportError as exc:
            raise RuntimeError(
                "mlx-whisper is not installed, so this voice engine cannot "
                "transcribe. Install it or switch voice input to faster-whisper."
            ) from exc
        options: dict[str, Any] = {
            "path_or_hf_repo": self._model,
            "fp16": True,
            "condition_on_previous_text": False,
            "verbose": None,
        }
        if language:
            options["language"] = language
        if self._prompt:
            options["initial_prompt"] = self._prompt
        return mlx_whisper.transcribe(samples, **options)

    def _warm_blocking(self) -> None:
        if self._model in _WARM_MODELS:
            return
        started = time.monotonic()
        silence = np.zeros(_SAMPLE_RATE, dtype=np.float32)
        with MLX_WARM_GATE:
            self._run(silence, self._language)
        _WARM_MODELS.add(self._model)
        record_timing("stt_warm", ms=round((time.monotonic() - started) * 1000))

    def _warm_quietly(self) -> None:
        try:
            self._warm_blocking()
        except Exception as exc:  # noqa: BLE001 — the first sentence reports it
            log.warning("MLX Whisper warm start failed: %s", exc)

    def warm_up(self) -> None:
        """Load the model and pay the first decode before the first utterance."""
        _WORKER.submit(self._warm_blocking).result()

    def _ensure_model(self) -> None:
        self.warm_up()

    async def transcribe(self, audio: AsyncIterator[AudioChunk]) -> Transcript:
        pieces: list[np.ndarray] = []
        sample_rate = _SAMPLE_RATE
        async for chunk in audio:
            pieces.append(pcm_bytes_to_np(chunk.pcm))
            sample_rate = chunk.sample_rate
        if not pieces:
            return Transcript(text="", language="unknown", confidence=0.0)
        return await self._decode(np.concatenate(pieces), sample_rate, None)

    async def transcribe_pcm(
        self,
        pcm_bytes: bytes,
        sample_rate: int = _SAMPLE_RATE,
        language: str | None = None,
    ) -> Transcript:
        return await self._decode(pcm_bytes_to_np(pcm_bytes), sample_rate, language)

    async def stream_transcribe(
        self, audio: AsyncIterator[AudioChunk]
    ) -> AsyncIterator[Transcript]:
        yield await self.transcribe(audio)

    def _language_for(self, per_call: str | None) -> str | None:
        if per_call is None or not str(per_call).strip():
            return self._language
        value = str(per_call).strip()
        return None if value.lower() == AUTO_LANGUAGE else value

    @staticmethod
    def _prepare(samples: np.ndarray, sample_rate: int) -> np.ndarray:
        audio = np.asarray(samples, dtype=np.float32)
        if audio.size and np.max(np.abs(audio)) > 1.0:
            audio = audio / _INT16_FULL_SCALE
        if sample_rate != _SAMPLE_RATE and audio.size:
            length = round(audio.size * _SAMPLE_RATE / sample_rate)
            positions = np.linspace(0, audio.size - 1, length)
            audio = np.interp(positions, np.arange(audio.size), audio).astype(np.float32)
        return audio

    async def _decode(
        self, samples: np.ndarray, sample_rate: int, per_call_language: str | None
    ) -> Transcript:
        if samples.size == 0:
            return Transcript(text="", language="unknown", confidence=0.0)
        language = self._language_for(per_call_language)
        audio = self._prepare(samples, sample_rate)
        loop = asyncio.get_running_loop()
        started = time.monotonic()
        result = await loop.run_in_executor(_WORKER, self._run, audio, language)
        _WARM_MODELS.add(self._model)
        record_timing(
            "stt",
            ms=round((time.monotonic() - started) * 1000),
            audio_s=round(audio.size / _SAMPLE_RATE, 2),
        )

        from dodaios.plugins.stt.transcript_filter import clean_stt_text

        segments = result.get("segments") or []
        spoken = [
            s for s in segments if float(s.get("no_speech_prob", 0.0)) <= _NO_SPEECH_LIMIT
        ]
        raw = str(result.get("text") or "").strip()
        if segments and not spoken:
            raw = ""
        text = clean_stt_text(raw, language=language)
        logprobs = [float(s["avg_logprob"]) for s in spoken if "avg_logprob" in s]
        confidence = 0.0
        if text:
            confidence = math.exp(sum(logprobs) / len(logprobs)) if logprobs else 1.0
        return Transcript(
            text=text,
            raw_text=raw,
            language=language or str(result.get("language") or "auto"),
            confidence=min(confidence, 1.0),
        )

    async def aclose(self) -> None:
        """The engine is shared by the process, so one closed call keeps it loaded."""
