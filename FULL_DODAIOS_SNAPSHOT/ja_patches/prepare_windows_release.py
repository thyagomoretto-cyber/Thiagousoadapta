from pathlib import Path
from datetime import datetime, timezone
import json
import re
import shutil
import sys

ROOT = Path.home() / ".dodaios"
POLICY = ROOT / "ja_policies" / "change_classification.json"
PATCHES = ROOT / "ja_patches"
RELEASES = ROOT / "ja_releases" / "windows"
VERSION_STATE = RELEASES / "current_version.json"

RELEASES.mkdir(parents=True, exist_ok=True)

def load_json(path, default=None):
    if default is None:
        default = {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default

def save_json(path, data):
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

def bump_patch(version):
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version.strip())
    if not m:
        raise ValueError(f"Versao invalida: {version}")
    a, b, c = map(int, m.groups())
    return f"{a}.{b}.{c+1}"

policy = load_json(POLICY)

if not policy:
    print("POLICY=NAO_ENCONTRADA")
    raise SystemExit(1)

state = load_json(
    VERSION_STATE,
    {
        "platform": "windows",
        "version": "0.1.0"
    }
)

current = state.get("version", "0.1.0")
new_version = bump_patch(current)

category = "core_global"

if len(sys.argv) >= 2:
    category = sys.argv[1].strip()

allowed = {
    "core_global",
    "companies_structural",
    "company_specific"
}

if category not in allowed:
    print("CATEGORY=INVALIDA")
    raise SystemExit(1)

publish_update = bool(
    policy["categories"][category]["publish_update"]
)

if not publish_update:
    print("CATEGORY=COMPANY_SPECIFIC")
    print("GLOBAL_UPDATE=NAO")
    raise SystemExit(2)

release = RELEASES / new_version
release.mkdir(parents=True, exist_ok=True)

# ------------------------------------------------------------
# VERSION.JSON
# ------------------------------------------------------------

version_data = {
    "product": "JA",
    "platform": "windows",
    "channel": "stable",
    "version": new_version,
    "previous_version": current,
    "category": category,
    "published_at": None,
    "prepared_at": datetime.now(timezone.utc).isoformat(),
    "update_format": "powershell",
    "manifest": "manifest.json",
    "update_script": "update.ps1"
}

save_json(release / "version.json", version_data)

# ------------------------------------------------------------
# MANIFEST.JSON
# ------------------------------------------------------------

manifest = {
    "schema": 1,
    "product": "JA",
    "platform": "windows",
    "version": new_version,
    "category": category,
    "distribution": "global",
    "policy": {
        "backup_before_apply": True,
        "healthcheck_after_apply": True,
        "rollback_on_failure": True,
        "admin_machine_validation_required": True
    },
    "components": {
        "qwen_runner": True,
        "global_rules": True,
        "self_healing": True,
        "window_controls": True,
        "restart_frontend": True,
        "restart_guard": True,
        "loopback_origin": True,
        "change_classification_policy": True,
        "admin_update_policy": True
    }
}

save_json(release / "manifest.json", manifest)

# ------------------------------------------------------------
# UPDATE.PS1
# ------------------------------------------------------------

update_ps1 = r'''param(
    [switch]$ValidateOnly
)

$Root="$env:USERPROFILE\.dodaios"
$Py="$Root\.venv\Scripts\python.exe"
$Patch="$Root\ja_patches\apply_ja_patches.py"

Write-Host "===== JA WINDOWS UPDATE ====="

if (!(Test-Path $Py)) {
    Write-Host "PYTHON_VENV=NAO_ENCONTRADO"
    exit 1
}

if (!(Test-Path $Patch)) {
    Write-Host "PATCH_MANAGER=NAO_ENCONTRADO"
    exit 1
}

if ($ValidateOnly) {
    Write-Host "VALIDATE_ONLY=OK"
    & $Py $Patch
    exit $LASTEXITCODE
}

$Backup="$Root\ja_backups\release-" + (Get-Date -Format "yyyyMMdd-HHmmss")
New-Item -ItemType Directory -Force $Backup | Out-Null

Write-Host "BACKUP_DIR=$Backup"

Copy-Item "$Root\GLOBAL_RULES.md" $Backup -ErrorAction SilentlyContinue
Copy-Item "$Root\global\multiuser.json" $Backup -ErrorAction SilentlyContinue
Copy-Item "$Root\ja_policies" "$Backup\ja_policies" -Recurse -ErrorAction SilentlyContinue
Copy-Item "$Root\ja_patches" "$Backup\ja_patches" -Recurse -ErrorAction SilentlyContinue

Write-Host "BACKUP=OK"

& $Py $Patch

if ($LASTEXITCODE -ne 0) {
    Write-Host "HEALTHCHECK=FALHOU"
    Write-Host "UPDATE=ABORTADA"
    exit 1
}

Write-Host "HEALTHCHECK=OK"
Write-Host "JA_WINDOWS_UPDATE=OK"
'''

(release / "update.ps1").write_text(
    update_ps1,
    encoding="utf-8"
)

# ------------------------------------------------------------
# CHANGELOG
# ------------------------------------------------------------

changelog = f"""# JA Windows {new_version}

Categoria: {category}

Versao anterior: {current}
Nova versao: {new_version}

Esta versao foi preparada automaticamente pelo publicador do JA.

Antes de publicar:
- testar no computador administrador;
- executar update.ps1 -ValidateOnly;
- confirmar patch manager;
- confirmar interface;
- confirmar Qwen local;
- confirmar restart;
- confirmar usuarios/perfis;
- confirmar modulo Empresas quando aplicavel.

Somente depois da validacao esta versao deve ser publicada no canal stable.
"""

(release / "CHANGELOG.md").write_text(
    changelog,
    encoding="utf-8"
)

# ------------------------------------------------------------
# VALIDACAO LOCAL
# ------------------------------------------------------------

required = [
    release / "version.json",
    release / "manifest.json",
    release / "update.ps1",
    release / "CHANGELOG.md"
]

missing = [str(x) for x in required if not x.exists()]

if missing:
    print("RELEASE_VALIDATION=ERRO")
    print(missing)
    raise SystemExit(1)

state["version"] = new_version
state["prepared_at"] = datetime.now(timezone.utc).isoformat()
state["status"] = "prepared_not_published"
save_json(VERSION_STATE, state)

print("PLATFORM=windows")
print("CATEGORY=", category)
print("PREVIOUS_VERSION=", current)
print("NEW_VERSION=", new_version)
print("GLOBAL_UPDATE=SIM")
print("RELEASE_DIR=", release)
print("RELEASE_VALIDATION=OK")
print("JA_WINDOWS_RELEASE_PREPARED=OK")
