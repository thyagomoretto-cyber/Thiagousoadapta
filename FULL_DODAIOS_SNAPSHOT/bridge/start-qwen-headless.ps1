$ErrorActionPreference = "SilentlyContinue"

$UserRoot = "C:\Users\ME Arquitetura"
$LmRoot   = "$UserRoot\.lmstudio"
$LmTemp   = "$LmRoot\.internal\temp"
$Lms      = "$LmRoot\bin\lms.exe"
$Model    = "qwen/qwen3.5-9b"
$Port     = 1234

# ------------------------------------------------------------
# IMPORTANTE:
# A tarefa roda como SYSTEM, mas o LM Studio pertence à conta
# ME Arquitetura. Forçamos o ambiente correto aqui.
# ------------------------------------------------------------

$env:USERPROFILE = $UserRoot
$env:HOME        = $UserRoot
$env:HOMEDRIVE   = "C:"
$env:HOMEPATH    = "\Users\ME Arquitetura"

$env:TEMP = $LmTemp
$env:TMP  = $LmTemp

New-Item -ItemType Directory -Force -Path $LmTemp | Out-Null

# Aguarda rede/Windows terminar de subir
Start-Sleep -Seconds 5

if (!(Test-Path $Lms)) {
    exit 10
}

# Sobe daemon LM Studio
& $Lms daemon up | Out-Null

Start-Sleep -Seconds 3

# Verifica se modelo já está carregado
$psOutput = (& $Lms ps 2>&1 | Out-String)

if ($psOutput -notmatch [regex]::Escape($Model)) {
    & $Lms load $Model --context-length 32768 --gpu max --yes | Out-Null
    Start-Sleep -Seconds 8
}

# Se já existe servidor respondendo, não duplica
try {
    $models = Invoke-RestMethod `
        -Uri "http://127.0.0.1:$Port/v1/models" `
        -TimeoutSec 3

    if ($models.data.id -contains $Model) {
        exit 0
    }
}
catch {}

# Inicia servidor OpenAI-compatible
& $Lms server start --port $Port --bind 0.0.0.0
