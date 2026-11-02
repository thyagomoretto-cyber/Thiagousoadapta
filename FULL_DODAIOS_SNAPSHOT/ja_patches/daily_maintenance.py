from pathlib import Path
import subprocess
import sys

ROOT = Path.home() / ".dodaios"
DIR = ROOT / "ja_patches"

def run(name):
    path = DIR / name

    result = subprocess.run(
        [sys.executable, str(path)],
        text=True,
    )

    return result.returncode

print("===== JA DAILY MAINTENANCE =====")

# Primeiro verifica se existe nova versao.
run("check_updates.py")

# Depois garante que nenhuma correcao JA regrediu.
code = run("apply_ja_patches.py")

print("JA_DAILY_MAINTENANCE=OK" if code == 0 else "JA_DAILY_MAINTENANCE=ATENCAO")
