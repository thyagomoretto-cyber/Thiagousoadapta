"""Especialista em cadastro: inicia o agente e conta o que ele fez.

O agente roda em ``bridge/ja-kenlo-cadastro.py``. Aqui fica so o controle: um
cadastro por vez, a trava de salvamento e o resumo para o painel e para o chat.
Salvar publica nos portais, por isso depende de ``salvar_liberado`` nas regras.
"""
from __future__ import annotations

import re
import subprocess
import sys
import threading
import unicodedata
from pathlib import Path
from typing import Any, Final

from dodaios.core import cadastro_plan as plan, property_intake as intake

GROUP: Final[str] = "Agenciamentos"
_START = re.compile(r"^\s*(?:por favor,?\s*)?(?:pode\s+)?(?:cadastr[ae]|cadastrar|faca o cadastro|faz o cadastro)\b.*\b(?:imove\w*|agenciament\w*)")
_STATUS = re.compile(r"\b(?:quais|quantos|como (?:esta|anda|foi)|o que)\b.*\b(?:cadastr\w*|imove\w*)")
_AGENT_WORDS = re.compile(r"\b(?:agente|especialista|fila|ja cadastr\w*|cadastrou|cadastrados|faltam|pendentes)\b")
_LOCK = threading.Lock()
_process: subprocess.Popen[bytes] | None = None


def _fold(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in plain if not unicodedata.combining(c)).lower()


def _log_path() -> Path:
    return plan.rules_path().parent / "agente.log"


def _rules() -> dict[str, Any]:
    try:
        return plan.load_rules()
    except (OSError, ValueError):
        return {}


def running() -> bool:
    return _process is not None and _process.poll() is None


def can_save() -> bool:
    return _rules().get("salvar_liberado") is True


def start(save: bool, group: str = GROUP) -> None:
    """Inicia o agente. Recusa se ja estiver rodando ou se salvar nao foi liberado."""
    global _process
    if save and not can_save():
        raise PermissionError("O salvamento ainda nao foi liberado")
    with _LOCK:
        if running():
            raise RuntimeError("O agente ja esta cadastrando")
        script = Path.home() / ".dodaios" / "bridge" / "ja-kenlo-cadastro.py"
        command = [sys.executable, str(script), "--rodar", "--grupo", group, *(["--salvar"] if save else [])]
        path = _log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as output:
            _process = subprocess.Popen(command, cwd=str(script.parents[1]), stdout=output, stderr=subprocess.STDOUT, start_new_session=True)


def _last_event() -> str:
    try:
        lines = _log_path().read_text("utf-8", "replace").splitlines()
    except OSError:
        return ""
    events = [line for line in lines if re.match(r"(KENLO_RESULTADO|WHATSAPP_|CADASTROS_FEITOS|LOGIN_AUTOMATICO)", line)]
    if not events:
        return lines[-1][:200] if lines else ""
    return re.sub(r"\s/\S+$", "", events[-1])[:200]


def _item_view(item: dict[str, Any], done: dict[str, str]) -> dict[str, Any]:
    known = item["chave"] in done
    return {"chave": item["chave"], "tipo": item.get("tipo", ""), "status": intake.DONE if known else item["status"],
            "nota": f"Ja cadastrado: {done[item['chave']]}" if known else item.get("nota", ""),
            "titulo": next((line.strip() for line in item["texto"].splitlines()[1:] if line.strip()), item["chave"])[:80]}


def panel() -> dict[str, Any]:
    done = _rules().get("ja_cadastrados", {})
    items = [_item_view(item, done) for item in intake.all_items()]
    counts = {status: sum(item["status"] == status for item in items) for status in (intake.DONE, intake.PENDING, intake.REVIEW)}
    return {"rodando": running(), "ultimo": _last_event(), "salvar_liberado": can_save(), "contagem": counts, "itens": items}


def _summary() -> str:
    view = panel()
    counts = view["contagem"]
    lines = [f"{counts[intake.DONE]} cadastrados, {counts[intake.PENDING]} pendentes e {counts[intake.REVIEW]} para revisar."]
    lines.insert(0, "O agente esta trabalhando agora." if view["rodando"] else "O agente esta parado.")
    lines += [f"Revisar {item['chave']}: {item['nota'] or 'sem motivo registrado'}" for item in view["itens"] if item["status"] == intake.REVIEW][:5]
    return "\n".join(lines)


def answer_property_request(text: str) -> str | None:
    """Pedido direto no chat. Devolve None quando a frase nao e para o especialista."""
    plain = _fold(text)
    if _START.search(plain) and "?" not in text:
        save = can_save()
        try:
            start(save)
        except RuntimeError as exc:
            return f"{exc}.\n{_summary()}"
        if save:
            return "Comecei o cadastro dos imoveis novos, em sequencia. Peca o resumo quando quiser."
        return "Comecei sem salvar, porque o salvamento ainda nao foi liberado. Ele preenche o proximo imovel e espera voce conferir."
    if _STATUS.search(plain) and _AGENT_WORDS.search(plain):
        return _summary()
    return None
