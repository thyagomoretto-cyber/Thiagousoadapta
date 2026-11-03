"""Sessao de ensino ao vivo, rodando no servidor do app.

O microfone do painel para quando outra janela fica na frente, entao aqui a
escuta e a execucao nao dependem da janela do DodaiOS. Do inicio ate "finalizar
aprendizado" ele ouve, executa, observa os cliques e registra na habilidade.
"""
from __future__ import annotations

import asyncio
import math
import queue
import re
import struct
import subprocess
import threading
import time
from typing import Any, Final

from dodaios.core import company_skills, live_actions, screen_control

SAMPLE_RATE: Final[int] = 16_000
_BLOCK: Final[int] = 1_600
_SPEECH_LEVEL: Final[float] = 0.015
_END_SILENCE_S: Final[float] = 0.8
_MAX_SPEECH_S: Final[float] = 30.0
_MIN_SPEECH_S: Final[float] = 0.25
_FINISH = re.compile(r"\b(finalizar|finaliza|encerrar|terminar)\s+(o\s+|a\s+)?aprend", re.I)


def _level(block: bytes) -> float:
    samples = struct.unpack(f"<{len(block) // 2}h", block)
    if not samples:
        return 0.0
    return math.sqrt(sum(value * value for value in samples) / len(samples)) / 32768.0


def _open_microphone() -> Any:
    import sounddevice

    return sounddevice.RawInputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=_BLOCK)


def microphone_level(seconds: float = 1.0) -> float:
    """O pico de um trecho curto. Zero costuma significar microfone sem permissao."""
    peak = 0.0
    with _open_microphone() as stream:
        for _ in range(int(seconds * SAMPLE_RATE / _BLOCK)):
            block, _overflow = stream.read(_BLOCK)
            peak = max(peak, _level(bytes(block)))
    return peak


def _say(text: str) -> None:
    subprocess.run(["say", text[:200]], capture_output=True, timeout=30)


class LiveTeach:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._reset("", "")

    def _reset(self, company_id: str, skill_id: str) -> None:
        self.company_id = company_id
        self.skill_id = skill_id
        self.live = False
        self.status = ""
        self.level = 0.0
        self.error = ""
        self.log: list[dict[str, str]] = []
        self.agent: list[str] = []
        self.pending_link = ""
        self.muted = False
        self._speech: queue.Queue[bytes | None] = queue.Queue()
        self._observed = 0

    def start(self, company_id: str, skill_id: str) -> None:
        with self._lock:
            if self.live:
                return
            self._reset(company_id, skill_id)
            self.live = True
        threading.Thread(target=self._listen, name="ensino-escuta", daemon=True).start()
        threading.Thread(target=self._work, name="ensino-execucao", daemon=True).start()
        threading.Thread(target=self._watch, name="ensino-cliques", daemon=True).start()

    def stop(self) -> None:
        self.live = False
        self.status = "Aprendizado finalizado."
        self._speech.put(None)

    def snapshot(self, since: int, agent_since: int) -> dict[str, Any]:
        return {
            "live": self.live,
            "status": self.status,
            "level": round(self.level, 3),
            "error": self.error,
            "log": self.log[since:],
            "total": len(self.log),
            "agent": self.agent[agent_since:],
            "agent_total": len(self.agent),
        }

    def _note(self, who: str, text: str) -> None:
        self.log.append({"who": who, "text": text})

    def _record(self, step: str) -> None:
        skill = company_skills.get_skill(self.company_id, self.skill_id)
        if step not in skill["steps"]:
            company_skills.update_skill(
                self.company_id, self.skill_id, {"steps": [*skill["steps"], step]}, "Aprendido ao vivo"
            )

    def _speak(self, text: str) -> None:
        self.muted = True
        try:
            _say(text)
        finally:
            self.muted = False

    def _listen(self) -> None:
        try:
            with _open_microphone() as stream:
                self._capture(stream)
        except Exception as exc:  # noqa: BLE001 — aparece no painel em vez de morrer calado
            self.error = f"Microfone: {exc}"
            self.live = False
            self._speech.put(None)

    def _capture(self, stream: Any) -> None:
        blocks: list[bytes] = []
        silent = 0.0
        seconds = _BLOCK / SAMPLE_RATE
        self.status = "Ouvindo e olhando sua tela. Diga finalizar aprendizado para encerrar."
        while self.live:
            data, _overflow = stream.read(_BLOCK)
            block = bytes(data)
            if self.muted:
                blocks, silent = [], 0.0
                continue
            self.level = _level(block)
            if self.level > _SPEECH_LEVEL:
                silent = 0.0
                blocks.append(block)
            elif blocks:
                silent += seconds
                blocks.append(block)
            spoken = len(blocks) * seconds
            if blocks and (silent >= _END_SILENCE_S or spoken >= _MAX_SPEECH_S):
                if spoken - silent >= _MIN_SPEECH_S:
                    self._speech.put(b"".join(blocks))
                blocks, silent = [], 0.0

    def _transcribe(self, recognizer: Any, audio: bytes) -> str:
        result = asyncio.run(recognizer.transcribe_pcm(audio, sample_rate=SAMPLE_RATE))
        return (getattr(result, "text", "") or "").strip()

    def _work(self) -> None:
        from dodaios.core.config import load_config
        from dodaios.plugins.stt import build_stt_from_config

        recognizer = build_stt_from_config(load_config().stt)
        while (audio := self._speech.get()) is not None:
            try:
                text = self._transcribe(recognizer, audio)
                if len(text) >= 3:
                    self._execute(text)
            except Exception as exc:  # noqa: BLE001 — um passo ruim nao encerra o ensino
                self.error = str(exc)[:200]

    def _execute(self, text: str) -> None:
        self._note("Você", text)
        if _FINISH.search(text):
            self.stop()
            return
        result = live_actions.act(text, self.pending_link)
        if result.get("failed"):
            self._note("Ele", result["failed"])
            self._speak(result["failed"])
        elif result.get("done"):
            self.pending_link = ""
            self._note("Ele", f"Feito: {result['step']}")
            self._record(result["step"])
        elif result.get("needs_link"):
            self.pending_link = result["needs_link"]
            question = f"Qual é o endereço de {self.pending_link}?"
            self._note("Ele", question)
            self._speak(question)
        else:
            self.agent.append(text)

    def _watch(self) -> None:
        observer = screen_control.OBSERVER
        try:
            observer.start()
        except Exception as exc:  # noqa: BLE001 — o ensino segue sem observar
            self.error = f"Observar cliques: {exc}"
            return
        seen = 0
        while self.live:
            time.sleep(1)
            steps = observer.steps_after(seen)
            seen += len(steps)
            for step in steps:
                self._note("Observei", step)
                try:
                    self._record(step)
                except (OSError, ValueError, company_skills.SkillNotFound) as exc:
                    self.error = str(exc)[:200]
        observer.stop()


SESSION: Final[LiveTeach] = LiveTeach()
