from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import shutil
import sys

ROOT = Path.home() / ".dodaios"
PATCH = ROOT / "ja_patches"
BACKUPS = ROOT / "ja_backups"
REGISTRY = PATCH / "fix_registry.json"

PATCH.mkdir(parents=True, exist_ok=True)
BACKUPS.mkdir(parents=True, exist_ok=True)

def load():
    return json.loads(REGISTRY.read_text(encoding="utf-8-sig"))

def save(data):
    REGISTRY.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

def digest(path: Path):
    if not path.exists() or not path.is_file():
        return None

    h = hashlib.sha256()

    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)

    return h.hexdigest()

def main():

    if len(sys.argv) < 3:
        print(
            "USO: register_fix.py <fix_id> <arquivo> "
            "[descricao]"
        )
        return 1

    fix_id = sys.argv[1].strip()
    target = Path(sys.argv[2]).expanduser()

    description = (
        sys.argv[3].strip()
        if len(sys.argv) >= 4
        else fix_id
    )

    if not target.exists():
        print(f"TARGET_NOT_FOUND={target}")
        return 1

    data = load()

    now = datetime.now(timezone.utc).isoformat()

    backup_folder = BACKUPS / "persistent_fixes" / fix_id
    backup_folder.mkdir(parents=True, exist_ok=True)

    backup = backup_folder / target.name
    shutil.copy2(target, backup)

    entry = {
        "id": fix_id,
        "description": description,
        "target": str(target),
        "backup": str(backup),
        "sha256": digest(target),
        "registered_at": now,
        "enabled": True,
        "status": "validated"
    }

    fixes = data.setdefault("fixes", [])

    replaced = False

    for i, item in enumerate(fixes):
        if item.get("id") == fix_id:
            fixes[i] = entry
            replaced = True
            break

    if not replaced:
        fixes.append(entry)

    save(data)

    print(f"FIX_REGISTERED={fix_id}")
    print("PERSISTENT=YES")
    print("BACKUP=OK")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
