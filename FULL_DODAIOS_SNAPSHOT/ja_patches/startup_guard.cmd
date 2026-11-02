@echo off
"%USERPROFILE%\.dodaios\.venv\Scripts\python.exe" "%USERPROFILE%\.dodaios\ja_patches\enforce_change_policy.py"
"%USERPROFILE%\.dodaios\.venv\Scripts\python.exe" "%USERPROFILE%\.dodaios\ja_patches\apply_ja_patches.py" >> "%USERPROFILE%\.dodaios\logs\startup_patch_guard.log" 2>&1


"%USERPROFILE%\.dodaios\.venv\Scripts\python.exe" "%USERPROFILE%\.dodaios\ja_patches\enforce_persistent_fixes.py"

