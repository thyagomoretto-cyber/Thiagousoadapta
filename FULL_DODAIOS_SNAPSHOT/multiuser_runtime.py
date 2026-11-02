from __future__ import annotations
import json
from pathlib import Path

STATE = Path.home()/".dodaios"
GLOBAL = STATE/"global"
PROFILES = STATE/"profiles"
ACTIVE = STATE/"active_profile.json"

def active_profile_id() -> str:
    try:
        return json.loads(ACTIVE.read_text()).get("profile_id", "thiago")
    except Exception:
        return "thiago"

def profile_dir() -> Path:
    return PROFILES/active_profile_id()

def native_rules() -> list[str]:
    try:
        return list(json.loads((GLOBAL/"native_rules.json").read_text()).get("rules", []))
    except Exception:
        return []

def profile_rules() -> list[str]:
    try:
        return list(json.loads((profile_dir()/"rules.json").read_text()).get("rules", []))
    except Exception:
        return []

def merged_rules() -> list[str]:
    return native_rules() + profile_rules()
