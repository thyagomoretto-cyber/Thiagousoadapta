"""Archive continuous transcripts without inventing provider turn boundaries."""

from __future__ import annotations

import asyncio
from uuid import uuid4

from dodaios.core.events import VoiceSessionEnded, VoiceTurnCompleted, VoiceTurnStarted


async def publish_completed_text(session) -> None:
    """Mirror completed speech promptly and consume each ledger fragment once."""
    if session._ledger is None or session._bus is None:
        return
    fragments = await asyncio.to_thread(session._ledger.transcript, session.session_id)
    cursor = getattr(session, "_archived_fragment_count", 0)
    pending = fragments[cursor:]
    text = {
        role: " ".join(f["delta"] for f in pending if f["role"] == role)
        if role == "user" else "".join(f["delta"] for f in pending if f["role"] == role)
        for role in ("user", "assistant")
    }
    if any(text.values()):
        if cursor:
            await session._bus.publish(VoiceTurnStarted(
                session_id=session.session_id, turn_id=session._archive_turn_id,
            ))
        await session._bus.publish(
            VoiceTurnCompleted(
                session_id=session.session_id,
                turn_id=session._archive_turn_id,
                user_text=text["user"],
                jarvis_text=text["assistant"],
                user_lang=session._language,
                jarvis_lang=session._language,
                provider=session.active_provider,
                model=session._active_model,
                tier="realtime",
            )
        )
        session._archived_fragment_count = len(fragments)
        session._archive_turn_id = str(uuid4())


async def archive_session(session, reason: str) -> None:
    """Flush any interrupted remainder before closing the recorded session."""
    if session._ledger is None or session._bus is None:
        return
    await publish_completed_text(session)
    await session._bus.publish(
        VoiceSessionEnded(
            session_id=session.session_id,
            hangup_reason=reason,
            duration_s=session._voice_seconds,
        )
    )
