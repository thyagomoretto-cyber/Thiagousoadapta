$ErrorActionPreference = "Stop"

$R="$env:USERPROFILE\.dodaios"
$Src="$R\dodaios\ui\web\frontend"
$Gate="$Src\src\components\UserSelectorGate.tsx"
$Dist="$R\dodaios\ui\web\dist"
$RunDist="$R\.venv\Lib\site-packages\dodaios\ui\web\dist"
$Stamp=Get-Date -Format "yyyyMMdd-HHmmss"
$Bak="$R\ja_backups\login-progressivo-$Stamp"

Write-Host "===== JA LOGIN PROGRESSIVO SAFE ====="

New-Item $Bak -ItemType Directory -Force | Out-Null
Copy-Item $Gate "$Bak\UserSelectorGate.tsx" -Force

$T=Get-Content $Gate -Raw

# Localiza o handler atual da seleção
if($T -notmatch 'await fetch\("/api/multiuser/select"'){
    Write-Host "ERRO=PADRAO_SELECT_NAO_ENCONTRADO"
    Read-Host "ENTER"
    return
}

# Troca await fetch por disparo da requisição em background
$T=$T -replace `
'const response = await fetch\("/api/multiuser/select",', `
'const selectRequest = fetch("/api/multiuser/select",'

# Coloca abertura imediata da interface antes da espera da resposta
$T=$T -replace `
'(const selectRequest = fetch\("/api/multiuser/select",[\s\S]*?\}\);)', `
'$1' + "`r`n`r`n    onSelected(profile.id);"

# Onde antes usava response, passa a aguardar a resposta depois
$T=$T -replace `
'(\s*)if \(!response\.ok\)', `
'$1const response = await selectRequest;$1if (!response.ok)'

# Remove chamadas duplicadas posteriores
$seen=$false
$T=[regex]::Replace($T,'onSelected\(profile\.id\);',{
    param($m)
    if(!$script:seen){
        $script:seen=$true
        return $m.Value
    }
    return ""
})

Set-Content $Gate $T -Encoding UTF8

Write-Host "SOURCE_PATCH=OK"

Set-Location $Src

& "$env:ProgramFiles\nodejs\npx.cmd" vite build --outDir ../dist --emptyOutDir

if($LASTEXITCODE -ne 0){
    Write-Host "VITE_BUILD=ERRO"
    Copy-Item "$Bak\UserSelectorGate.tsx" $Gate -Force
    Read-Host "ENTER"
    return
}

Write-Host "VITE_BUILD=OK"

$Bad=0
Get-ChildItem "$Dist\assets" -File -Filter *.js | ForEach-Object {
    & node --check $_.FullName 2>$null
    if($LASTEXITCODE -ne 0){ $Bad++ }
}

if($Bad -gt 0){
    Write-Host "JS_VALIDATION=ERRO ($Bad)"
    Read-Host "ENTER"
    return
}

Write-Host "JS_VALIDATION=OK"

$RuntimeBak="$R\ja_backups\runtime-before-progressive-$Stamp"
Copy-Item $RunDist $RuntimeBak -Recurse -Force

Remove-Item $RunDist -Recurse -Force
Copy-Item $Dist $RunDist -Recurse -Force

Write-Host ""
Write-Host "RUNTIME=ATUALIZADO"
Write-Host "JA_LOGIN_PROGRESSIVO=OK"
Write-Host "BACKUP=$RuntimeBak"
Write-Host ""
Read-Host "ENTER PARA FECHAR"
