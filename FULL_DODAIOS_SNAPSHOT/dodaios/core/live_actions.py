"""Acoes imediatas do ensino por voz: abrir aplicativos e links sem passar pelo modelo.

Um passo como "abra o Chrome" nao precisa de dezenas de segundos de modelo local.
So abre aplicativos instalados e enderecos https, e o resto segue para o assistente.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Any, Final

_APP_FOLDERS: Final[tuple[Path, ...]] = (
    Path("/Applications"),
    Path("/System/Applications"),
    Path.home() / "Applications",
)
_BROWSER: Final[str] = "Google Chrome"
_DOMAIN = re.compile(r"\b(?:https?://)?((?:[a-z0-9-]+\.)+[a-z]{2,}(?:/\S*)?)", re.I)
_OPEN_VERB = re.compile(r"^(?:por favor |agora |entao )*(?:abra|abre|abrir)\s+(?:o |a |os |as )?(.+)$")
_GO_VERB = re.compile(
    r"^(?:por favor |agora |entao )*(?:entre|entra|entrar|acesse|acessa|acessar|va|vai|ir|abra|abre|abrir)\s+"
    r"(?:(?:no|na|em|para|pro|pra|ao|o|a)\s+)*(?:link|site|pagina|endereco|url)\s*(?:(?:do|da|de)\s+)?(.+)$"
)


def _fold(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in plain if not unicodedata.combining(c)).lower().strip(" .,!?")


def _links_file() -> Path:
    from dodaios.core.paths import user_data_dir

    return user_data_dir() / "data" / "company_skills" / "links.json"


def _links() -> dict[str, str]:
    try:
        return json.loads(_links_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_link(name: str, url: str) -> None:
    links = _links()
    links[_fold(name)] = url
    path = _links_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(links, ensure_ascii=False, indent=2), encoding="utf-8")


def _installed_apps() -> dict[str, str]:
    apps: dict[str, str] = {}
    for folder in _APP_FOLDERS:
        if folder.is_dir():
            for path in folder.glob("*.app"):
                apps[_fold(path.stem)] = path.stem
    return apps


def _find_app(name: str) -> str | None:
    wanted = _fold(name)
    apps = _installed_apps()
    if wanted in apps:
        return apps[wanted]
    matches = [app for key, app in apps.items() if wanted in key.split() or key.startswith(wanted)]
    return sorted(matches, key=len)[0] if len(wanted) >= 3 and matches else None


def _url_in(text: str) -> str | None:
    spoken = re.sub(r"\s+ponto\s+", ".", text, flags=re.I)
    found = _DOMAIN.search(spoken.replace(" ", " "))
    return f"https://{found.group(1)}" if found else None


def _open(*arguments: str) -> None:
    subprocess.run(["open", *arguments], check=True, capture_output=True, timeout=15)


def act(text: str, pending_link: str = "") -> dict[str, Any]:
    """Executa o passo se for imediato; ``done`` falso manda para o assistente."""
    if sys.platform != "darwin":
        return {"done": False}
    url = _url_in(text)
    if pending_link and url:
        save_link(pending_link, url)
    folded = _fold(text)
    go = _GO_VERB.match(folded)
    if url and (pending_link or go or _OPEN_VERB.match(folded)):
        _open("-a", _BROWSER, url)
        return {"done": True, "step": f"Abrir {url} no {_BROWSER}"}
    if go:
        name = go.group(1).strip()
        known = _links().get(name)
        if known:
            _open("-a", _BROWSER, known)
            return {"done": True, "step": f"Abrir {known} no {_BROWSER}"}
        return {"done": False, "needs_link": name}
    opened = _OPEN_VERB.match(folded)
    if opened:
        app = _find_app(opened.group(1))
        if app:
            _open("-a", app)
            return {"done": True, "step": f"Abrir o aplicativo {app}"}
    return {"done": False}
