param(
    [switch]$ValidateOnly
)

$Root="$env:USERPROFILE\.dodaios"
$Py="$Root\.venv\Scripts\python.exe"
$Patch="$Root\ja_patches\apply_ja_patches.py"

Write-Host "===== JA WINDOWS UPDATE ====="

if (!(Test-Path $Py)) {
    Write-Host "PYTHON_VENV=NAO_ENCONTRADO"
    exit 1
}

if (!(Test-Path $Patch)) {
    Write-Host "PATCH_MANAGER=NAO_ENCONTRADO"
    exit 1
}

if ($ValidateOnly) {
    Write-Host "VALIDATE_ONLY=OK"
    & $Py $Patch
    exit $LASTEXITCODE
}

$Backup="$Root\ja_backups\release-" + (Get-Date -Format "yyyyMMdd-HHmmss")
New-Item -ItemType Directory -Force $Backup | Out-Null

Write-Host "BACKUP_DIR=$Backup"

Copy-Item "$Root\GLOBAL_RULES.md" $Backup -ErrorAction SilentlyContinue
Copy-Item "$Root\global\multiuser.json" $Backup -ErrorAction SilentlyContinue
Copy-Item "$Root\ja_policies" "$Backup\ja_policies" -Recurse -ErrorAction SilentlyContinue
Copy-Item "$Root\ja_patches" "$Backup\ja_patches" -Recurse -ErrorAction SilentlyContinue

Write-Host "BACKUP=OK"

& $Py $Patch

if ($LASTEXITCODE -ne 0) {
    Write-Host "HEALTHCHECK=FALHOU"
    Write-Host "UPDATE=ABORTADA"
    exit 1
}

Write-Host "HEALTHCHECK=OK"
Write-Host "JA_WINDOWS_UPDATE=OK"
