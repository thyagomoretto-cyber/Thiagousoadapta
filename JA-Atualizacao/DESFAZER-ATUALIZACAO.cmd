@echo off
chcp 65001 >nul
set "JA_PY=%USERPROFILE%\.dodaios\.venv\Scripts\python.exe"
if not exist "%JA_PY%" (
  echo Python do JA nao encontrado em "%JA_PY%".
  pause
  exit /b 1
)
"%JA_PY%" -X utf8 "%~dp0ja_update.py" --rollback
echo.
pause
