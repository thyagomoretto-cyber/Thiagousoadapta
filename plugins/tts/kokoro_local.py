from __future__ import annotations

import asyncio
import queue
import threading
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Any

import numpy as np

from dodaios.core.protocols import AudioChunk


_INT16_FULL_SCALE = 32767.0


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

        self._engine: Any | None = None
        self._load_lock = threading.Lock()

        # Pré-carrega o Kokoro/Santa em segundo plano assim que o provider nasce.
        # Isso elimina boa parte da espera antes da primeira fala.
        threading.Thread(
            target=self._load_engine_sync,
            name="kokoro-prewarm",
            daemon=True,
        ).start()

    def _load_engine_sync(self) -> Any:
        if self._engine is not None:
            return self._engine

        with self._load_lock:
            if self._engine is None:
                from kokoro_mlx import KokoroTTS
                self._engine = KokoroTTS.from_pretrained()

        return self._engine

    async def _get_engine(self) -> Any:
        if self._engine is not None:
            return self._engine

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
                for samples in engine.generate_stream(
                    spoken,
                    voice=selected_voice,
                    speed=self._speed,
                    sample_rate=self._sample_rate,
                    language=lang,
                ):
                    if stopped.is_set():
                        break

                    data = self._pcm(samples)
                    if data and not put(data):
                        break

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

                yield AudioChunk(
                    pcm=item,
                    sample_rate=self._sample_rate,
                    timestamp_ns=0,
                    channels=1,
                )

            await worker

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
        engine = self._engine
        self._engine = None

        if engine is not None:
            close = getattr(engine, "close", None)
            if callable(close):
                await asyncio.to_thread(close)
