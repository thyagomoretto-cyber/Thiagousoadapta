from pathlib import Path
import json
import shutil

ROOT = Path.home() / ".dodaios"
POLICY = ROOT / "ja_policies" / "change_classification.json"
SNAPSHOT = ROOT / "ja_patches" / "change_policy_snapshot.json"

if not POLICY.exists() and SNAPSHOT.exists():
    POLICY.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SNAPSHOT, POLICY)
    print("CHANGE_POLICY=RESTAURADO")
else:
    try:
        json.loads(POLICY.read_text(encoding="utf-8-sig"))
        print("CHANGE_POLICY=OK")
    except Exception:
        if SNAPSHOT.exists():
            shutil.copy2(SNAPSHOT, POLICY)
            print("CHANGE_POLICY=REPARADO")
        else:
            raise
