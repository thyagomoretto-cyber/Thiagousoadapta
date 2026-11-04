"""Sessao de ensino ao vivo, rodando no servidor do app.

O microfone do painel para quando outra janela fica na frente, entao aqui a
escuta e a execucao nao dependem da janela do DodaiOS. Do inicio ate "finalizar
aprendizado" ele ouve, executa, observa os cliques e registra na habilidade.
"""
from __future__ import annotations

import asyncio
import logging
import math
import queue
import re
import struct
import subprocess
import threading
import time
from typing import Any, Final

from dodaios.core import company_skills, live_actions, screen_control

log = logging.getLogger(__name__)

SAMPLE_RATE: Final[int] = 16_000
_BLOCK: Final[int] = 1_600
_SPEECH_LEVEL: Final[float] = 0.015
_END_SILENCE_S: Final[float] = 0.8
_MAX_SPEECH_S: Final[float] = 30.0
_MIN_SPEECH_S: Final[float] = 0.25
_NOTE = re.compile(r"^\W*(?:agora\s+)?(?:anote|anota|lembre|lembra|aprenda|aprende|registre|registra)\s+(?:que\s+)?(.+)$", re.I)
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


_tts: Any = None


async def _play_with_app_voice(text: str) -> None:
    """Fala com a mesma voz das conversas do app."""
    global _tts
    import sounddevice

    if _tts is None:
        from dodaios.core.config import load_config
        from dodaios.plugins.tts import build_tts_from_config

        _tts = build_tts_from_config(load_config().tts)
    output = None
    try:
        async for chunk in _tts.synthesize(text, language_code="pt-BR"):
            if output is None:
                output = sounddevice.RawOutputStream(samplerate=chunk.sample_rate, channels=1, dtype="int16")
                output.start()
            output.write(chunk.pcm)
    finally:
        if output is not None:
            output.stop()
            output.close()


def _portuguese_voice() -> list[str]:
    """Reserva: a voz do sistema em portugues, se a do app falhar."""
    listed = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=10).stdout
    for line in listed.splitlines():
        if "pt_BR" in line:
            return ["-v", line.split("  ")[0].strip()]
    return []


_VOICE: list[str] | None = None


def _spoken_step(step: str) -> str:
    """O passo como ele diria numa conversa."""
    for pattern, sentence in (
        (r'^Abrir o aplicativo (.+)$', r"Abri o \1."),
        (r"^Abrir https?://.+$", "Abri o site."),
        (r'^Clicar em "(.+)"$', r"Cliquei em \1."),
        (r'^Digitar ".+"$', "Digitei."),
        (r"^Apertar (.+)$", r"Apertei \1."),
        (r"^Rolar para (.+)$", r"Rolei para \1."),
    ):
        if re.match(pattern, step):
            return re.sub(pattern, sentence, step)
    return "Pronto."


def _say(text: str) -> None:
    global _VOICE
    try:
        asyncio.run(_play_with_app_voice(text[:400]))
        return
    except Exception as exc:  # noqa: BLE001 — a conversa segue com a voz do sistema
        log.warning("Voz do app indisponivel no ensino: %s", exc)
    if _VOICE is None:
        _VOICE = _portuguese_voice()
    subprocess.run(["say", *_VOICE, text[:400]], capture_output=True, timeout=60)


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

    def speak(self, text: str) -> None:
        """Fala uma resposta do assistente, com o microfone em pausa."""
        if self.live:
            self._speak(text)

    def _learn_decision(self, decision: str) -> None:
        """Guarda a frase do dono como ela foi dita, sem passar pelo modelo."""
        skill = company_skills.get_skill(self.company_id, self.skill_id)
        known = skill.get("conditions") or []
        if decision not in known:
            company_skills.update_skill(
                self.company_id, self.skill_id, {"conditions": [*known, decision]}, "Decisao ensinada por voz"
            )
        self._note("Observei", f"Decisão: {decision}")
        self._speak("Anotado.")

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
        note = _NOTE.match(text)
        if note:
            self._learn_decision(note.group(1).strip().rstrip("."))
            return
        if self.pending_link and re.search(r"\b(cancela|cancelar|deixa|esquece)\b", text, re.I):
            self.pending_link = ""
            self._note("Ele", "Certo, deixei de lado.")
            self._speak("Certo.")
            return
        result = live_actions.act(text, self.pending_link)
        if not result.get("needs_link"):
            self.pending_link = ""
        if result.get("failed"):
            self._note("Ele", result["failed"])
            self._speak(result["failed"])
        elif result.get("done"):
            self.pending_link = ""
            self._note("Ele", f"Feito: {result['step']}")
            self._record(result["step"])
            self._speak(_spoken_step(result["step"]))
        elif result.get("needs_link"):
            self.pending_link = result["needs_link"]
            question = f"Qual é o endereço do {self.pending_link}?"
            if result.get("again"):
                question = f"Não entendi o endereço do {self.pending_link}. Fale, por exemplo: kenlo ponto com ponto br."
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
