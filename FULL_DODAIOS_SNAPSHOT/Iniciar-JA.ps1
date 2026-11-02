$ErrorActionPreference = "Stop"

$Root = Join-Path $env:USERPROFILE ".dodaios"
$Python = Join-Path $Root ".venv\Scripts\pythonw.exe"

if (!(Test-Path $Python)) {
    Write-Host "JA nao esta instalado corretamente."
    exit 1
}

$env:PYTHONPATH = $Root

$Existing = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
        $_.CommandLine -like "*dodaios.ui.web.launcher*"
    }

if (!$Existing) {
    Start-Process `
        -FilePath $Python `
        -ArgumentList "-m","dodaios.ui.web.launcher","--headless","--background-service" `
        -WorkingDirectory $Root `
        -WindowStyle Hidden
}

Start-Sleep -Seconds 4
