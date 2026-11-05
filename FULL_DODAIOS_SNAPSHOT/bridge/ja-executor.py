#!/usr/bin/env python3
"""Executor do DodaiOS: roda so uma lista fechada de acoes pedidas numa pasta local.

Pedido: um JSON em ~/.dodaios-data/executor/pedidos/<id>.json
  {"acao": "instalar", "arquivo": "nome-mac.sh"}
Acoes: instalar, desfazer, reiniciar, testar. Qualquer outra coisa e recusada.
Instaladores ficam em ~/.dodaios-data/executor/pacotes/.
"""
from __future__ import annotations

import json
import os
import plistlib
import re
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime
from pathlib import Path

HOME = Path.home()
ROOT = HOME / ".dodaios-data/executor"
REQUESTS = ROOT / "pedidos"
PACKAGES = ROOT / "pacotes"
RESULTS = ROOT / "resultados"
DONE = ROOT / "feitos"
LOG = ROOT / "executor.log"
AGENT_LOG = HOME / ".dodaios-data/data/imoveis/agente.log"
BRIDGE = HOME / ".dodaios/bridge"
APP = Path("/Applications/DodaiOS.app")
STATUS_URL = "http://127.0.0.1:47821/api/company-voice/pergunta"
REQUEST_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,60}\.json$")
PACKAGE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,60}-mac\.sh$")
SECRET = re.compile(r"senha|password|passwd|token|api.?key|secret|bearer|cookie|authorization", re.IGNORECASE)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"(?<!\d)(?:\+?55\s?)?\(?\d{2}\)?\s?9?\d{4}[-\s]?\d{4}(?!\d)")
AGENT_RUNNING = re.compile(r"ja-kenlo-(?:leitura|cadastro)|ja-whatsapp-imoveis")
POLL_S = float(os.environ.get("JA_EXECUTOR_ESPERA") or 3)
INSTALL_LIMIT_S = int(os.environ.get("JA_EXECUTOR_LIMITE") or 600)
OUTPUT_LIMIT = 20_000
TAIL_LINES = 40
stop = {"now": False}


def log(text: str) -> None:
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {text}\n")


def clean(text: str) -> str:
    """Nada de segredo ou contato no resultado: a saida pode ser lida fora do Mac."""
    lines = [PHONE.sub("[tel]", EMAIL.sub("[email]", line)) for line in text.splitlines() if not SECRET.search(line)]
    return "\n".join(lines)[-OUTPUT_LIMIT:]


def run(command: list[str], limit: int = 30) -> tuple[int, str]:
    try:
        done = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True, errors="replace", timeout=limit)
        return done.returncode, done.stdout
    except subprocess.TimeoutExpired as exc:
        return 124, f"{exc.stdout or ''}\nTempo esgotado."
    except OSError as exc:
        return 127, str(exc)


def processes() -> str:
    return run(["ps", "-axo", "args="])[1]


def agent_busy() -> bool:
    return any(AGENT_RUNNING.search(line) and "ja-executor" not in line for line in processes().splitlines())


def package(request: dict) -> Path:
    name = str(request.get("arquivo", ""))
    path = PACKAGES / name
    if not PACKAGE_NAME.match(name) or not path.is_file() or path.is_symlink():
        raise ValueError(f"pacote invalido: {name[:80]}")
    return path


def install(request: dict) -> tuple[int, str]:
    if agent_busy():
        return 75, "Agente trabalhando agora: nada foi instalado."
    return run(["/bin/bash", str(package(request))], INSTALL_LIMIT_S)


def undo(request: dict) -> tuple[int, str]:
    if agent_busy():
        return 75, "Agente trabalhando agora: nada foi desfeito."
    return run(["/bin/bash", str(package(request)), "--desfazer"], INSTALL_LIMIT_S)


def restart_app(_: dict) -> tuple[int, str]:
    if agent_busy():
        return 75, "Agente trabalhando agora: o app nao foi reiniciado."
    if not APP.is_dir():
        return 1, "DodaiOS.app nao encontrado."
    name = plistlib.loads((APP / "Contents/Info.plist").read_bytes()).get("CFBundleExecutable", "DodaiOS")
    run(["pkill", "-x", name])
    time.sleep(3)
    return run(["open", str(APP)])


def check(_: dict) -> tuple[int, str]:
    """Testes fixos: servidor, app, sintaxe dos agentes e fim do log."""
    lines, failures = [], 0
    began = time.monotonic()
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(STATUS_URL, timeout=5) as answer:
            data = json.load(answer)
        lines.append(f"Servidor: ok em {time.monotonic() - began:.2f}s; pergunta aberta: {bool(data.get('pergunta'))}")
    except Exception as exc:
        failures += 1
        lines.append(f"Servidor: sem resposta ({type(exc).__name__})")
    running = processes()
    lines.append(f"App aberto: {'DodaiOS.app' in running}")
    for path in sorted(BRIDGE.glob("ja-*.py")):
        try:
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
            lines.append(f"Sintaxe ok: {path.name}")
        except (OSError, SyntaxError) as exc:
            failures += 1
            lines.append(f"Sintaxe com erro: {path.name}: {exc}")
    if AGENT_LOG.is_file():
        tail = AGENT_LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-TAIL_LINES:]
        lines += ["", "Fim do log do agente:", *[line[:220] for line in tail]]
    return (1 if failures else 0), "\n".join(lines)


ACTIONS = {"instalar": install, "desfazer": undo, "reiniciar": restart_app, "testar": check}


def write_result(name: str, result: dict) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=RESULTS, delete=False, suffix=".tmp") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=1)
    os.replace(handle.name, RESULTS / name)


def handle_request(path: Path) -> None:
    began = datetime.now().isoformat(timespec="seconds")
    result = {"pedido": path.name, "inicio": began, "acao": "", "codigo": 2, "saida": ""}
    try:
        if not REQUEST_NAME.match(path.name) or path.is_symlink():
            raise ValueError("nome de pedido invalido")
        request = json.loads(path.read_text(encoding="utf-8"))
        action = request.get("acao") if isinstance(request, dict) else None
        result["acao"] = str(action)[:30]
        if action not in ACTIONS:
            raise ValueError(f"acao recusada: {str(action)[:30]}")
        log(f"INICIO {path.name} {action}")
        code, output = ACTIONS[action](request)
        result.update(codigo=code, saida=clean(output))
    except (OSError, ValueError) as exc:
        result["saida"] = clean(str(exc))
    result["fim"] = datetime.now().isoformat(timespec="seconds")
    write_result(path.name, result)
    log(f"FIM {path.name} codigo={result['codigo']}")
    if path.is_symlink() or not path.is_file():
        path.unlink(missing_ok=True)
    else:
        os.replace(path, DONE / f"{int(time.time())}-{path.name}")


def main() -> int:
    for folder in (REQUESTS, PACKAGES, RESULTS, DONE):
        folder.mkdir(parents=True, exist_ok=True)
    signal.signal(signal.SIGTERM, lambda *_: stop.update(now=True))
    signal.signal(signal.SIGINT, lambda *_: stop.update(now=True))
    log("Executor ligado")
    once = "--uma-vez" in sys.argv
    while not stop["now"]:
        for path in sorted(REQUESTS.iterdir()):
            if path.name.endswith(".tmp") or path.name.startswith("."):
                continue
            handle_request(path)
        if once:
            break
        time.sleep(POLL_S)
    log("Executor desligado")
    return 0


if __name__ == "__main__":
    sys.exit(main())
