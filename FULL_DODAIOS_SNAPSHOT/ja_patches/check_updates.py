from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import importlib.metadata
import json
import subprocess
import urllib.request
import urllib.error

ROOT = Path.home() / ".dodaios"
DIR = ROOT / "ja_patches"
LOGS = ROOT / "logs"
STATE = DIR / "update_state.json"

LOGS.mkdir(parents=True, exist_ok=True)

def log(msg):
    print(msg)
    with (LOGS / "update_check.log").open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat(timespec='seconds')} {msg}\n")

def local_update_endpoint():

    try:
        from dodaios.ui.web import update_routes

        router = update_routes.router

        candidates = []

        for route in router.routes:

            methods = getattr(route, "methods", set()) or set()

            if "GET" not in methods:
                continue

            path = str(getattr(route, "path", ""))

            if "check" in path.lower():
                candidates.insert(0, path)
            elif "status" in path.lower():
                candidates.append(path)

        prefix = str(getattr(router, "prefix", "") or "")

        for path in candidates:

            full = prefix + path

            if not full.startswith("/api"):
                full = "/api/update" + full

            url = "http://127.0.0.1:47821" + full

            request = urllib.request.Request(
                url,
                headers={
                    "Origin": "http://127.0.0.1:47821",
                    "Accept": "application/json",
                },
            )

            try:
                with urllib.request.urlopen(request, timeout=10) as r:

                    body = r.read().decode("utf-8", errors="replace")

                    try:
                        data = json.loads(body)
                    except Exception:
                        data = {"raw": body}

                    return {
                        "method": "dodaios_api",
                        "endpoint": full,
                        "result": data,
                    }

            except Exception:
                continue

    except Exception:
        pass

    return None

def git_source_check():

    try:
        dist = importlib.metadata.distribution("dodaios")
        text = dist.read_text("direct_url.json")

        if not text:
            return None

        info = json.loads(text)

        url = info.get("url")
        vcs = info.get("vcs_info") or {}

        installed_commit = vcs.get("commit_id")

        if not url or not installed_commit:
            return None

        result = subprocess.run(
            ["git", "ls-remote", url, "HEAD"],
            capture_output=True,
            text=True,
            timeout=20,
        )

        if result.returncode != 0:
            return None

        remote_commit = result.stdout.strip().split()[0]

        return {
            "method": "git",
            "source": url,
            "installed_commit": installed_commit,
            "remote_commit": remote_commit,
            "update_available": remote_commit != installed_commit,
        }

    except Exception:
        return None

def main():

    try:
        version = importlib.metadata.version("dodaios")
    except Exception:
        version = "unknown"

    result = local_update_endpoint()

    if result is None:
        result = git_source_check()

    if result is None:
        result = {
            "method": "none",
            "status": "NO_UPDATE_SOURCE",
            "message": (
                "Nenhuma fonte automatica de atualizacao foi detectada. "
                "O sistema continuara verificando diariamente."
            ),
        }

    state = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "installed_version": version,
        "check": result,
    }

    STATE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    log(f"UPDATE_CHECK={result.get('method')}")
    log(f"INSTALLED_VERSION={version}")

    if result.get("update_available") is True:
        log("UPDATE_AVAILABLE=YES")
    else:
        log("UPDATE_AVAILABLE=NO_OR_UNKNOWN")

    print(json.dumps(state, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
