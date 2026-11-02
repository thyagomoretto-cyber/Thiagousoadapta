"""Voice is another input/output surface of the person's existing chat."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any

from dodaios.agent_chat.send_queue import send_or_queue
from dodaios.agent_chat.voice_mirror import VoiceChatMirror

log = logging.getLogger(__name__)
_resolve_service: Callable[[], Any] | None = None


def set_service_resolver(resolver: Callable[[], Any] | None) -> None:
    """Register the same lazy service factory used by the typed chat routes."""
    global _resolve_service
    _resolve_service = resolver


class VoiceChatExecution:
    def __init__(
        self,
        service: Any,
        call_id: str,
        chat_id: str,
        speak: Callable[[str], Awaitable[bool | None]],
    ) -> None:
        self.service = service
        self.call_id = call_id
        self.chat_id = chat_id
        self.speak = speak
        self._closed = False
        self._seen_inputs: set[str] = set()
        self._blocks: dict[str, dict[str, str]] = {}
        self._spoken_turns: set[str] = set()
        self._asked_approval: str | None = None
        self._question_card: dict | None = None
        self._queue = service.subscribe(chat_id)
        self._listener = asyncio.create_task(self._listen(), name="voice-chat-replies")

    @classmethod
    async def open(cls, call_id: str, speak: Callable[[str], Awaitable[bool | None]]):
        if _resolve_service is None:
            raise RuntimeError("The chat execution service is not registered.")
        from dodaios.agent_chat.service import remember_app_loop

        remember_app_loop()
        service = await asyncio.to_thread(_resolve_service)
        if service is None:
            raise RuntimeError("The chat execution service is unavailable.")
        archived = getattr(service, "voice_session_continued", None)
        history = service.voice_chat_history() if archived else []
        session = VoiceChatMirror._target_session(service, call_id) if not archived else None
        if session is None:
            session = VoiceChatMirror._ensure_session(service, SimpleNamespace(provider=""))
            if session is None:
                raise RuntimeError("No chat is available for the voice request.")
            for item in history:
                if isinstance(item, tuple) and len(item) == 2:
                    item = {"role": item[0], "content": item[1]}
                role = item.get("role") if isinstance(item, dict) else getattr(item, "role", "")
                text = (
                    item.get("content", item.get("text", ""))
                    if isinstance(item, dict)
                    else getattr(item, "content", getattr(item, "text", ""))
                )
                if role in {"user", "assistant"} and text:
                    await service.import_voice_turn(
                        session.session_id,
                        str(text) if role == "user" else "",
                        str(text) if role == "assistant" else "",
                    )
            service.bind_voice_chat(session.session_id)
            if archived:
                from dodaios.core.paths import user_data_dir
                from dodaios.live.state import LiveLedger

                ledger = LiveLedger(user_data_dir() / "live.sqlite3")
                try:
                    ledger.bind_chat(archived, session.session_id)
                finally:
                    ledger.close()
        calls = getattr(service, "_voice_execution_calls", None)
        if calls is None:
            calls = service._voice_execution_calls = set()
        calls.add(call_id)
        service.pin_voice_call(call_id, session.session_id)
        return cls(service, call_id, session.session_id, speak)

    async def submit(self, text: str, input_id: str) -> None:
        """Submit the exact transcript once, with the typed route's defaults."""
        if self._closed or input_id in self._seen_inputs or not text.strip():
            return
        self._seen_inputs.add(input_id)
        # Only a separate explicit answer to the single approval we actually
        # presented can resolve its existing card. No rule or policy changes.
        if self._asked_approval:
            answer = re.sub(r"[.!?]", "", text).strip().casefold()
            decision = (
                "allow"
                if answer in {"sim", "yes", "ja", "sí", "si"}
                else "deny"
                if answer in {"não", "nao", "no", "nein"}
                else ""
            )
            approval = self._asked_approval
            self._asked_approval = None
            pending = self.service.pending_approvals(self.chat_id)
            if (
                decision
                and pending == [approval]
                and self.service.resolve_approval(self.chat_id, approval, decision)
            ):
                from dodaios.agent_chat.events import make_event

                await self.service._emit(self.chat_id, make_event("user_message", {"text": text}))
                return
        if self._question_card or self.service.pending_questions(self.chat_id):
            outcome = await self.service.answer_by_message(self.chat_id, text)
            if outcome.get("consumed"):
                return
        await send_or_queue(self.service, self.chat_id, text)
        # The first input has now reached the ledger, allowing the existing
        # persistent recording-to-chat link to be established as well.
        self.service.pin_voice_call(self.call_id, self.chat_id)

    async def _listen(self) -> None:
        while not self._closed:
            event = await self._queue.get()
            payload = event.get("payload") or {}
            if payload.get("agent_id"):
                continue
            kind = event.get("kind")
            turn = str(payload.get("turn_id") or "")
            if kind == "assistant_text":
                self._blocks.setdefault(turn, {})[str(payload.get("message_id") or "reply")] = str(
                    payload.get("text") or ""
                )
            elif kind == "approval_required":
                question = str(payload.get("summary") or "")
                if question:
                    if await self._say(question):
                        self._asked_approval = str(payload.get("approval_id") or "")
            elif kind == "question_required":
                self._question_card = payload
                await self._read_question(0)
            elif kind == "question_progress" and self._question_card:
                answers = payload.get("answers") or []
                remaining = next((i for i, answer in enumerate(answers) if answer is None), None)
                if remaining is not None:
                    await self._read_question(remaining)
            elif kind == "question_resolved":
                if self._question_card and self._question_card.get("question_id") == payload.get(
                    "question_id"
                ):
                    self._question_card = None
            elif kind == "credential_required":
                await self._say("Preciso que preenchas o campo protegido que aparece no chat.")
            elif kind == "approval_resolved":
                if self._asked_approval == payload.get("approval_id"):
                    self._asked_approval = None
            elif kind == "turn_finished" and turn not in self._spoken_turns:
                self._spoken_turns.add(turn)
                blocks = self._blocks.pop(turn, {})
                reply = "\n\n".join(blocks.values()).strip()
                if payload.get("status") == "error":
                    reply = str(
                        payload.get("error")
                        or "O pedido não foi concluído. Consulta o motivo no chat."
                    )
                if reply and payload.get("status") != "cancelled":
                    await self._say(reply)

    async def _read_question(self, index: int) -> None:
        questions = (self._question_card or {}).get("questions") or []
        if index >= len(questions):
            return
        spec = questions[index]
        text = str(spec.get("question") or "")
        options = [str(option.get("label") or "") for option in spec.get("options") or []]
        if options:
            text += " " + "; ".join(options) + "."
        if text.strip():
            await self._say(text)

    async def _say(self, text: str) -> bool:
        try:
            return await self.speak(text) is not False
        except asyncio.CancelledError:
            raise
        except Exception:
            # The persisted chat is authoritative. Never re-execute an action
            # because its spoken readback failed.
            log.warning("Voice readback failed; the chat result is retained", exc_info=True)
            return False

    async def close(self) -> None:
        self._closed = True
        self.service.unsubscribe(self.chat_id, self._queue)
        self._listener.cancel()
        await asyncio.gather(self._listener, return_exceptions=True)
        # Closing the microphone does not cancel accepted chat work, discard
        # queued messages, resolve approvals, or reassign the user's model.
