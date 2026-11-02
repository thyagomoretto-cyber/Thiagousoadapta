from __future__ import annotations
import subprocess

import json
import os
import re
import unicodedata

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


router = APIRouter(prefix="/api/multiuser", tags=["multiuser"])

STATE = Path.home() / ".dodaios"
PROFILES = STATE / "profiles"
ACTIVE = STATE / "active_profile.json"


def safe_id(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-z0-9_-]+", "-", value.strip().lower()).strip("-")
    return value or "usuario"


def load_profiles():
    rows = []

    if not PROFILES.exists():
        return rows

    for directory in sorted(PROFILES.iterdir()):
        profile_file = directory / "profile.json"

        if not directory.is_dir() or not profile_file.exists():
            continue

        try:
            data = json.loads(profile_file.read_text())

            rows.append({
                "id": data.get("id", directory.name),
                "display_name": data.get("display_name", directory.name),
                "role": data.get("role", "user"),
            })

        except Exception:
            continue

    return rows


def current_profile():
    try:
        return json.loads(ACTIVE.read_text()).get("profile_id", "thiago")
    except Exception:
        return "thiago"


def activate(profile_id: str):
    profile_dir = PROFILES / profile_id
    profile_file = profile_dir / "profile.json"

    if not profile_file.exists():
        raise HTTPException(status_code=404, detail="Perfil inexistente.")

    ACTIVE.write_text(
        json.dumps(
            {
                "profile_id": profile_id,
                "selected_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n"
    )

    ACTIVE.chmod(0o600)

    # Atualiza tambÃ©m o ambiente do processo atual.
    os.environ["DODAIOS_MULTIUSER"] = "1"
    os.environ["DODAIOS_PROFILE"] = profile_id
    os.environ["DODAIOS_PROFILE_DIR"] = str(profile_dir)

    return profile_id


@router.get("")
async def get_profiles():
    return {
        "profiles": load_profiles(),
        "active": current_profile(),
    }


class SelectProfile(BaseModel):
    profile_id: str


@router.post("/select")
async def select_profile(payload: SelectProfile):
    profile_id = activate(payload.profile_id.strip())

    return {
        "ok": True,
        "profile_id": profile_id,
    }


class CreateProfile(BaseModel):
    display_name: str
    role: Literal["user", "administrator"] = "user"


@router.post("/create")
async def create_profile(payload: CreateProfile):
    name = payload.display_name.strip()

    if not name:
        raise HTTPException(status_code=400, detail="Informe o nome do usuÃ¡rio.")

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

    (directory / "profile.json").write_text(
        json.dumps(profile, ensure_ascii=False, indent=2) + "\n"
    )

    (directory / "rules.json").write_text(
        '{"schema_version":1,"rules":[]}\n'
    )

    (directory / "preferences.json").write_text(
        '{"schema_version":1,"preferences":{}}\n'
    )

    (directory / "computers.json").write_text(
        '{"schema_version":1,"computers":[]}\n'
    )

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
    """Reinicia a instÃ¢ncia local do DodaiOS pelo LaunchAgent do macOS."""
    import os

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


