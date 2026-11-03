from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/multiuser", tags=["multiuser"])

STATE = Path.home() / ".dodaios"
PROFILES = STATE / "profiles"
ACTIVE = STATE / "active_profile.json"

_PROFILE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def safe_id(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-z0-9_-]+", "-", value.strip().lower()).strip("-")
    return value or "usuario"


def read_json(path: Path) -> Any:
    """Le JSON com ou sem BOM, inclusive arquivos antigos gravados em cp1252."""
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    return json.loads(text)


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def load_profiles():
    rows = []

    if not PROFILES.exists():
        return rows

    try:
        directories = sorted(PROFILES.iterdir())
    except OSError as exc:
        log.warning("Perfis inacessiveis em %s: %s", PROFILES, exc)
        raise HTTPException(
            status_code=503,
            detail="A pasta de perfis esta inacessivel.",
        ) from exc

    for directory in directories:
        profile_file = directory / "profile.json"

        try:
            if not directory.is_dir() or not profile_file.exists():
                continue

            data = read_json(profile_file)

            rows.append({
                "id": data.get("id", directory.name),
                "display_name": data.get("display_name", directory.name),
                "role": data.get("role", "user"),
            })

        except (OSError, ValueError, AttributeError) as exc:
            log.warning("Perfil ignorado (%s): %s", directory.name, exc)

    return rows


def current_profile():
    try:
        return read_json(ACTIVE).get("profile_id", "thiago")
    except (OSError, ValueError, AttributeError):
        return "thiago"


def activate(profile_id: str):
    if not _PROFILE_ID.fullmatch(profile_id):
        raise HTTPException(status_code=400, detail="Perfil invalido.")

    profile_dir = PROFILES / profile_id
    profile_file = profile_dir / "profile.json"

    if not profile_file.exists():
        raise HTTPException(status_code=404, detail="Perfil inexistente.")

    write_text(
        ACTIVE,
        json.dumps(
            {
                "profile_id": profile_id,
                "selected_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
    )

    try:
        ACTIVE.chmod(0o600)
    except OSError as exc:
        log.debug("chmod ignorado em %s: %s", ACTIVE, exc)

    # Atualiza também o ambiente do processo atual.
    os.environ["DODAIOS_MULTIUSER"] = "1"
    os.environ["DODAIOS_PROFILE"] = profile_id
    os.environ["DODAIOS_PROFILE_DIR"] = str(profile_dir)

    return profile_id


@router.get("")
def get_profiles():
    return {
        "profiles": load_profiles(),
        "active": current_profile(),
    }


class SelectProfile(BaseModel):
    profile_id: str


@router.post("/select")
def select_profile(payload: SelectProfile):
    profile_id = activate(payload.profile_id.strip())

    return {
        "ok": True,
        "profile_id": profile_id,
    }


class CreateProfile(BaseModel):
    display_name: str
    role: Literal["user", "administrator"] = "user"


@router.post("/create")
def create_profile(payload: CreateProfile):
    # O primeiro perfil de uma instalacao nova ainda nao tem administrador.
    if load_profiles():
        from .ja_update_auth import require_update_administrator

        require_update_administrator()

    name = payload.display_name.strip()

    if not name:
        raise HTTPException(status_code=400, detail="Informe o nome do usuário.")

    profile_id = safe_id(name)
    base_id = profile_id
    number = 2

    while (PROFILES / profile_id).exists():
        profile_id = f"{base_id}-{number}"
        number += 1

    directory = PROFILES / profile_id

    (directory / "memory").mkdir(parents=True, exist_ok=True)
    (directory / "automations").mkdir(parents=True, exist_ok=True)

    profile = {
        "schema_version": 1,
        "id": profile_id,
        "display_name": name,
        "role": payload.role,
        "can_manage_all_profiles": payload.role == "administrator",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    write_text(
        directory / "profile.json",
        json.dumps(profile, ensure_ascii=False, indent=2) + "\n",
    )
    write_text(directory / "rules.json", '{"schema_version":1,"rules":[]}\n')
    write_text(directory / "preferences.json", '{"schema_version":1,"preferences":{}}\n')
    write_text(directory / "computers.json", '{"schema_version":1,"computers":[]}\n')

    return {
        "ok": True,
        "profile": {
            "id": profile_id,
            "display_name": name,
            "role": payload.role,
        },
    }


@router.post("/restart")
def restart_dodaios():
    """Reinicia a instância local do DodaiOS pelo LaunchAgent do macOS."""
    if sys.platform != "darwin":
        raise HTTPException(
            status_code=501,
            detail="Neste sistema use /api/settings/restart-app.",
        )

    uid = os.getuid()

    command = (
        "sleep 0.1; "
        f"/bin/launchctl kickstart -k gui/{uid}/com.personal-jarvis.autostart "
        ">/tmp/dodaios-restart.log 2>&1"
    )

    subprocess.Popen(
        ["/bin/bash", "-lc", command],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    return {"ok": True, "status": "restarting"}
