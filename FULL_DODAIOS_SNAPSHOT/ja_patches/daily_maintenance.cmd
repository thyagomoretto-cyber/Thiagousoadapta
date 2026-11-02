@echo off
"%USERPROFILE%\.dodaios\.venv\Scripts\python.exe" "%USERPROFILE%\.dodaios\ja_patches\enforce_change_policy.py"
"%USERPROFILE%\.dodaios\.venv\Scripts\python.exe" "%USERPROFILE%\.dodaios\ja_patches\daily_maintenance.py" >> "%USERPROFILE%\.dodaios\logs\daily_maintenance.log" 2>&1


"%USERPROFILE%\.dodaios\.venv\Scripts\python.exe" "%USERPROFILE%\.dodaios\ja_patches\enforce_persistent_fixes.py"

