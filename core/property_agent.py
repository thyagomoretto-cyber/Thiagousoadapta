"""Especialista em cadastro: inicia o agente e conta o que ele fez.

O agente roda em ``bridge/ja-kenlo-cadastro.py``. Aqui fica so o controle: um
cadastro por vez, a trava de salvamento e o resumo para o painel e para o chat.
Salvar publica nos portais, por isso depende de ``salvar_liberado`` nas regras.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
import unicodedata
from pathlib import Path
from typing import Any, Callable, Final

from dodaios.core import cadastro_plan as plan, property_intake as intake

GROUP: Final[str] = "Agenciamentos"
_START = re.compile(r"^\s*(?:por favor,?\s*)?(?:pode\s+)?(?:cadastr[ae]|cadastrar|faca o cadastro|faz o cadastro)\b.*\b(?:imove\w*|agenciament\w*)")
_STATUS = re.compile(r"\b(?:quais|quantos|como (?:esta|anda|foi)|o que)\b.*\b(?:cadastr\w*|imove\w*)")
_AGENT_WORDS = re.compile(r"\b(?:agente|especialista|fila|ja cadastr\w*|cadastrou|cadastrados|faltam|pendentes)\b")
_LOCK = threading.Lock()
_process: subprocess.Popen[bytes] | None = None
_watcher: threading.Thread | None = None


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


def result_message() -> str:
    """Conta ao dono, em uma frase, como terminou a ultima execucao."""
    try:
        lines = _log_path().read_text("utf-8", "replace").splitlines()
    except OSError:
        return "O agente terminou sem deixar registro."
    read = [line for line in lines if line.startswith("WHATSAPP_LIDO=")]
    info = json.loads(read[-1].split("=", 1)[1]) if read else {}
    results = [re.sub(r"\s/\S+$", "", line.split("=", 1)[1]) for line in lines if line.startswith("KENLO_RESULTADO=")]
    if not read:
        return f"Não consegui ler o grupo: {lines[-1][:160] if lines else 'sem registro'}."
    if not info.get("mensagens"):
        return "Abri o grupo, mas não consegui ler nenhuma mensagem."
    done = [item.split()[-1] for item in results if item.startswith("SALVO")]
    if results and results[-1].startswith("FILA_VAZIA") or not results:
        return (f"Li {info.get('mensagens', 0)} fichas no grupo: o último código é o {info.get('maior_codigo', 0)} e eu começo no {info.get('codigo_inicial', 0)}. "
                "Não há imóvel novo para cadastrar.")
    labels = {"PREENCHIDO": "Preenchi {} sem salvar.", "FALTANDO": "Parei no {}: faltam dados na ficha.", "FALHOU": "Parei no {}: alguns campos falharam e nada foi salvo.",
              "FOTOS_EM_DUVIDA": "Parei no {}: há fotos em dúvida. Veja com o Especialista em Fotos.", "TIPO_NAO_ENSINADO": "Parei no {}: esse tipo ainda não foi ensinado.",
              "JA_CADASTRADO": "{} já estava cadastrado.", "SEM_IMOVEL": "Não encontrei o imóvel {}.", "SALVO": "Salvei {}."}
    parts = [labels.get(item.split()[0], item) .format(" ".join(item.split()[1:3])) for item in results]
    return " ".join(parts + ([f"Referências: {', '.join(done)}."] if done else []))


def busy() -> bool:
    return running() or (_watcher is not None and _watcher.is_alive())


def _tell_when_done(process: subprocess.Popen, on_finish: Callable[[str], None]) -> None:
    global _watcher

    def wait() -> None:
        process.wait()
        on_finish(result_message())

    _watcher = threading.Thread(target=wait, name="agente-imoveis-fim", daemon=True)
    _watcher.start()


def start(save: bool, group: str = GROUP, on_finish: Callable[[str], None] | None = None) -> None:
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
        if on_finish:
            _tell_when_done(_process, on_finish)


def reading_message() -> str:
    try:
        lines = _log_path().read_text("utf-8", "replace").splitlines()
    except OSError:
        return "A leitura terminou sem deixar registro."
    done = [line for line in lines if line.startswith("LEITURA_RESULTADO=")]
    if not done:
        written = [line.strip() for line in lines if line.strip() and not line.startswith(" ")]
        return f"A leitura parou: {written[-1][:160] if written else 'sem registro'}."
    info = json.loads(done[-1].split("=", 1)[1])
    return f"Li {info['lidos']} cadastros do Kenlo: {info['por_tipo']}. Falhas: {info['falhas']}. Relatório em Downloads: {info['relatorio']}."


def read_kenlo(on_finish: Callable[[str], None], per_type: int = 100) -> None:
    """Le cadastros prontos do Kenlo para aprender. Nunca altera nada la."""
    global _process, _watcher
    with _LOCK:
        if running():
            raise RuntimeError("O agente ja esta trabalhando")
        script = Path.home() / ".dodaios" / "bridge" / "ja-kenlo-leitura.py"
        path = _log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as output:
            _process = subprocess.Popen([sys.executable, str(script), "--por-tipo", str(per_type)], cwd=str(script.parents[1]), stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
        process = _process

    def wait() -> None:
        process.wait()
        on_finish(reading_message())

    _watcher = threading.Thread(target=wait, name="leitura-kenlo-fim", daemon=True)
    _watcher.start()


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
