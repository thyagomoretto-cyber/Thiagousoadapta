from pathlib import Path
import shutil
import hashlib
import json
import time

HOME = Path.home()
LOCAL = HOME / ".dodaios"
SYNC = HOME / ".dodaios-sync"

FILES = [
    "global/native_rules.json",
    "global/multiuser.json",
    "profiles/thiago/profile.json",
    "profiles/thiago/rules.json",
    "profiles/thiago/preferences.json",
    "data/core_memory.json",
    "data/workspace/USER.md",
    "data/workspace/SOUL.md",
]

STATE_FILE = SYNC / ".sync-state-windows.json"

def sha(path):
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except Exception:
        return None

def mtime(path):
    try:
        return path.stat().st_mtime
    except Exception:
        return 0

def load_state():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")

def copy(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)

def sync_once():
    state = load_state()

    for rel in FILES:
        local = LOCAL / rel
        shared = SYNC / rel

        lh = sha(local)
        sh = sha(shared)

        if lh is None and sh is None:
            continue

        previous = state.get(rel, {})
        prev_local = previous.get("local")
        prev_shared = previous.get("shared")

        # primeira execução: arquivos já estão iguais
        if prev_local is None and prev_shared is None:
            if lh is None and sh is not None:
                copy(shared, local)
            elif sh is None and lh is not None:
                copy(local, shared)
            elif lh != sh:
                if mtime(local) >= mtime(shared):
                    copy(local, shared)
                else:
                    copy(shared, local)

        else:
            local_changed = lh != prev_local
            shared_changed = sh != prev_shared

            if local_changed and not shared_changed:
                if local.exists():
                    copy(local, shared)

            elif shared_changed and not local_changed:
                if shared.exists():
                    copy(shared, local)

            elif local_changed and shared_changed and lh != sh:
                if mtime(local) >= mtime(shared):
                    copy(local, shared)
                else:
                    copy(shared, local)

        state[rel] = {
            "local": sha(local),
            "shared": sha(shared),
            "updated": time.time(),
        }

    save_state(state)

if __name__ == "__main__":
    while True:
        try:
            sync_once()
        except Exception:
            pass
        time.sleep(5)

