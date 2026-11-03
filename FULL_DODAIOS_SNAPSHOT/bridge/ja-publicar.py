#!/usr/bin/env python3
"""Publica no GitHub uma correcao feita no DodaiOS. Roda so na maquina publicadora.

Uso:
  python ja-publicar.py --verificar
  python ja-publicar.py --mensagem "O que mudou" --arquivo plugins/stt/x.py

Publica somente os arquivos citados, nas duas arvores do repositorio. Testa antes,
recusa segredos e nunca usa push forcado. A chave SSH fica fora do repositorio.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("JA_PUBLICAR_RAIZ") or Path.home() / ".dodaios")
PACKAGE = ROOT / "dodaios"
MARKER = ROOT / "global" / "publicador.json"
WORK = ROOT / "publicacao"
CLONE = WORK / "repo"
LOCK = WORK / "publicando.lock"
LOG = ROOT / "logs" / "publicacoes.jsonl"
KEY = Path.home() / ".ssh" / "dodaios_publicar"
REMOTE = os.environ.get("JA_PUBLICAR_REMOTO") or "git@github.com:thyagomoretto-cyber/Thiagousoadapta.git"
BRANCH = "principal"
TREES = (Path("."), Path("FULL_DODAIOS_SNAPSHOT/dodaios"))
ALLOWED_SUFFIXES = {".py", ".json", ".md"}
BLOCKED_PARTS = {".git", ".venv", "__pycache__", "node_modules", "dist", "backups", "memories", "logs"}
BLOCKED_NAMES = re.compile(r"(^\.env|secret|token|credential|password|senha|\.key$|\.pem$|dodaios\.toml)", re.I)
SECRET_TEXT = re.compile(
    r"(sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}"
    r"|xox[bp]-[A-Za-z0-9-]{20,}|AIza[0-9A-Za-z_-]{30,}|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|(?:api[_-]?key|password|senha|secret)\s*[=:]\s*[\"'][^\"'\s]{12,}[\"'])",
    re.I,
)


class Recusado(RuntimeError):
    """A publicacao parou antes do envio, sem alterar o GitHub."""


def git(*args: str, cwd: Path | None = CLONE, check: bool = True) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    if not os.environ.get("JA_PUBLICAR_REMOTO"):
        env["GIT_SSH_COMMAND"] = f'ssh -i "{KEY}" -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new'
    done = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=300)
    if check and done.returncode:
        raise Recusado(f"git {args[0]} falhou: {done.stderr.strip()[-300:]}")
    return done


def validate_path(name: str) -> Path:
    rel = Path(name.replace("\\", "/"))
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        raise Recusado(f"caminho invalido: {name}")
    if rel.suffix not in ALLOWED_SUFFIXES or set(rel.parts) & BLOCKED_PARTS or BLOCKED_NAMES.search(rel.name):
        raise Recusado(f"arquivo nao permitido: {name}")
    source = PACKAGE / rel
    if not source.is_file():
        raise Recusado(f"arquivo nao encontrado: {name}")
    text = source.read_text(encoding="utf-8")
    if SECRET_TEXT.search(text):
        raise Recusado(f"possivel segredo em {name}. Nada foi enviado.")
    return rel


def test_file(path: Path) -> None:
    if path.suffix == ".py":
        try:
            compile(path.read_text(encoding="utf-8").lstrip("\ufeff"), str(path), "exec")
        except SyntaxError as exc:
            raise Recusado(f"erro de sintaxe em {path.name}: {exc}") from exc
    elif path.suffix == ".json":
        try:
            json.loads(path.read_text(encoding="utf-8-sig"))
        except ValueError as exc:
            raise Recusado(f"JSON invalido em {path.name}: {exc}") from exc


def test_imports(files: list[Path]) -> None:
    modules = [".".join(("dodaios", *f.with_suffix("").parts)) for f in files if f.suffix == ".py" and f.name != "__main__.py"]
    modules = [m[: -len(".__init__")] if m.endswith(".__init__") else m for m in modules]
    if not modules:
        return
    code = "import importlib,sys\nfor m in sys.argv[1:]: importlib.import_module(m)\n"
    done = subprocess.run([sys.executable, "-c", code, *modules], cwd=str(ROOT), capture_output=True, text=True, timeout=240)
    if done.returncode:
        raise Recusado("teste de importacao falhou: " + done.stderr.strip()[-400:])


def prepare_clone() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    if not (CLONE / ".git").is_dir():
        git("clone", "-c", "core.autocrlf=false", "--depth", "30", "--branch", BRANCH, REMOTE, str(CLONE), cwd=WORK)
    git("config", "user.name", "thyagomoretto-cyber")
    git("config", "user.email", "thyagomoretto@gmail.com")
    git("fetch", "origin", BRANCH)
    if git("status", "--porcelain").stdout.strip():
        raise Recusado("copia de publicacao com alteracoes pendentes")
    git("merge", "--ff-only", f"origin/{BRANCH}")


def publish(message: str, names: list[str]) -> str:
    if not MARKER.is_file():
        raise Recusado("esta maquina nao e a publicadora")
    if not message.strip():
        raise Recusado("mensagem vazia")
    files = [validate_path(name) for name in dict.fromkeys(names)]
    if not files:
        raise Recusado("nenhum arquivo informado")
    for rel in files:
        test_file(PACKAGE / rel)
    test_imports(files)
    prepare_clone()
    for tree in TREES:
        for rel in files:
            target = CLONE / tree / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PACKAGE / rel, target)
    if not git("status", "--porcelain").stdout.strip():
        return "SEM_MUDANCAS"
    try:
        git("add", "--", *[str(tree / rel) for tree in TREES for rel in files])
        git("commit", "-q", "-m", message.strip()[:200])
        pushed = git("push", "origin", BRANCH, check=False)
        if pushed.returncode:
            git("pull", "--rebase", "origin", BRANCH)
            git("push", "origin", BRANCH)
    except Recusado:
        # A copia e descartavel: a proxima publicacao baixa uma limpa.
        shutil.rmtree(CLONE, ignore_errors=True)
        raise
    return git("rev-parse", "--short", "HEAD").stdout.strip()


def record(entry: dict) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as output:
        output.write(json.dumps({"quando": time.strftime("%Y-%m-%d %H:%M:%S"), **entry}, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mensagem", default="")
    parser.add_argument("--arquivo", action="append", default=[])
    parser.add_argument("--verificar", action="store_true")
    args = parser.parse_args()
    try:
        if args.verificar:
            if not MARKER.is_file():
                raise Recusado("esta maquina nao e a publicadora")
            head = git("ls-remote", REMOTE, BRANCH, cwd=None).stdout.split()[:1]
            print(f"PUBLICADOR=OK {head[0][:7] if head else 'sem branch'}")
            return 0
        WORK.mkdir(parents=True, exist_ok=True)
        try:
            LOCK.touch(exist_ok=False)
        except FileExistsError:
            if time.time() - LOCK.stat().st_mtime < 900:
                raise Recusado("ja existe uma publicacao em andamento") from None
            LOCK.touch()
        try:
            result = publish(args.mensagem, args.arquivo)
        finally:
            LOCK.unlink(missing_ok=True)
        record({"resultado": result, "mensagem": args.mensagem, "arquivos": args.arquivo})
        print(f"PUBLICADO={result}")
        return 0
    except (Recusado, subprocess.TimeoutExpired, OSError) as exc:
        record({"resultado": "RECUSADO", "motivo": str(exc)[:300], "arquivos": args.arquivo})
        print(f"PUBLICACAO_RECUSADA: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
