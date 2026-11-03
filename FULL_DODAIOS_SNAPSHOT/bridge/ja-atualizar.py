#!/usr/bin/env python3
"""Atualizador do DodaiOS. So recebe versoes marcadas como estaveis no GitHub.

  --verificar   compara com o canal estavel e avisa; nunca instala
  --status      mostra a versao atual e a disponivel
  --historico   mostra as ultimas operacoes
  --comparar    lista o que a instalacao mudaria, sem alterar nada
  --instalar    instala com backup; se o app nao voltar, restaura sozinho
  --desfazer    volta para o ultimo backup

Instala somente os arquivos alterados entre as duas versoes. Se um deles foi
mudado nesta maquina, para sem alterar nada. Configuracoes locais e segredos
nunca sao tocados.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(os.environ.get("JA_ATUALIZAR_RAIZ") or Path.home() / ".dodaios")
PACKAGE = ROOT / "dodaios"
UPDATE = ROOT / "update"
VERSION = UPDATE / "versao.json"
STATE = UPDATE / "estado.json"
HISTORY = UPDATE / "historico.jsonl"
CLONE = UPDATE / "repo"
LOCK = UPDATE / "atualizando.lock"
PAUSE = ROOT / "bridge" / "ja-supervisor.pause"
REMOTE = os.environ.get("JA_ATUALIZAR_REMOTO") or "https://github.com/thyagomoretto-cyber/Thiagousoadapta.git"
CHANNEL = "estavel"
HEALTH = os.environ.get("JA_ATUALIZAR_SAUDE") or "http://127.0.0.1:47821/api/health"
ALLOWED_SUFFIXES = {".py", ".json", ".js", ".css", ".html", ".md", ".png", ".ico", ".svg", ".woff2", ".txt"}
SKIP_TOP = {"FULL_DODAIOS_SNAPSHOT", "JA-Atualizacao", "ja_patches", "docs", "tests", ".github"}
SKIP_NAMES = {"dodaios.toml", ".env", "credentials.py"}
HEALTH_TIMEOUT_S = 150


class Parado(RuntimeError):
    """A operacao parou sem alterar a instalacao."""


def git(*args: str, cwd: Path | None = CLONE) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=600)
    if done.returncode:
        raise Parado(f"git {args[0]} falhou: {done.stderr.strip()[-300:]}")
    return done.stdout.strip()


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def record(action: str, **fields) -> None:
    UPDATE.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"quando": time.strftime("%Y-%m-%d %H:%M:%S"), "acao": action, **fields}, ensure_ascii=False)
    with HISTORY.open("a", encoding="utf-8") as output:
        output.write(line + "\n")


def notify(message: str) -> None:
    if sys.platform == "darwin":
        script = f'display notification "{message}" with title "DodaiOS"'
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=20)


def stable_commit() -> str:
    tag = f"refs/tags/{CHANNEL}"
    rows = git("ls-remote", REMOTE, tag, f"{tag}^{{}}", cwd=None).splitlines()
    commits = {row.split()[1]: row.split()[0] for row in rows}
    commit = commits.get(f"{tag}^{{}}") or commits.get(tag)
    if not commit:
        raise Parado("ainda nao existe versao marcada como estavel")
    return commit


def current_commit() -> str:
    commit = read_json(VERSION).get("commit")
    if not commit:
        raise Parado("esta maquina nao tem versao registrada")
    return commit


def verify() -> dict:
    available = stable_commit()
    current = current_commit()
    warned = read_json(STATE).get("avisado")
    state = {
        "verificado": time.strftime("%Y-%m-%d %H:%M:%S"),
        "atual": current,
        "disponivel": available,
        "ha_atualizacao": available != current,
        "avisado": warned,
    }
    if state["ha_atualizacao"] and warned != available:
        notify("Nova versao disponivel. Abra o Terminal para instalar.")
        state["avisado"] = available
    write_json(STATE, state)
    record("verificar", atual=current[:7], disponivel=available[:7])
    return state


def prepare_clone(commit: str) -> None:
    if not (CLONE / ".git").is_dir():
        UPDATE.mkdir(parents=True, exist_ok=True)
        git("clone", "-q", "--filter=blob:none", "--no-checkout", "-c", "core.autocrlf=false", REMOTE, str(CLONE), cwd=None)
    git("fetch", "-q", "--tags", "--force", "origin", "principal")
    git("cat-file", "-e", f"{commit}^{{commit}}")


def selected(name: str) -> bool:
    path = Path(name)
    return (
        path.parts[0] not in SKIP_TOP
        and path.suffix in ALLOWED_SUFFIXES
        and path.name not in SKIP_NAMES
        and not name.startswith(".")
    )


def blob(commit: str, name: str) -> bytes | None:
    done = subprocess.run(["git", "show", f"{commit}:{name}"], cwd=CLONE, capture_output=True, timeout=120)
    return done.stdout if done.returncode == 0 else None


def plan(old: str, new: str) -> tuple[list[tuple[str, str]], list[str]]:
    """``(mudancas, conflitos)``; conflito e arquivo alterado nesta maquina."""
    rows = git("diff", "--name-status", "--no-renames", old, new).splitlines()
    changes = [(row.split("\t")[0], row.split("\t")[1]) for row in rows]
    changes = [(kind, name) for kind, name in changes if selected(name)]
    conflicts = []
    for kind, name in changes:
        target = PACKAGE / name
        before = blob(old, name)
        local = target.read_bytes() if target.is_file() else None
        after = blob(new, name)
        if local in (before, after):
            continue
        if local is not None and before is not None and local.replace(b"\r\n", b"\n") == before.replace(b"\r\n", b"\n"):
            continue
        conflicts.append(name)
    return changes, conflicts


def healthy() -> bool:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.time() + HEALTH_TIMEOUT_S
    while time.time() < deadline:
        try:
            if opener.open(HEALTH, timeout=2).status == 200:
                return True
        except OSError:
            pass
        time.sleep(2)
    return False


def restart(change) -> bool:
    if os.environ.get("JA_ATUALIZAR_SEM_REINICIO"):
        change()
        return True
    PAUSE.touch()
    subprocess.run(["pkill", "-f", "dodaios.ui.web.launcher"], capture_output=True)
    time.sleep(4)
    change()
    log = open(ROOT / "ja-launcher.log", "ab")
    subprocess.Popen(
        [str(ROOT / ".venv/bin/python"), "-m", "dodaios.ui.web.launcher", "--headless", "--background-service"],
        cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
    )
    alive = healthy()
    PAUSE.unlink(missing_ok=True)
    return alive


def restore(folder: Path) -> None:
    index = read_json(folder / "arquivos.json")
    for name, saved in index["arquivos"].items():
        target = PACKAGE / name
        if saved:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(folder / saved, target)
        else:
            target.unlink(missing_ok=True)
    write_json(VERSION, {"commit": index["de"], "quando": time.strftime("%Y-%m-%d %H:%M:%S")})


def install() -> str:
    if sys.platform == "win32":
        raise Parado("a instalacao no Windows ainda nao esta pronta")
    new = stable_commit()
    old = current_commit()
    if new == old:
        return "JA_ATUALIZADO"
    prepare_clone(new)
    changes, conflicts = plan(old, new)
    if conflicts:
        raise Parado("arquivos alterados nesta maquina: " + ", ".join(conflicts[:12]))
    folder = ROOT / "backups" / ("atualizacao-" + time.strftime("%Y%m%d-%H%M%S"))
    folder.mkdir(parents=True, exist_ok=True)
    saved: dict[str, str] = {}
    for number, (_kind, name) in enumerate(changes):
        target = PACKAGE / name
        saved[name] = ""
        if target.is_file():
            saved[name] = f"{number}-{target.name}"
            shutil.copy2(target, folder / saved[name])
    write_json(folder / "arquivos.json", {"de": old, "para": new, "arquivos": saved})
    contents = {name: blob(new, name) for kind, name in changes if kind != "D"}

    def apply() -> None:
        for kind, name in changes:
            target = PACKAGE / name
            if kind == "D":
                target.unlink(missing_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(contents[name])

    if restart(apply):
        write_json(VERSION, {"commit": new, "quando": time.strftime("%Y-%m-%d %H:%M:%S")})
        record("instalar", de=old[:7], para=new[:7], arquivos=len(changes))
        return new[:7]
    restart(lambda: restore(folder))
    record("instalar_falhou", de=old[:7], para=new[:7])
    raise Parado("o app nao voltou depois de instalar; a versao anterior foi restaurada")


def undo() -> str:
    folders = sorted(path for path in (ROOT / "backups").glob("atualizacao-*") if (path / "arquivos.json").is_file())
    if not folders:
        raise Parado("nenhum backup de atualizacao")
    folder = folders[-1]
    restart(lambda: restore(folder))
    folder.rename(folder.with_name("desfeita-" + folder.name))
    record("desfazer", backup=folder.name)
    return folder.name


def main() -> int:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    for name in ("verificar", "status", "historico", "comparar", "instalar", "desfazer"):
        action.add_argument(f"--{name}", action="store_true")
    args = parser.parse_args()
    try:
        if args.historico:
            lines = HISTORY.read_text(encoding="utf-8").splitlines() if HISTORY.exists() else []
            print("\n".join(lines[-20:]) or "Sem historico.")
        elif args.status:
            state = read_json(STATE)
            print(f"ATUAL={read_json(VERSION).get('commit', 'desconhecida')[:7]}")
            print(f"DISPONIVEL={state.get('disponivel', '?')[:7]} VERIFICADO={state.get('verificado', 'nunca')}")
        elif args.verificar:
            state = verify()
            print("HA_ATUALIZACAO" if state["ha_atualizacao"] else "ATUALIZADO", state["disponivel"][:7])
        elif args.comparar:
            new = stable_commit()
            prepare_clone(new)
            changes, conflicts = plan(current_commit(), new)
            print(f"MUDANCAS={len(changes)} CONFLITOS={len(conflicts)}")
            print("\n".join(f"{kind} {name}" for kind, name in changes[:40]))
            print("\n".join(f"CONFLITO {name}" for name in conflicts[:40]))
        elif args.instalar:
            if LOCK.exists() and time.time() - LOCK.stat().st_mtime < 1800:
                raise Parado("ja existe uma atualizacao em andamento")
            LOCK.parent.mkdir(parents=True, exist_ok=True)
            LOCK.touch()
            try:
                print(f"INSTALADO={install()}")
            finally:
                LOCK.unlink(missing_ok=True)
        elif args.desfazer:
            print(f"DESFEITO={undo()}")
        return 0
    except (Parado, OSError, subprocess.TimeoutExpired) as exc:
        record("parado", motivo=str(exc)[:300])
        print(f"PARADO: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
