"""Shared helpers for the on-device voice engines: timing log and warm start.

The voice call path builds its recognizer and voice when a call opens. Loading
models then lands on the owner's first sentence, so ``warm_local_voice`` loads
them when the backend starts.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: One load or first decode at a time. Whisper and Kokoro both drive the Mac GPU
#: and warm up at the same moment, which is the one overlap this code can avoid.
MLX_WARM_GATE = threading.Lock()

_TIMING_FILE = Path.home() / ".dodaios" / "logs" / "voz-tempos.jsonl"
_TIMING_LIMIT_BYTES = 1_000_000

#: Memory MLX keeps resident for Whisper and Kokoro. On a Mac under memory
#: pressure the models were paged out between sentences, and a 3.4 s sentence
#: took 5 s to transcribe instead of 0.5 s.
_MLX_WIRED_BYTES = 1024 * 1024 * 1024
_MLX_CACHE_BYTES = 128 * 1024 * 1024


def keep_mlx_models_resident() -> None:
    """Ask MLX to keep loaded models in memory. Older systems simply skip this."""
    try:
        import mlx.core as mx

        mx.set_wired_limit(_MLX_WIRED_BYTES)
        mx.set_cache_limit(_MLX_CACHE_BYTES)
        record_timing("mlx_residente", wired_mb=_MLX_WIRED_BYTES // 1024 // 1024)
    except Exception as exc:  # noqa: BLE001 — an optimization, never a requirement
        record_timing("mlx_residente_falhou", error=str(exc)[:200])


def record_timing(event: str, **fields: Any) -> None:
    """Append one timing line. Measuring must never disturb the voice."""
    try:
        _TIMING_FILE.parent.mkdir(parents=True, exist_ok=True)
        if _TIMING_FILE.exists() and _TIMING_FILE.stat().st_size > _TIMING_LIMIT_BYTES:
            _TIMING_FILE.unlink()
        line = json.dumps({"t": round(time.time(), 3), "event": event, **fields}, ensure_ascii=False)
        with _TIMING_FILE.open("a", encoding="utf-8") as output:
            output.write(line + "\n")
    except OSError:
        pass


def warm_local_voice(cfg: Any) -> None:
    """Warm the Mac voice engines in the background; other engines are untouched."""
    uses_mlx = getattr(cfg.stt, "provider", "") == "mlx-whisper"
    uses_kokoro = getattr(cfg.tts, "provider", "") in ("kokoro-local", "kokoro", "kokoro-mlx")
    if not uses_mlx and not uses_kokoro:
        return

    def run() -> None:
        keep_mlx_models_resident()
        try:
            if uses_mlx:
                from dodaios.plugins.stt import build_stt_from_config

                recognizer = build_stt_from_config(cfg.stt, dictionary_bias=False)
                warm_up = getattr(recognizer, "warm_up", None)
                if callable(warm_up):
                    warm_up()
            if uses_kokoro:
                from dodaios.plugins.tts import build_tts_from_config

                build_tts_from_config(cfg.tts)
        except Exception as exc:  # noqa: BLE001 — the first sentence still lazy-loads
            log.warning("Local voice warm start failed: %s", exc)

    threading.Thread(target=run, name="local-voice-warm", daemon=True).start()
