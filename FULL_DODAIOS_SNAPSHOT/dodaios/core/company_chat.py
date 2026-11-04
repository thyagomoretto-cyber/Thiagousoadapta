"""Conversa do dono com a empresa, guardada por empresa fora do repositorio."""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

MAX_MESSAGES: Final[int] = 300
_LOCK = threading.Lock()


def _path(company_id: str) -> Path:
    from dodaios.core.paths import user_data_dir

    return user_data_dir() / "data" / "company_chat" / f"{re.sub(r'[^a-zA-Z0-9_-]', '-', company_id)[:80]}.json"


def history(company_id: str) -> list[dict[str, Any]]:
    try:
        return json.loads(_path(company_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def add(company_id: str, author: str, text: str, **extra: Any) -> None:
    path = _path(company_id)
    message = {"quem": author, "texto": text, "quando": datetime.now(UTC).isoformat(timespec="seconds"), **extra}
    with _LOCK:
        messages = [*history(company_id), message][-MAX_MESSAGES:]
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        with os.fdopen(handle, "w", encoding="utf-8") as output:
            json.dump(messages, output, ensure_ascii=False)
        os.replace(temporary, path)
