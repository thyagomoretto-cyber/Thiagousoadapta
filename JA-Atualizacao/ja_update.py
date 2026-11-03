"""Atualizador do JA para Windows.

Faz backup, aplica as correcoes no source e no runtime, reconstroi o frontend,
valida o resultado e grava um relatorio. Pode ser executado mais de uma vez.

    python ja_update.py              aplica
    python ja_update.py --rollback   desfaz a ultima atualizacao
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import py_compile
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PAYLOAD = HERE / "payload"
ROOT = Path(os.environ.get("JA_ROOT") or Path.home() / ".dodaios")
VENV = ROOT / ".venv"
SITE = VENV / "Lib" / "site-packages"
SOURCE_TREE = ROOT / "dodaios"
RUNTIME_TREE = SITE / "dodaios"
BACKUPS = ROOT / "ja_backups"
LOGS = ROOT / "logs"
STAMP = datetime.now().strftime("%Y%m%d-%H%M%S")
BACKUP = BACKUPS / f"update-{STAMP}"
PORT = 47821

RANGE_OK = r"\u0300-\u036f"
RANGE_LITERAL = "\u0300-\u036f"
RANGE_BROKEN = "\u00cc\u20ac-\u00cd\u00af"  # U+0300-U+036F lido como cp1252
RETRY_MARKER = "JA_LOAD_RETRY"
REGEX_FILES = (
    "components/society/create/starterFilters.ts",
    "lib/clipboard.ts",
    "lib/quickSwitch.ts",
    "views/profile/MemorySection.tsx",
)
MOJIBAKE_FILES = (
    "components/UserSelectorGate.tsx",
    "components/layout/SidebarBottomActions.tsx",
)

lines: list[str] = []
warnings: list[str] = []
manifest: dict = {"files": [], "dirs": []}
touched: set[str] = set()


def say(text: str) -> None:
    print(text, flush=True)
    lines.append(text)


def warn(text: str) -> None:
    warnings.append(text)
    say(f"[AVISO] {text}")


def ok(text: str) -> None:
    say(f"[OK] {text}")


# ---------------------------------------------------------------------------
# Backup e escrita
# ---------------------------------------------------------------------------

def save_manifest() -> None:
    BACKUP.mkdir(parents=True, exist_ok=True)
    (BACKUP / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def key(path: Path) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def backup_file(path: Path) -> None:
    if any(item["path"] == str(path) for item in manifest["files"]):
        return
    entry: dict = {"path": str(path), "backup": None}
    if path.exists():
        saved = BACKUP / "files" / f"{len(manifest['files']):05d}_{path.name}"
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, saved)
        entry["backup"] = str(saved)
    manifest["files"].append(entry)
    save_manifest()


def write_bytes(path: Path, data: bytes) -> None:
    if path.exists() and path.read_bytes() == data:
        return
    backup_file(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    touched.add(key(path))


def read_text(path: Path) -> str:
    return path.read_bytes().decode("utf-8-sig")


def write_text(path: Path, text: str) -> None:
    write_bytes(path, text.encode("utf-8"))


def copy_file(source: Path, target: Path) -> None:
    write_bytes(target, source.read_bytes())


def trees() -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()
    for tree in (SOURCE_TREE, RUNTIME_TREE):
        if tree.is_dir() and key(tree.resolve()) not in seen:
            seen.add(key(tree.resolve()))
            found.append(tree)
    return found


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------

CP1252_CHARS = "".join(
    bytes([value]).decode("cp1252", errors="ignore") for value in range(0x80, 0x100)
)
MOJIBAKE_RUN = re.compile(
    "[" + re.escape(CP1252_CHARS) + "\u0081\u008d\u008f\u0090\u009d]{2,}"
)


def _to_cp1252(run: str) -> bytes:
    out = bytearray()
    for char in run:
        code = ord(char)
        if code in (0x81, 0x8d, 0x8f, 0x90, 0x9d):
            out.append(code)
        else:
            out += char.encode("cp1252")
    return bytes(out)


def demojibake(text: str) -> str:
    """Desfaz UTF-8 lido como cp1252, sem tocar em texto que nao seja reversivel."""

    def fix(match: re.Match[str]) -> str:
        run = match.group(0)
        try:
            return _to_cp1252(run).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return run

    return MOJIBAKE_RUN.sub(fix, text)


def fix_regex_text(text: str) -> str:
    return text.replace(RANGE_BROKEN, RANGE_OK).replace(RANGE_LITERAL, RANGE_OK)


# ---------------------------------------------------------------------------
# Correcoes em Python
# ---------------------------------------------------------------------------

def fix_multiuser(tree: Path) -> None:
    copy_file(PAYLOAD / "dodaios/ui/web/multiuser_routes.py", tree / "ui/web/multiuser_routes.py")
    copy_file(PAYLOAD / "dodaios/ui/web/ja_update_auth.py", tree / "ui/web/ja_update_auth.py")


def fix_user_rules(tree: Path) -> None:
    path = tree / "core/user_rules.py"
    if not path.exists():
        warn(f"{path} nao encontrado")
        return
    text = read_text(path)
    write_text(path, text.replace(
        'json.loads(path.read_text(encoding="utf-8"))',
        'json.loads(path.read_text(encoding="utf-8-sig"))',
    ))


def fix_restart_route(tree: Path) -> None:
    path = tree / "ui/web/settings_routes.py"
    if not path.exists():
        warn(f"{path} nao encontrado")
        return
    text = read_text(path)
    newline = "\r\n" if "\r\n" in text else "\n"
    source = text.split(newline)
    function = next(
        (
            node
            for node in ast.walk(ast.parse(text))
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "restart_app"
        ),
        None,
    )
    if function is None:
        warn("restart_app nao encontrado em settings_routes.py")
        return
    gate = [
        "    from .ja_update_auth import require_update_administrator",
        "    require_update_administrator()",
    ]
    body = function.body
    docstring = next(
        (
            node
            for node in body[:3]
            if isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ),
        None,
    )
    if docstring is None:
        warn("docstring de restart_app nao encontrada; rota mantida como estava")
        return
    start = body[0].lineno - 1
    if source[start:start + 2] == gate:
        end = docstring.end_lineno
        fixed = source[:start] + source[start + 2:end] + gate + source[end:]
    elif gate[0] in source[docstring.end_lineno:docstring.end_lineno + 2]:
        return
    else:
        end = docstring.end_lineno
        fixed = source[:end] + gate + source[end:]
    write_text(path, newline.join(fixed))


def fix_plugin_registry(tree: Path) -> None:
    path = tree / "marketplace/plugin_registry.py"
    if not path.exists():
        warn(f"{path} nao encontrado")
        return
    text = read_text(path)
    tree_ast = ast.parse(text)
    offsets = text.split("\n")
    changed = 0

    def walk(node: ast.AST, inside: ast.AST | None) -> None:
        nonlocal changed
        for child in ast.iter_child_nodes(node):
            scope = inside
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                scope = child
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr == "load"
                and ast.unparse(child.func) == "self._store.load"
                and isinstance(scope, ast.AsyncFunctionDef)
                and len(child.args) == 1
            ):
                index = child.lineno - 1
                argument = ast.unparse(child.args[0])
                original = f"self._store.load({argument})"
                replacement = f"await asyncio.to_thread(self._store.load, {argument})"
                if original in offsets[index]:
                    offsets[index] = offsets[index].replace(original, replacement, 1)
                    changed += 1
            walk(child, scope)

    walk(tree_ast, None)
    if changed:
        write_text(path, "\n".join(offsets))


def fix_text_encoding(tree: Path) -> None:
    path = tree / "ui/desktop_app.py"
    if path.exists():
        write_text(path, demojibake(read_text(path)))


def fix_scheduler(active_trees: list[Path]) -> None:
    donor = next(
        (
            tree / "tasks/scheduler.py"
            for tree in active_trees
            if (tree / "tasks/scheduler.py").exists()
            and "def attach_owner_gate(" in read_text(tree / "tasks/scheduler.py")
        ),
        PAYLOAD / "dodaios/tasks/scheduler.py",
    )
    for tree in active_trees:
        path = tree / "tasks/scheduler.py"
        if not path.exists() or "def attach_owner_gate(" not in read_text(path):
            copy_file(donor, path)
            ok(f"scheduler.py atualizado em {tree}")


def add_missing_modules(active_trees: list[Path]) -> None:
    for tree in active_trees:
        path = tree / "society/credentials.py"
        if not path.exists():
            copy_file(PAYLOAD / "dodaios/society/credentials.py", path)
            ok(f"society/credentials.py restaurado em {tree}")
    for base in (ROOT, SITE):
        if not base.is_dir():
            continue
        orb = base / "ui/orb"
        if (orb / "bus_bridge.py").exists():
            continue
        source = PAYLOAD / "top_ui"
        for item in sorted(source.rglob("*")):
            if item.is_file() and "__pycache__" not in item.parts:
                target = base / "ui" / item.relative_to(source)
                if target.name == "__init__.py" and target.exists():
                    continue
                copy_file(item, target)
        ok(f"ui/orb restaurado em {base}")


def apply_python_fixes(active_trees: list[Path]) -> None:
    say("\n== Backend ==")
    for tree in active_trees:
        fix_multiuser(tree)
        fix_user_rules(tree)
        fix_restart_route(tree)
        fix_plugin_registry(tree)
        fix_text_encoding(tree)
    fix_scheduler(active_trees)
    add_missing_modules(active_trees)
    ok("Correcoes do backend aplicadas")


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------

LOAD_PROFILES = """async function loadProfiles() {
    // JA_LOAD_RETRY: o backend pode demorar a responder durante o boot.
    setLoading(true);

    for (let attempt = 1; attempt <= 8; attempt += 1) {
      try {
        const response = await fetch("/api/multiuser", {
          cache: "no-store",
        });

        if (!response.ok) {
          throw new Error(await response.text());
        }

        const data = await response.json();

        setProfiles(data.profiles ?? []);
        setError("");
        setLoading(false);
        return;
      } catch {
        if (attempt < 8) {
          await new Promise((resolve) => window.setTimeout(resolve, attempt * 500));
        }
      }
    }

    setError("N\u00e3o foi poss\u00edvel carregar os usu\u00e1rios.");
    setLoading(false);
  }

"""

VITE_CHARSET = (
    '  // JA: bundle somente ASCII, imune a leitura errada de encoding.\n'
    '  esbuild: { charset: "ascii" },\n'
)


def patch_gate(path: Path) -> None:
    text = demojibake(read_text(path))
    if RETRY_MARKER not in text:
        newline = "\r\n" if "\r\n" in text else "\n"
        start = text.find("async function loadProfiles() {")
        end = text.find("  useEffect(() => {", start)
        if start < 0 or end < 0:
            warn("loadProfiles nao encontrado em UserSelectorGate.tsx")
        else:
            text = text[:start] + LOAD_PROFILES.replace("\n", newline) + text[end:]
    write_text(path, text)


def patch_frontend_source(frontend: Path) -> None:
    source = frontend / "src"
    for relative in REGEX_FILES:
        path = source / relative
        if path.exists():
            write_text(path, fix_regex_text(read_text(path)))
        else:
            warn(f"{path} nao encontrado")

    for path in sorted(source.rglob("*.ts*")):
        if path.suffix in (".ts", ".tsx"):
            try:
                raw = read_text(path)
            except UnicodeDecodeError:
                warn(f"{path} nao esta em UTF-8")
                continue
            if RANGE_BROKEN in raw or RANGE_LITERAL in raw:
                write_text(path, fix_regex_text(raw))

    for relative in MOJIBAKE_FILES:
        path = source / relative
        if not path.exists():
            warn(f"{path} nao encontrado")
        elif path.name == "UserSelectorGate.tsx":
            patch_gate(path)
        else:
            write_text(path, demojibake(read_text(path)))

    vite = frontend / "vite.config.ts"
    if vite.exists():
        text = demojibake(read_text(vite))
        anchor = 'assetsInclude: ["**/*.glb"],'
        if 'charset: "ascii"' not in text:
            if anchor in text:
                newline = "\r\n" if "\r\n" in text else "\n"
                text = text.replace(
                    anchor, anchor + newline + VITE_CHARSET.replace("\n", newline).rstrip("\r\n"), 1
                )
            else:
                warn("vite.config.ts em formato inesperado; charset nao aplicado")
        write_text(vite, text)


def find_tool(name: str) -> str | None:
    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    candidate = program_files / "nodejs" / f"{name}.cmd"
    if candidate.exists():
        return str(candidate)
    if name == "node" and (program_files / "nodejs/node.exe").exists():
        return str(program_files / "nodejs/node.exe")
    return shutil.which(name)


def run(command: list[str], *, cwd: Path | None = None, timeout: int = 300, log_to: Path | None = None,
        env: dict[str, str] | None = None) -> int:
    try:
        result = subprocess.run(
            command, cwd=cwd, timeout=timeout, env=env, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.SubprocessError) as exc:
        if log_to:
            with log_to.open("a", encoding="utf-8") as handle:
                handle.write(f"$ {command}\n{exc}\n")
        return 1
    if log_to:
        with log_to.open("a", encoding="utf-8") as handle:
            handle.write(f"$ {command}\n{result.stdout}\n")
    return result.returncode


def check_bundle(dist: Path, log_to: Path) -> bool:
    node = find_tool("node")
    assets = dist / "assets"
    index = dist / "index.html"
    if not index.is_file() or not assets.is_dir():
        return False
    for reference in re.findall(r'(?:src|href)="/(assets/[^"]+\.(?:js|css))"', read_text(index)):
        if not (dist / reference).is_file():
            warn(f"index.html referencia arquivo ausente: {reference}")
            return False
    broken = RANGE_BROKEN.encode("utf-8")
    for path in assets.glob("*.js"):
        if broken in path.read_bytes():
            warn(f"regex corrompido em {path.name}")
            return False
    if not node:
        warn("Node nao encontrado; compilacao dos bundles nao verificada")
        return True
    checker = PAYLOAD / "check_bundle.mjs"
    code = run(
        [node, "--experimental-vm-modules", "--no-warnings", str(checker), str(assets)],
        log_to=log_to, timeout=300,
    )
    return code == 0


def build_frontend(frontend: Path, log_to: Path) -> Path | None:
    npx = find_tool("npx")
    npm = find_tool("npm")
    if not npx:
        warn("Node/npx nao encontrado; usando reparo direto do dist")
        return None
    if not (frontend / "node_modules/vite").exists():
        say("Instalando dependencias do frontend...")
        if not npm or run([npm, "ci", "--no-audit", "--no-fund"], cwd=frontend, timeout=900, log_to=log_to):
            warn("npm ci falhou; usando reparo direto do dist")
            return None
    target = ROOT / "ja_builds" / f"update-{STAMP}" / "dist"
    env = dict(os.environ)
    env.setdefault("NODE_OPTIONS", "--max-old-space-size=4096")
    say("Gerando o frontend (pode levar alguns minutos)...")
    code = run(
        [npx, "vite", "build", "--outDir", str(target), "--emptyOutDir"],
        cwd=frontend, timeout=1200, log_to=log_to, env=env,
    )
    if code != 0:
        warn("vite build falhou; usando reparo direto do dist")
        return None
    if not check_bundle(target, log_to):
        warn("O build novo nao passou na validacao; usando reparo direto do dist")
        shutil.rmtree(target.parent, ignore_errors=True)
        return None
    return target


def repair_dist(dist: Path) -> int:
    fixed = 0
    broken = RANGE_BROKEN.encode("utf-8")
    literal = RANGE_LITERAL.encode("utf-8")
    for path in sorted((dist / "assets").glob("*.js")):
        raw = path.read_bytes()
        strings = b"ja.selectedUser" in raw or "Rein\u00c3\u00adcio".encode("utf-8") in raw
        if broken not in raw and literal not in raw and not strings:
            continue
        text = raw.decode("utf-8-sig")
        if broken in raw or strings:
            text = demojibake(text)
        text = fix_regex_text(text)
        data = text.encode("utf-8")
        if data != raw:
            write_bytes(path, data)
            fixed += 1
    return fixed


def publish_dist(built: Path, dist: Path) -> None:
    if dist.exists():
        saved = BACKUP / "dist" / str(len(manifest["dirs"]))
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(dist), str(saved))
        manifest["dirs"].append({"path": str(dist), "backup": str(saved)})
    else:
        manifest["dirs"].append({"path": str(dist), "backup": None})
    save_manifest()
    shutil.copytree(built, dist)


def apply_frontend(active_trees: list[Path], build_log: Path) -> bool:
    say("\n== Frontend ==")
    frontends = [
        tree / "ui/web/frontend"
        for tree in active_trees
        if (tree / "ui/web/frontend/src").is_dir()
    ]
    if not frontends:
        warn("Codigo-fonte do frontend nao encontrado")
    for frontend in frontends:
        patch_frontend_source(frontend)
    ok("Fonte do frontend corrigida")

    dists = [tree / "ui/web/dist" for tree in active_trees]
    built = build_frontend(frontends[0], build_log) if frontends else None
    if built:
        for dist in dists:
            publish_dist(built, dist)
        shutil.rmtree(built.parent, ignore_errors=True)
        ok("Frontend reconstruido e publicado")
    else:
        for dist in dists:
            if (dist / "assets").is_dir():
                ok(f"{repair_dist(dist)} arquivo(s) reparados em {dist}")

    result = True
    for dist in dists:
        if not dist.exists():
            continue
        valid = check_bundle(dist, build_log)
        result = result and valid
        (ok if valid else warn)(f"Validacao do bundle em {dist}: {'OK' if valid else 'FALHOU'}")
    return result


# ---------------------------------------------------------------------------
# Ferramentas, registro e validacao
# ---------------------------------------------------------------------------

def update_tools() -> None:
    say("\n== Ferramentas do JA ==")
    (ROOT / "ja_patches").mkdir(parents=True, exist_ok=True)
    copy_file(PAYLOAD / "check_bundle.mjs", ROOT / "ja_patches/check_bundle.mjs")

    for name in ("JA-FIX-SEGUNDO-SELETOR.ps1", "ja_login_progressivo_safe.ps1"):
        path = ROOT / name
        if path.exists():
            raw = path.read_bytes()
            bom = raw.startswith(b"\xef\xbb\xbf")
            text = raw.decode("utf-8-sig").replace(
                "$T=Get-Content $Gate -Raw\n", "$T=Get-Content $Gate -Raw -Encoding UTF8\n"
            ).replace(
                "$T=Get-Content $Gate -Raw\r\n", "$T=Get-Content $Gate -Raw -Encoding UTF8\r\n"
            )
            write_bytes(path, (b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))

    script = ROOT / "ja_build_frontend.ps1"
    if script.exists():
        raw = script.read_bytes()
        bom = raw.startswith(b"\xef\xbb\xbf")
        text = raw.decode("utf-8-sig")
        newline = "\r\n" if "\r\n" in text else "\n"
        old = newline.join((
            'Get-ChildItem "$SrcDist\\assets" -Filter *.js -File | ForEach-Object {',
            '    cmd.exe /d /c "node --check ""$($_.FullName)"" >nul 2>&1"',
            '    if($LASTEXITCODE -ne 0){ $Bad++ }',
            '}',
        ))
        new = newline.join((
            '& node --experimental-vm-modules --no-warnings "$R\\ja_patches\\check_bundle.mjs" "$SrcDist\\assets"',
            'if($LASTEXITCODE -ne 0){ $Bad++ }',
        ))
        write_bytes(script, (b"\xef\xbb\xbf" if bom else b"") + text.replace(old, new).encode("utf-8"))

    requirements = ROOT / "requirements-windows.txt"
    if requirements.exists():
        text = read_text(requirements)
        if "global-hotkeys" not in text.lower() and "global_hotkeys" not in text.lower():
            newline = "\r\n" if "\r\n" in text else "\n"
            ending = "" if text.endswith(("\n", "\r\n")) else newline
            write_text(requirements, f"{text}{ending}global-hotkeys>=0.1.7{newline}")
    ok("Ferramentas atualizadas")


def install_hotkeys(python: Path, log_to: Path) -> None:
    check = run([str(python), "-c", "import global_hotkeys"], log_to=log_to, timeout=30)
    if check == 0:
        ok("global_hotkeys ja instalado")
        return
    code = run(
        [str(python), "-m", "pip", "install", "global-hotkeys>=0.1.7"],
        log_to=log_to, timeout=180,
    )
    (ok if code == 0 else warn)(
        "global_hotkeys instalado" if code == 0 else "Nao foi possivel instalar global_hotkeys (nao impede a abertura)"
    )


def sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def update_registry() -> None:
    path = ROOT / "ja_patches/fix_registry.json"
    if not path.exists():
        warn("fix_registry.json nao encontrado")
        return
    data = json.loads(read_text(path))
    changed = 0
    now = datetime.now(timezone.utc).isoformat()
    for fix in data.get("fixes", []):
        target = Path(fix.get("target", ""))
        if fix.get("id") == "frontend_unicode_regex_fix":
            if fix.get("enabled", True):
                fix.update(
                    enabled=False,
                    status="superseded",
                    note="Substituido pela correcao no source e por check_bundle.mjs.",
                )
                changed += 1
            continue
        in_new_dist = any(
            key(target).startswith(key(tree / "ui/web/dist")) for tree in (SOURCE_TREE, RUNTIME_TREE)
        )
        if key(target) in touched or (in_new_dist and fix.get("enabled", True)):
            if target.is_file():
                fix["sha256"] = sha256(target)
                fix["registered_at"] = now
                if fix.get("backup"):
                    copy_file(target, Path(fix["backup"]))
                changed += 1
    fixes = data.setdefault("fixes", [])
    if not any(fix.get("id") == "ja_update_20261102" for fix in fixes):
        fixes.append({
            "id": "ja_update_20261102",
            "description": "Encoding, regex, multiusuario, restart, Orb e event loop.",
            "target": str(SOURCE_TREE / "ui/web/multiuser_routes.py"),
            "backup": str(BACKUP),
            "sha256": sha256(SOURCE_TREE / "ui/web/multiuser_routes.py"),
            "registered_at": now,
            "enabled": True,
            "status": "validated",
        })
    write_text(path, json.dumps(data, indent=2, ensure_ascii=False))
    ok(f"Registro de correcoes atualizado ({changed} item(ns))")


def compile_python() -> list[str]:
    errors: list[str] = []
    for item in touched:
        path = Path(item)
        if path.suffix == ".py" and path.exists():
            try:
                py_compile.compile(str(path), cfile=str(BACKUP / "compile.pyc"), doraise=True)
            except py_compile.PyCompileError as exc:
                errors.append(str(exc))
    return errors


IMPORT_TEST = """
import importlib
for name in (
    "dodaios.ui.web.multiuser_routes", "dodaios.ui.web.ja_update_auth",
    "dodaios.society.credentials", "dodaios.ui.web.agent_chat_routes",
    "dodaios.marketplace.plugin_registry", "ui.orb.bus_bridge",
):
    importlib.import_module(name)
from dodaios.tasks.scheduler import TaskScheduler
assert hasattr(TaskScheduler, "attach_owner_gate")
print("IMPORTS=OK")
"""


def import_test(python: Path, log_to: Path) -> bool:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    result = run([str(python), "-c", IMPORT_TEST], cwd=ROOT, env=env, log_to=log_to, timeout=240) == 0
    env["PYTHONPATH"] = str(ROOT)
    return run([str(python), "-c", IMPORT_TEST], cwd=ROOT, env=env, log_to=log_to, timeout=240) == 0 and result


PATCHED_FILES = (
    "agent_chat/service.py",
    "agent_chat/tools.py",
    "ui/desktop_app.py",
    "ui/web/lifecycle_guard.py",
    "ui/web/surface_security.py",
)

PATCH_SOURCE = """
import importlib.util, os, pathlib
spec = importlib.util.spec_from_file_location("ja_patch", os.environ["JA_PATCH_SCRIPT"])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.SITE = pathlib.Path(os.environ["JA_SOURCE_TREE"])
for name in ("qwen_runner", "window_controls", "self_healing", "restart_guard", "loopback_origin"):
    getattr(module, name)()
module.validate()
"""


def run_patch_guard(python: Path, log_to: Path) -> None:
    script = ROOT / "ja_patches/apply_ja_patches.py"
    if not script.exists():
        return
    for tree in (SOURCE_TREE, RUNTIME_TREE):
        for relative in PATCHED_FILES:
            if (tree / relative).exists():
                backup_file(tree / relative)
    code = run([str(python), str(script)], cwd=ROOT, log_to=log_to, timeout=180)
    (ok if code == 0 else warn)(f"Patch manager do JA: codigo {code}")
    if not SOURCE_TREE.is_dir():
        return
    env = dict(os.environ, JA_PATCH_SCRIPT=str(script), JA_SOURCE_TREE=str(SOURCE_TREE))
    code = run([str(python), "-c", PATCH_SOURCE], cwd=ROOT, log_to=log_to, timeout=120, env=env)
    (ok if code == 0 else warn)(f"Patches levados para o source: codigo {code}")


def check_persistent_fixes(python: Path, log_to: Path) -> None:
    script = ROOT / "ja_patches/enforce_persistent_fixes.py"
    if not script.exists():
        return
    code = run([str(python), str(script)], cwd=ROOT, log_to=log_to, timeout=180)
    if code == 0:
        ok("Anti-regressao do JA")
    else:
        warn(f"Anti-regressao do JA retornou {code}; detalhes em logs/anti_regression.log")


# ---------------------------------------------------------------------------
# Processos e teste de abertura
# ---------------------------------------------------------------------------

def stop_app() -> None:
    if sys.platform != "win32":
        return
    script = r"""
$venv = $env:JA_VENV + '\*'
$keep = @([int]$env:JA_KEEP_A, [int]$env:JA_KEEP_B)
Get-CimInstance Win32_Process | Where-Object {
    ($keep -notcontains [int]$_.ProcessId) -and (
        $_.Name -eq 'DodaiosApp.exe' -or
        ($_.ExecutablePath -and $_.ExecutablePath -like $venv) -or
        ($_.CommandLine -and $_.CommandLine -like '*dodaios.ui.web.launcher*') -or
        ($_.Name -like 'python*' -and $_.CommandLine -like '*-m dodaios*') -or
        ($_.Name -eq 'msedgewebview2.exe' -and $_.CommandLine -like '*DodaiosApp*')
    )
} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
"""
    env = dict(os.environ, JA_VENV=str(VENV), JA_KEEP_A=str(os.getpid()), JA_KEEP_B=str(os.getppid()))
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", script],
        env=env, capture_output=True, timeout=60, check=False,
    )
    time.sleep(2)


def fetch(path: str, timeout: float = 5) -> tuple[int, bytes]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{PORT}{path}", timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except OSError:
        return 0, b""


def open_test(python: Path) -> bool:
    say("\n== Teste de abertura ==")
    log_path = LOGS / f"ja-update-{STAMP}-boot.log"
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    with log_path.open("w", encoding="utf-8") as handle:
        process = subprocess.Popen(
            [str(python), "-m", "dodaios.ui.web.launcher", "--headless", "--background-service"],
            cwd=ROOT, env=env, stdout=handle, stderr=subprocess.STDOUT,
        )
        ready = False
        deadline = time.time() + 150
        while time.time() < deadline and process.poll() is None:
            if fetch("/api/health")[0] == 200:
                ready = True
                break
            time.sleep(2)

        passed = ready
        if ready:
            time.sleep(6)
            for path in ("/", "/api/multiuser", "/api/tasks"):
                status, body = 0, b""
                for _ in range(15):
                    status, body = fetch(path, timeout=30)
                    if status == 200:
                        break
                    time.sleep(2)
                (ok if status == 200 else warn)(f"GET {path} -> {status}")
                passed = passed and status == 200
                if path == "/api/multiuser" and status == 200:
                    try:
                        names = [item.get("id") for item in json.loads(body).get("profiles", [])]
                        say(f"Perfis encontrados: {names}")
                        if not names:
                            warn("Nenhum perfil encontrado; confira a pasta profiles")
                    except ValueError:
                        warn("/api/multiuser nao retornou JSON")
        else:
            warn(f"Backend nao respondeu. Log: {log_path}")

        if process.poll() is None:
            process.terminate()
    stop_app()
    return passed


# ---------------------------------------------------------------------------
# Desfazer
# ---------------------------------------------------------------------------

def rollback(folder: Path | None = None) -> int:
    if folder is None:
        candidates = [
            path for path in sorted(BACKUPS.glob("update-*/manifest.json"))
            if any(json.loads(path.read_text(encoding="utf-8")).values())
        ]
        if not candidates:
            say("Nenhuma atualizacao para desfazer.")
            return 1
        folder = candidates[-1].parent
    say(f"Desfazendo a partir de {folder}")
    stop_app()
    data = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    for item in reversed(data.get("dirs", [])):
        path = Path(item["path"])
        if path.exists():
            shutil.rmtree(path)
        if item.get("backup"):
            shutil.move(item["backup"], str(path))
    for item in reversed(data.get("files", [])):
        path = Path(item["path"])
        if item.get("backup"):
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item["backup"], path)
        elif path.exists():
            path.unlink()
    (folder / "manifest.json").rename(folder / "manifest.restored.json")
    say("Atualizacao desfeita. Abra o JA normalmente.")
    return 0


# ---------------------------------------------------------------------------
# Principal
# ---------------------------------------------------------------------------

def write_report(status: str) -> Path:
    LOGS.mkdir(parents=True, exist_ok=True)
    report = LOGS / f"ja-update-{STAMP}.txt"
    text = "\n".join([
        f"RESULTADO={status}",
        f"BACKUP={BACKUP}",
        f"ARQUIVOS_ALTERADOS={len(touched)}",
        f"AVISOS={len(warnings)}",
        "",
        *lines,
    ])
    report.write_text(text + "\n", encoding="utf-8")
    try:
        (HERE / f"RELATORIO-{STAMP}.txt").write_text(text + "\n", encoding="utf-8")
    except OSError:
        pass
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rollback", action="store_true")
    parser.add_argument("--no-open-test", action="store_true")
    parser.add_argument("--no-pip", action="store_true")
    args = parser.parse_args()

    if args.rollback:
        return rollback()

    say(f"===== ATUALIZACAO DO JA {STAMP} =====")
    say(f"Instalacao: {ROOT}")
    python = VENV / "Scripts" / "python.exe" if sys.platform == "win32" else Path(sys.executable)
    active = trees()
    if not active:
        say("ERRO: nem o source nem o runtime do JA foram encontrados.")
        write_report("FALHOU")
        return 1
    for tree in active:
        say(f"Arvore: {tree}")

    LOGS.mkdir(parents=True, exist_ok=True)
    build_log = LOGS / f"ja-update-{STAMP}-build.log"
    save_manifest()

    say("Fechando o JA...")
    stop_app()

    try:
        apply_python_fixes(active)
        bundle_ok = apply_frontend(active, build_log)
        update_tools()
        errors = compile_python()
    except Exception as exc:  # noqa: BLE001 - qualquer falha desfaz a alteracao parcial
        say(f"ERRO: {exc!r}. Desfazendo.")
        rollback(BACKUP)
        write_report("FALHOU")
        return 1

    if errors:
        say("ERRO de compilacao. Desfazendo.")
        for error in errors:
            say(error)
        rollback(BACKUP)
        write_report("FALHOU")
        return 1
    ok("Compilacao do Python")

    say("\n== Validacao ==")
    imports_ok = import_test(python, build_log)
    (ok if imports_ok else warn)(f"Imports: {'OK' if imports_ok else 'FALHOU; veja o log de build'}")
    if not args.no_pip:
        install_hotkeys(python, build_log)
    run_patch_guard(python, build_log)
    update_registry()
    check_persistent_fixes(python, build_log)

    opened = True
    if not args.no_open_test:
        opened = open_test(python)

    success = bundle_ok and imports_ok and opened
    status = "OK" if success and not warnings else ("OK_COM_AVISOS" if success else "ATENCAO")
    report = write_report(status)
    say(f"\nRESULTADO={status}")
    say(f"Relatorio: {report}")
    if success:
        say("Abra o JA normalmente.")
    else:
        say("Envie o relatorio. Para voltar ao estado anterior, use DESFAZER-ATUALIZACAO.cmd.")
    return 0 if success else 2


if __name__ == "__main__":
    raise SystemExit(main())
