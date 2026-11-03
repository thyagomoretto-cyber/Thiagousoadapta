from __future__ import annotations

import json
from pathlib import Path

STATE = Path.home() / ".dodaios"
GLOBAL = STATE / "global"
PROFILES = STATE / "profiles"
ACTIVE = STATE / "active_profile.json"
MULTIUSER = GLOBAL / "multiuser.json"
NATIVE_RULES = GLOBAL / "native_rules.json"


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def active_profile_id() -> str:
    data = _read_json(ACTIVE, {})
    return str(data.get("profile_id") or "thiago")


def administrator_profile_id() -> str:
    data = _read_json(MULTIUSER, {})
    return str(data.get("administrator_profile") or "thiago")


def active_profile_role() -> str:
    pid = active_profile_id()
    data = _read_json(PROFILES / pid / "profile.json", {})
    return str(data.get("role") or ("administrator" if pid == administrator_profile_id() else "user"))


def native_rules() -> list[str]:
    data = _read_json(NATIVE_RULES, {})
    rows = data.get("rules", [])
    if not isinstance(rows, list):
        return []
    return [str(x).strip() for x in rows if str(x).strip()]


def profile_rules(profile_id: str | None = None) -> list[str]:
    pid = profile_id or active_profile_id()
    data = _read_json(PROFILES / pid / "rules.json", {})
    rows = data.get("rules", [])
    if not isinstance(rows, list):
        return []
    return [str(x).strip() for x in rows if str(x).strip()]


def merged_rules(profile_id: str | None = None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for rule in native_rules() + profile_rules(profile_id):
        rule = rule.strip()
        if rule and rule not in seen:
            seen.add(rule)
            result.append(rule)

    return result


def rules_prompt(profile_id: str | None = None) -> str:
    rules = merged_rules(profile_id)
    if not rules:
        return ""

    body = "\n".join(f"- {rule}" for rule in rules)

    return (
        "REGRAS PERMANENTES DO DODAIOS\n"
        "Estas regras fazem parte da configuração persistente do aplicativo. "
        "As regras globais têm precedência sobre preferências comuns do perfil.\n\n"
        f"{body}"
    )


def prepend_rules(prompt: str, profile_id: str | None = None) -> str:
    rules = rules_prompt(profile_id)
    prompt = prompt or ""

    if not rules:
        return prompt

    if rules in prompt:
        return prompt

    if not prompt:
        return rules

    return rules + "\n\n" + prompt
