#!/usr/bin/env python3
from pathlib import Path
import subprocess
import urllib.request
import json
import re
import time
import os

HOME = Path.home()
ROOT = HOME / ".dodaios"
CFG = ROOT / "dodaios.toml"
STATE = ROOT / "bridge" / "ja-provider-state.txt"
LOG = ROOT / "logs" / "ja-supervisor.log"

def maria_root():
    """Endereco do LM Studio lido da configuracao local desta maquina."""
    try:
        text = CFG.read_text()
        block = re.search(r'(?ms)^\[brain\.providers\."local-openai"\]\n(.*?)(?=^\[|\Z)', text)
        match = re.search(r'^base_url\s*=\s*"([^"]+)"', block.group(1), re.M)
        return match.group(1).rstrip("/")
    except Exception:
        return "http://127.0.0.1:1234"


MARIA_ROOT = maria_root()
MARIA_MODELS = MARIA_ROOT + "/v1/models"
MARIA_MODEL = "qwen/qwen3.5-9b"

NVIDIA_MODEL = "nvidia/nemotron-3.5-super-vl-120b-a12b"

def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts} {msg}\n"
    try:
        with LOG.open("a") as f:
            f.write(line)
    except Exception:
        pass

def maria_ready():
    try:
        req = urllib.request.Request(MARIA_MODELS)
        with urllib.request.urlopen(req, timeout=3) as r:
            if r.status != 200:
                return False
            data = json.loads(r.read().decode("utf-8", "ignore"))
            ids = []
            for m in data.get("data", []):
                if isinstance(m, dict):
                    ids.append(str(m.get("id", "")))
            return MARIA_MODEL in ids or any("qwen3.5-9b" in x.lower() for x in ids)
    except Exception:
        return False

def ensure_provider_block(s):
    marker = '[brain.providers."local-openai"]'
    if marker not in s:
        block = (
            '\n[brain.providers."local-openai"]\n'
            f'model = "{MARIA_MODEL}"\n'
            f'base_url = "{MARIA_ROOT}"\n'
        )
        pos = s.find("\n[brain.worker]")
        if pos >= 0:
            s = s[:pos] + block + s[pos:]
        else:
            s = s.rstrip() + "\n" + block
    else:
        start = s.index(marker)
        end = s.find("\n[", start + 1)
        if end == -1:
            end = len(s)
        block = s[start:end]

        if re.search(r'^model\s*=', block, re.M):
            block = re.sub(
                r'^model\s*=\s*"[^"]*"',
                f'model = "{MARIA_MODEL}"',
                block,
                count=1,
                flags=re.M
            )
        else:
            block += f'\nmodel = "{MARIA_MODEL}"'

        if re.search(r'^base_url\s*=', block, re.M):
            block = re.sub(
                r'^base_url\s*=\s*"[^"]*"',
                f'base_url = "{MARIA_ROOT}"',
                block,
                count=1,
                flags=re.M
            )
        else:
            block += f'\nbase_url = "{MARIA_ROOT}"'

        s = s[:start] + block + s[end:]

    return s

def ensure_nvidia(s):
    marker = "[brain.providers.nvidia]"
    if marker not in s:
        block = (
            '\n[brain.providers.nvidia]\n'
            f'model = "{NVIDIA_MODEL}"\n'
        )
        pos = s.find('\n[brain.providers."local-openai"]')
        if pos >= 0:
            s = s[:pos] + block + s[pos:]
        else:
            s = s.rstrip() + "\n" + block
    return s

def set_provider(s, provider):
    # [brain] primary
    brain_match = re.search(r'(?ms)^\[brain\]\n(.*?)(?=^\[|\Z)', s)
    if brain_match:
        block = brain_match.group(0)
        if re.search(r'^primary\s*=', block, re.M):
            newblock = re.sub(
                r'^primary\s*=\s*"[^"]+"',
                f'primary = "{provider}"',
                block,
                count=1,
                flags=re.M
            )
        else:
            newblock = block.rstrip() + f'\nprimary = "{provider}"\n'
        s = s[:brain_match.start()] + newblock + s[brain_match.end():]

    # [brain.worker]
    wm = re.search(r'(?ms)^\[brain\.worker\]\n(.*?)(?=^\[|\Z)', s)
    if wm:
        block = wm.group(0)
        model = MARIA_MODEL if provider == "local-openai" else NVIDIA_MODEL

        if re.search(r'^provider\s*=', block, re.M):
            block = re.sub(
                r'^provider\s*=\s*"[^"]+"',
                f'provider = "{provider}"',
                block,
                count=1,
                flags=re.M
            )
        else:
            block = block.rstrip() + f'\nprovider = "{provider}"\n'

        if re.search(r'^model\s*=', block, re.M):
            block = re.sub(
                r'^model\s*=\s*"[^"]*"',
                f'model = "{model}"',
                block,
                count=1,
                flags=re.M
            )
        else:
            block = block.rstrip() + f'\nmodel = "{model}"\n'

        s = s[:wm.start()] + block + s[wm.end():]

    return s

def ensure_cu_rule(s):
    marker = "[regras_persistentes.roteamento_computer_use]"
    if marker in s:
        return s

    return s.rstrip() + r'''

[regras_persistentes.roteamento_computer_use]
ativa = true
prioridade = "alta"
descricao = "Roteamento automático de ações físicas e visuais no Mac para computer_use."
regra = "Pedidos para abrir aplicativos, clicar, digitar, selecionar, navegar, rolar, trocar janelas, usar Finder, Chrome, menus, botões, campos ou outros elementos visuais devem ser executados diretamente usando computer_use. Para shell, arquivos e APIs que não dependam de interface visual, usar ferramentas diretas. Após ações físicas, verificar visualmente o resultado quando possível."
''' + "\n"

def health_ok():
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:47821/api/health",
            timeout=2
        ) as r:
            return r.status == 200
    except Exception:
        return False


FAILS = ROOT / "bridge" / "ja-health-fails.txt"
PAUSE = ROOT / "bridge" / "ja-supervisor.pause"
APP = Path("/Applications/Dodaios.app")
if not APP.is_dir():
    APP = HOME / "Applications" / "Dodaios.app"


def launcher_running():
    return subprocess.run(
        ["pgrep", "-f", "dodaios.ui.web.launcher"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    ).returncode == 0


def switch_live(provider):
    body = json.dumps({"provider": provider}).encode("utf-8")
    request = urllib.request.Request(
        "http://127.0.0.1:47821/api/brain/switch",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Origin": "http://127.0.0.1:47821",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as r:
            return r.status == 200
    except Exception as exc:
        log(f"troca sem reiniciar falhou: {exc}")
        return False


def write_config(text):
    temporary = CFG.with_suffix(".toml.tmp")
    temporary.write_text(text)
    temporary.replace(CFG)


def start_backend():
    out = open(ROOT / "ja-launcher.log", "ab")
    subprocess.Popen(
        [
            str(ROOT / ".venv" / "bin" / "python"),
            "-m",
            "dodaios.ui.web.launcher",
            "--headless",
            "--background-service",
        ],
        cwd=str(ROOT),
        stdout=out,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def recover_if_hung():
    if health_ok():
        if FAILS.exists():
            FAILS.unlink()
        return
    if not launcher_running():
        start_backend()
        log("backend ausente: iniciado")
        return
    try:
        fails = int(FAILS.read_text().strip()) + 1
    except Exception:
        fails = 1
    FAILS.write_text(str(fails))
    if fails < 3:
        log(f"health falhou ({fails}/3)")
        return
    subprocess.run(
        ["pkill", "-f", "dodaios.ui.web.launcher"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    time.sleep(3)
    start_backend()
    FAILS.write_text("0")
    log("backend travado: reiniciado")


def main():
    if PAUSE.exists():
        return

    maria = maria_ready()
    desired = "local-openai" if maria else "nvidia"

    s = CFG.read_text()
    current = ""
    m = re.search(r'(?ms)^\[brain\]\n(.*?)(?=^\[|\Z)', s)
    if m:
        pm = re.search(r'^primary\s*=\s*"([^"]+)"', m.group(0), re.M)
        if pm:
            current = pm.group(1)

    if current != desired:
        applied = health_ok() and switch_live(desired)
        s = CFG.read_text()
        s = ensure_provider_block(s)
        s = ensure_nvidia(s)
        s = ensure_cu_rule(s)
        s = set_provider(s, desired)
        write_config(s)
        STATE.write_text(desired + "\n")
        state = "aplicado sem reiniciar" if applied else "vale na proxima abertura"
        log(f"provider alterado: {current or '?'} -> {desired} ({state})")
    else:
        log(f"ok provider={desired} maria={'online' if maria else 'offline'}")

    recover_if_hung()


if __name__ == "__main__":
    main()
