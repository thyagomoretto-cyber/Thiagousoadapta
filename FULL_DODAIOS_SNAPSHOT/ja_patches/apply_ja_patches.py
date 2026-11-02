from __future__ import annotations

from pathlib import Path
from datetime import datetime
import json
import re
import shutil
import subprocess
import sys
import unicodedata

ROOT = Path.home() / ".dodaios"
SITE = ROOT / ".venv" / "Lib" / "site-packages" / "dodaios"
PATCH = ROOT / "ja_patches"
BACKUPS = ROOT / "ja_backups"
LOGS = ROOT / "logs"

BACKUPS.mkdir(parents=True, exist_ok=True)
LOGS.mkdir(parents=True, exist_ok=True)

def log(msg):
    print(msg)
    try:
        with (LOGS / "ja_patch_manager.log").open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')} {msg}\n")
    except Exception:
        pass

def backup(path, tag):
    if not path.exists():
        return
    stamp = datetime.now().strftime("%Y%m%d")
    dst = BACKUPS / f"{path.name}.{tag}.{stamp}.bak"
    if not dst.exists():
        shutil.copy2(path, dst)

def normalize(text):
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).casefold()

# ============================================================
# QWEN LOCAL -> API
# ============================================================

def qwen_runner():
    p = SITE / "agent_chat" / "service.py"

    if not p.exists():
        log("QWEN_RUNNER=ARQUIVO_AUSENTE")
        return False

    s = p.read_text(encoding="utf-8")

    marker = "# JA QWEN LOCAL API OVERRIDE"

    if marker in s:
        log("QWEN_RUNNER=JA_OK")
        return True

    backup(p, "qwen")

    patch = r'''

# JA QWEN LOCAL API OVERRIDE
_JA_ORIGINAL_RESOLVE_RUNNER = resolve_runner

def resolve_runner(provider, *args, **kwargs):
    if str(provider or "").strip().lower() == "local-openai":
        return "api"
    return _JA_ORIGINAL_RESOLVE_RUNNER(provider, *args, **kwargs)
'''

    p.write_text(s + patch, encoding="utf-8")
    log("QWEN_RUNNER=REAPLICADO")
    return True

# ============================================================
# CONTROLES NATIVOS WINDOWS
# ============================================================

def window_controls():
    p = SITE / "ui" / "desktop_app.py"

    if not p.exists():
        log("WINDOW_CONTROLS=ARQUIVO_AUSENTE")
        return False

    s = p.read_text(encoding="utf-8")

    pos = s.find("def _main_window_kwargs")
    if pos < 0:
        log("WINDOW_CONTROLS=FUNCAO_NAO_ENCONTRADA")
        return False

    end = s.find("\n    def ", pos + 10)
    if end < 0:
        end = pos + 2500

    section = s[pos:end]

    if '"frameless": False' in section:
        log("WINDOW_CONTROLS=JA_OK")
        return True

    old = '"frameless": sys.platform != "darwin",'

    if old not in section:
        log("WINDOW_CONTROLS=PADRAO_DESCONHECIDO")
        return False

    backup(p, "window")

    new_section = section.replace(
        old,
        '"frameless": False,  # JA PERSISTENT: native Windows controls',
        1,
    )

    s = s[:pos] + new_section + s[end:]
    p.write_text(s, encoding="utf-8")

    log("WINDOW_CONTROLS=REAPLICADO")
    return True

# ============================================================
# GLOBAL RULES
# ============================================================

def global_rules():
    current = ROOT / "GLOBAL_RULES.md"
    template = PATCH / "GLOBAL_RULES.template.md"

    if not template.exists():
        if current.exists():
            shutil.copy2(current, template)
        else:
            log("GLOBAL_RULES=SEM_TEMPLATE")
            return False

    wanted = template.read_text(
        encoding="utf-8-sig",
        errors="replace"
    )

    if not current.exists():
        shutil.copy2(template, current)
        log("GLOBAL_RULES=RESTAURADO")
        return True

    existing = current.read_text(
        encoding="utf-8-sig",
        errors="replace"
    )

    n = normalize(existing)

    required = (
        "self healing",
        "pesquisar automaticamente na web",
        "editar e reescrever seu proprio codigo",
        "persistent learning",
    )

    if all(x in n for x in required):
        log("GLOBAL_RULES=JA_OK")
        return True

    backup(current, "global-rules")
    current.write_text(wanted, encoding="utf-8")

    log("GLOBAL_RULES=RESTAURADO")
    return True

# ============================================================
# SELF HEALING OPERACIONAL
# ============================================================

def self_healing():
    p = SITE / "agent_chat" / "tools.py"

    if not p.exists():
        log("SELF_HEALING=ARQUIVO_AUSENTE")
        return False

    s = p.read_text(encoding="utf-8")

    marker = "# JA OPERATIONAL SELF HEALING"

    if marker in s:
        log("SELF_HEALING=JA_OK")
        return True

    backup(p, "self-healing")

    patch = r'''

# JA OPERATIONAL SELF HEALING
_JA_ORIGINAL_EXECUTE_TOOL = execute_tool

async def execute_tool(name: str, args: dict[str, Any], *, cwd: Path) -> tuple[str, bool]:

    output, is_error = await _JA_ORIGINAL_EXECUTE_TOOL(
        name,
        args,
        cwd=cwd,
    )

    if not is_error:
        return output, False

    try:
        import json
        import time

        log_dir = Path.home() / ".dodaios" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)

        event = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "tool": str(name),
            "arg_keys": sorted(str(k) for k in (args or {}).keys()),
            "cwd": str(cwd),
            "error": str(output)[:4000],
        }

        with (log_dir / "self_healing.jsonl").open(
            "a",
            encoding="utf-8"
        ) as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")

    except Exception:
        pass

    recovery = f"""
[JA_OPERATIONAL_ERROR]

A ferramenta {name!r} falhou.

ERRO:
{output}

Nao encerre automaticamente a tarefa.

Analise o erro.
Descubra a causa.
Inspecione configuracoes, arquivos, logs e dependencias.
Pesquise documentacao ou web se necessario.
Crie uma correcao.
Faca backup quando apropriado.
Aplique a correcao.
Teste novamente.
Continue o pedido original.

Nao repita cegamente a mesma acao.
Use nova hipotese se a primeira correcao falhar.
""".strip()

    return recovery, True
'''

    p.write_text(s + patch, encoding="utf-8")

    log("SELF_HEALING=REAPLICADO")
    return True

# ============================================================
# FRONTEND RESTART ROUTE
# ============================================================

def restart_frontend():
    dist = SITE / "ui" / "web" / "dist"

    if not dist.exists():
        log("RESTART_FRONTEND=DIST_AUSENTE")
        return False

    changed = 0
    found_new = False

    for p in dist.rglob("*.js"):
        try:
            s = p.read_text(encoding="utf-8")
        except Exception:
            continue

        if "/api/settings/restart-app" in s:
            found_new = True

        if "/api/multiuser/restart" in s:
            backup(p, "restart-route")

            s = s.replace(
                "/api/multiuser/restart",
                "/api/settings/restart-app"
            )

            p.write_text(s, encoding="utf-8")
            changed += 1
            found_new = True

    if changed:
        log(f"RESTART_FRONTEND=REAPLICADO_{changed}")
    elif found_new:
        log("RESTART_FRONTEND=JA_OK")
    else:
        log("RESTART_FRONTEND=ROTA_NAO_LOCALIZADA")

    return found_new

# ============================================================
# LIFECYCLE GUARD LOCAL
# ============================================================

def restart_guard():
    p = SITE / "ui" / "web" / "lifecycle_guard.py"

    if not p.exists():
        log("RESTART_GUARD=ARQUIVO_AUSENTE")
        return False

    s = p.read_text(encoding="utf-8")

    marker = "# JA: allow explicit lifecycle clicks"

    if marker in s:
        log("RESTART_GUARD=JA_OK")
        return True

    old = '''    if authorization.strip() or (require_origin and not origin.strip()):
        raise HTTPException(
'''

    if old not in s:
        log("RESTART_GUARD=PADRAO_DESCONHECIDO")
        return False

    backup(p, "restart-guard")

    new = '''    # JA: allow explicit lifecycle clicks coming from our own local web UI.
    host = ""
    try:
        host = str(getattr(request.url, "hostname", "") or "").lower()
    except Exception:
        pass

    local_ui = host in {"127.0.0.1", "localhost", "::1"}

    if (authorization.strip() and not local_ui) or (
        require_origin and not origin.strip()
    ):
        raise HTTPException(
'''

    p.write_text(s.replace(old, new, 1), encoding="utf-8")

    log("RESTART_GUARD=REAPLICADO")
    return True

# ============================================================
# LOOPBACK ORIGIN
# ============================================================

def loopback_origin():
    p = SITE / "ui" / "web" / "surface_security.py"

    if not p.exists():
        log("LOOPBACK_ORIGIN=ARQUIVO_AUSENTE")
        return False

    s = p.read_text(encoding="utf-8")

    marker = "# JA: pywebview may load the desktop UI"

    if marker in s:
        log("LOOPBACK_ORIGIN=JA_OK")
        return True

    old = '''    origin = _parse_origin(values[0])
    if origin is None:
        return False
    if origin == _scope_origin(scope):
        return True
'''

    if old not in s:
        log("LOOPBACK_ORIGIN=PADRAO_DESCONHECIDO")
        return False

    backup(p, "loopback-origin")

    new = '''    origin = _parse_origin(values[0])
    if origin is None:
        return False
    if origin == _scope_origin(scope):
        return True

    # JA: pywebview may load the desktop UI through localhost while the
    # backend resolves through 127.0.0.1, or vice versa.
    try:
        from urllib.parse import urlsplit

        raw_origin = urlsplit(values[0])
        origin_host = (raw_origin.hostname or "").lower()

        server = scope.get("server") or ("", 0)
        server_host = str(server[0] or "").lower()

        loopbacks = {"localhost", "127.0.0.1", "::1"}

        if origin_host in loopbacks and server_host in loopbacks:
            return True

    except Exception:
        pass
'''

    p.write_text(s.replace(old, new, 1), encoding="utf-8")

    log("LOOPBACK_ORIGIN=REAPLICADO")
    return True

# ============================================================
# PYTHON VALIDATION
# ============================================================

def validate():
    targets = [
        SITE / "agent_chat" / "service.py",
        SITE / "agent_chat" / "tools.py",
        SITE / "ui" / "desktop_app.py",
        SITE / "ui" / "web" / "lifecycle_guard.py",
        SITE / "ui" / "web" / "surface_security.py",
    ]

    existing = [str(x) for x in targets if x.exists()]

    result = subprocess.run(
        [sys.executable, "-m", "py_compile", *existing],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        log("PYTHON_VALIDATION=OK")
        return True

    log("PYTHON_VALIDATION=ERRO")
    log(result.stderr[-3000:])
    return False

def main():

    log("===== JA PATCH MANAGER =====")

    results = {
        "qwen_runner": qwen_runner(),
        "window_controls": window_controls(),
        "global_rules": global_rules(),
        "self_healing": self_healing(),
        "restart_frontend": restart_frontend(),
        "restart_guard": restart_guard(),
        "loopback_origin": loopback_origin(),
    }

    results["python_validation"] = validate()

    state = {
        "version": 2,
        "last_apply": datetime.now().isoformat(timespec="seconds"),
        "results": results,
    }

    (PATCH / "manifest.json").write_text(
        json.dumps(state, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print()

    for key, value in results.items():
        print(f"{key} = {value}")

    print()

    if all(results.values()):
        print("JA_PATCH_MANAGER=OK")
        return 0

    print("JA_PATCH_MANAGER=ATENCAO")
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
