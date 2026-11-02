from __future__ import annotations

from pathlib import Path
from datetime import datetime
import hashlib
import json
import subprocess
import sys

ROOT = Path.home() / ".dodaios"
PATCH = ROOT / "ja_patches"
REGISTRY = PATCH / "fix_registry.json"
LOG = ROOT / "logs" / "anti_regression.log"

PATCH_MANAGER = PATCH / "apply_ja_patches.py"


def log(text):
    print(text)

    LOG.parent.mkdir(parents=True, exist_ok=True)

    with LOG.open("a", encoding="utf-8") as f:
        f.write(
            f"{datetime.now().isoformat(timespec='seconds')} "
            f"{text}\n"
        )


def sha(path: Path):

    if not path.exists() or not path.is_file():
        return None

    h = hashlib.sha256()

    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)

    return h.hexdigest()


def main():

    if not REGISTRY.exists():
        log("FIX_REGISTRY=MISSING")
        return 1

    try:
        data = json.loads(
            REGISTRY.read_text(encoding="utf-8-sig")
        )
    except Exception as exc:
        log(f"FIX_REGISTRY=INVALID:{exc}")
        return 1

    # Primeiro reaplica os patches oficiais do JA.
    if PATCH_MANAGER.exists():

        result = subprocess.run(
            [sys.executable, str(PATCH_MANAGER)],
            text=True
        )

        if result.returncode != 0:
            log("PATCH_MANAGER=FAILED")
            return 1

        log("PATCH_MANAGER=OK")

    regressions = []

    for fix in data.get("fixes", []):

        if not fix.get("enabled", True):
            continue

        target = Path(fix["target"])
        expected = fix.get("sha256")

        current = sha(target)

        if current is None:
            regressions.append(
                (fix["id"], "TARGET_MISSING")
            )
            continue

        if expected and current != expected:
            # Nao sobrescrevemos cegamente uma versao nova.
            # O patch manager deve reaplicar a correcao estrutural.
            regressions.append(
                (fix["id"], "CONTENT_CHANGED")
            )

    if regressions:

        for fix_id, reason in regressions:
            log(
                f"REGRESSION_DETECTED={fix_id}:{reason}"
            )

        log("ANTI_REGRESSION=ATTENTION_REQUIRED")

        # Importante: nao restaura backup antigo sobre codigo novo
        # automaticamente, evitando quebrar futuras versoes.
        return 2

    log("PERSISTENT_FIXES=OK")
    log("ANTI_REGRESSION=OK")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
