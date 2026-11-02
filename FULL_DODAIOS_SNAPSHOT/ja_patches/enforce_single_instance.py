from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path.home() / ".dodaios"
VENV = str(ROOT / ".venv").lower()

POWERSHELL = [
    "powershell.exe",
    "-NoProfile",
    "-Command",
]

script = r"""
Get-CimInstance Win32_Process |
Where-Object {
    $_.CommandLine -match 'dodaios' -and
    (
        $_.ExecutablePath -like '*AppData\Local\Programs\Python\Python312\python.exe' -or
        $_.ExecutablePath -like '*AppData\Local\Programs\Python\Python312\pythonw.exe'
    )
} |
ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}
"""

result = subprocess.run(
    POWERSHELL + [script],
    capture_output=True,
    text=True
)

if result.returncode != 0:
    print("SINGLE_INSTANCE_GUARD=ERROR")
    print(result.stderr.strip())
    raise SystemExit(1)

print("GLOBAL_DODAIOS_PROCESSES=REMOVED")
print("SINGLE_INSTANCE_GUARD=OK")
