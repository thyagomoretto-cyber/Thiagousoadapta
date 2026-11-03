from __future__ import annotations

import asyncio
import queue
import re
import threading
import time
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Any

import numpy as np

from dodaios.core.protocols import AudioChunk
from dodaios.speech.local_voice import MLX_WARM_GATE, record_timing


_INT16_FULL_SCALE = 32767.0

# One engine per process. Each voice call builds a new provider, and an engine
# per call would stack a loaded model on memory at every reconnect.
_ENGINE: Any | None = None
_ENGINE_LOCK = threading.Lock()
_WARM_DONE = threading.Event()

# kokoro-mlx returns a whole text as one block, so the time to the first sound
# grows with the reply. Measured 2026-11-03 on an M1: 170 characters took 4.7 s
# and the audio arrived 40 ms before the end. Speaking in short parts makes the
# first sound depend on the first part only.
_SENTENCE_END = re.compile(r"(?<=[.!?…;:])\s+")
_PART_LIMIT = 90


def _speakable_parts(text: str) -> list[str]:
    """Split a reply at sentence ends, then long sentences at a comma or space."""
    parts: list[str] = []
    for sentence in _SENTENCE_END.split(text.strip()):
        rest = sentence.strip()
        while len(rest) > _PART_LIMIT:
            cut = rest.rfind(", ", 0, _PART_LIMIT)
            if cut < 30:
                cut = rest.rfind(" ", 0, _PART_LIMIT)
            if cut <= 0:
                break
            parts.append(rest[: cut + 1].strip())
            rest = rest[cut + 1 :].strip()
        if rest:
            parts.append(rest)
    return parts


class KokoroLocalTTS:
    name = "kokoro-local"
    supports_streaming = True
    runs_on_device = True

    last_voice: str | None = None
    last_voice_provider: str | None = None

    def __init__(
        self,
        *,
        voice: str = "pm_santa",
        speed: float = 1.0,
        language: str = "pt",
        sample_rate: int = 24000,
    ) -> None:
        self._voice = voice or "pm_santa"
        self._speed = float(speed or 1.0)
        self._language = language or "pt"
        self._sample_rate = int(sample_rate or 24000)

        # Pré-carrega o Kokoro/Santa em segundo plano assim que o provider nasce.
        # Isso elimina boa parte da espera antes da primeira fala.
        threading.Thread(
            target=self._prewarm,
            name="kokoro-prewarm",
            daemon=True,
        ).start()

    def _load_engine_sync(self) -> Any:
        global _ENGINE
        if _ENGINE is not None:
            return _ENGINE

        with _ENGINE_LOCK:
            if _ENGINE is None:
                from kokoro_mlx import KokoroTTS
                _ENGINE = KokoroTTS.from_pretrained()

        return _ENGINE

    def _prewarm(self) -> None:
        """Load the engine and speak once, so the first real reply starts warm."""
        if _WARM_DONE.is_set():
            return
        started = time.monotonic()
        try:
            with MLX_WARM_GATE:
                engine = self._load_engine_sync()
                if _WARM_DONE.is_set():
                    return
                for _samples in engine.generate_stream(
                    "Pronto.",
                    voice=self._voice,
                    speed=self._speed,
                    sample_rate=self._sample_rate,
                    language=self._language,
                ):
                    pass
            _WARM_DONE.set()
            record_timing("tts_warm", ms=round((time.monotonic() - started) * 1000))
        except Exception as exc:  # noqa: BLE001 — the first reply reports it
            record_timing("tts_warm_failed", error=str(exc)[:200])

    async def _get_engine(self) -> Any:
        if _ENGINE is not None:
            return _ENGINE

        return await asyncio.to_thread(self._load_engine_sync)

    @staticmethod
    def _pcm(samples: Any) -> bytes:
        values = np.asarray(samples, dtype=np.float32).reshape(-1)
        if values.size == 0:
            return b""

        values = np.clip(values, -1.0, 1.0)
        return (values * _INT16_FULL_SCALE).astype(np.int16).tobytes()

    async def synthesize(
        self,
        text: str,
        voice: str | None = None,
        language_code: str | None = None,
    ) -> AsyncIterator[AudioChunk]:

        spoken = (text or "").strip()
        if not spoken:
            return

        started = time.monotonic()
        first_ms: int | None = None
        engine = await self._get_engine()

        selected_voice = (voice or "").strip()
        if not selected_voice.startswith(("pm_", "pf_")):
            selected_voice = self._voice

        lang = self._language
        if language_code:
            short = language_code.lower().split("-", 1)[0]
            if short == "pt":
                lang = "pt"

        chunks: queue.Queue[bytes | object] = queue.Queue(maxsize=12)
        end = object()
        stopped = threading.Event()
        failure: list[Exception] = []

        def put(value: bytes | object) -> bool:
            while not stopped.is_set():
                try:
                    chunks.put(value, timeout=0.05)
                    return True
                except queue.Full:
                    continue
            return False

        def generate() -> None:
            try:
                for part in _speakable_parts(spoken):
                    for samples in engine.generate_stream(
                        part,
                        voice=selected_voice,
                        speed=self._speed,
                        sample_rate=self._sample_rate,
                        language=lang,
                    ):
                        if stopped.is_set():
                            return

                        data = self._pcm(samples)
                        if data and not put(data):
                            return

            except Exception as exc:
                failure.append(exc)

            finally:
                put(end)

        worker = asyncio.create_task(
            asyncio.to_thread(generate),
            name="kokoro-local-tts",
        )

        self.last_voice = selected_voice
        self.last_voice_provider = self.name

        try:
            while True:
                item = await asyncio.to_thread(chunks.get)

                if item is end:
                    break

                if first_ms is None:
                    first_ms = round((time.monotonic() - started) * 1000)

                yield AudioChunk(
                    pcm=item,
                    sample_rate=self._sample_rate,
                    timestamp_ns=0,
                    channels=1,
                )

            await worker
            record_timing(
                "tts",
                first_audio_ms=first_ms,
                total_ms=round((time.monotonic() - started) * 1000),
                chars=len(spoken),
            )

            if failure:
                raise failure[0]

        finally:
            stopped.set()

            if not worker.done():
                with suppress(TimeoutError):
                    await asyncio.wait_for(
                        asyncio.shield(worker),
                        timeout=1.0,
                    )

    async def _ensure_client(self) -> None:
        await self._get_engine()

    async def aclose(self) -> None:
        """The engine is shared by the process, so one closed call keeps it loaded."""
