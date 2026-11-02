$Root = Join-Path $env:USERPROFILE ".dodaios"
$Python = Join-Path $Root ".venv\Scripts\python.exe"

Write-Host ""
Write-Host "===== VERIFICACAO JA ====="
Write-Host ""

if (Test-Path $Python) {
    Write-Host "[OK] Python JA"
} else {
    Write-Host "[ERRO] Python JA"
}

if (Test-Path (Join-Path $Root "data\jarvis.db")) {
    Write-Host "[OK] Banco jarvis.db"
} else {
    Write-Host "[ERRO] Banco jarvis.db"
}

if (Get-Command node -ErrorAction SilentlyContinue) {
    Write-Host "[OK] Node"
} else {
    Write-Host "[ERRO] Node"
}

if (Get-Command ollama -ErrorAction SilentlyContinue) {
    Write-Host "[OK] Ollama"
} else {
    Write-Host "[AVISO] Ollama nao localizado no PATH"
}

try {
    $r = Invoke-WebRequest `
        -Uri "http://127.0.0.1:47821" `
        -UseBasicParsing `
        -TimeoutSec 5

    Write-Host "[OK] JA respondendo na porta 47821"
} catch {
    Write-Host "[AVISO] JA ainda nao respondeu na porta 47821"
}

Write-Host ""
Write-Host "===== FIM ====="
Write-Host ""
Read-Host "Pressione ENTER"
