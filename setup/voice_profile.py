"""Aplica o perfil de voz aprovado para o sistema desta maquina.

Cada plataforma tem seus motores e dependencias em ``voice_profiles.json``. O
perfil so e aplicado quando esta ``approved`` e quando sua versao ainda nao foi
aplicada aqui. Assim, um ajuste feito depois pelo usuario continua valendo ate
uma nova versao do perfil ser publicada.

    python -m dodaios.setup.voice_profile --check
    python -m dodaios.setup.voice_profile --apply
"""
from __future__ import annotations

import argparse
import json
import platform
import re
import shutil
import subprocess
import sys
import time
from importlib import metadata
from pathlib import Path
from typing import Any

PROFILES_FILE = Path(__file__).with_name("voice_profiles.json")
STATE_NAME = "voice-profile-state.json"


def platform_key(system: str | None = None, machine: str | None = None) -> str:
    system = system or sys.platform
    machine = (machine or platform.machine()).lower()
    architecture = "arm64" if machine in ("arm64", "aarch64") else "x64"
    name = {"darwin": "macos", "win32": "windows"}.get(system, system)
    return f"{name}-{architecture}"


def load_profile(key: str, path: Path = PROFILES_FILE) -> dict[str, Any] | None:
    data = json.loads(path.read_text(encoding="utf-8"))
    return (data.get("profiles") or {}).get(key)


def _format(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def set_value(text: str, table: str, key: str, value: Any) -> str:
    """Define ``key`` em ``[table]`` preservando o resto do arquivo."""
    newline = "\r\n" if "\r\n" in text else "\n"
    line = f"{key} = {_format(value)}"
    pattern = re.compile(rf"(?ms)^\[{re.escape(table)}\][ \t]*\r?\n(.*?)(?=^\[|\Z)")
    match = pattern.search(text)
    if match is None:
        return f"{text.rstrip()}{newline}{newline}[{table}]{newline}{line}{newline}"
    block = match.group(0)
    existing = re.compile(rf"(?m)^{re.escape(key)}[ \t]*=.*?(\r?)$")
    if existing.search(block):
        updated = existing.sub(lambda found: line + found.group(1), block, count=1)
    else:
        header_end = block.index("\n") + 1
        updated = block[:header_end] + line + newline + block[header_end:]
    return text[: match.start()] + updated + text[match.end() :]


def apply_settings(text: str, settings: dict[str, dict[str, Any]]) -> str:
    for table, values in settings.items():
        for key, value in values.items():
            text = set_value(text, table, key, value)
    return text


def missing_packages(profile: dict[str, Any]) -> list[str]:
    missing = []
    for name, requirement in (profile.get("packages") or {}).items():
        try:
            metadata.version(name)
        except metadata.PackageNotFoundError:
            missing.append(requirement)
    return missing


def read_state(root: Path) -> dict[str, Any]:
    try:
        return json.loads((root / "update" / STATE_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def status(root: Path, key: str, profile: dict[str, Any] | None) -> str:
    if profile is None:
        return "sem_perfil"
    if profile.get("status") != "approved":
        return "aguardando_aprovacao"
    if read_state(root).get("version") == profile.get("version"):
        return "aplicado"
    return "pendente"


def apply_profile(root: Path, key: str, profile: dict[str, Any], *, install=None) -> list[str]:
    missing = missing_packages(profile)
    if missing:
        install = install or (
            lambda items: subprocess.run([sys.executable, "-m", "pip", "install", *items], check=True)
        )
        install(missing)

    config = root / "dodaios.toml"
    original = config.read_bytes().decode("utf-8-sig")
    backup = root / "backups" / f"voice-profile-{time.strftime('%Y%m%d-%H%M%S')}"
    backup.mkdir(parents=True, exist_ok=True)
    shutil.copy2(config, backup / config.name)

    temporary = config.with_suffix(".toml.tmp")
    temporary.write_bytes(apply_settings(original, profile["settings"]).encode("utf-8"))
    temporary.replace(config)

    state = root / "update" / STATE_NAME
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(
        json.dumps(
            {"platform": key, "version": profile.get("version"), "applied_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")},
            indent=2,
        ),
        encoding="utf-8",
    )
    return missing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--root", default=str(Path.home() / ".dodaios"))
    args = parser.parse_args(argv)

    root = Path(args.root)
    key = platform_key()
    profile = load_profile(key)
    current = status(root, key, profile)
    print(f"PLATAFORMA={key}")
    print(f"PERFIL={current}")
    if args.apply and current == "pendente":
        installed = apply_profile(root, key, profile)
        print(f"PACOTES_INSTALADOS={installed}")
        print("PERFIL=aplicado")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
