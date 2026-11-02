$ErrorActionPreference="Stop"

$R="$env:USERPROFILE\.dodaios"
$Src="$R\dodaios\ui\web\frontend"
$SrcDist="$R\dodaios\ui\web\dist"
$RunDist="$R\.venv\Lib\site-packages\dodaios\ui\web\dist"
$Log="$R\logs\frontend-build-final.log"
$Npm="$env:ProgramFiles\nodejs\npm.cmd"

New-Item "$R\logs" -ItemType Directory -Force | Out-Null

"===== JA BUILD FRONTEND FINAL =====" | Tee-Object $Log

Set-Location $Src

cmd.exe /d /c """$Npm"" run build >> ""$Log"" 2>&1"
$Code=$LASTEXITCODE

Get-Content $Log -Tail 30

if($Code -ne 0){
    Write-Host ""
    Write-Host "BUILD=ERRO"
    Write-Host "LOG=$Log"
    return
}

Write-Host "BUILD=OK"

if(!(Test-Path "$SrcDist\index.html")){
    Write-Host "ERRO=DIST_NAO_GERADO"
    return
}

$Bad=0

Get-ChildItem "$SrcDist\assets" -Filter *.js -File | ForEach-Object {
    cmd.exe /d /c "node --check ""$($_.FullName)"" >nul 2>&1"
    if($LASTEXITCODE -ne 0){ $Bad++ }
}

if($Bad -gt 0){
    Write-Host "ERRO=JS_INVALIDO ($Bad)"
    return
}

Write-Host "JS_VALIDATION=OK"

$Bak="$R\ja_backups\runtime-dist-$(Get-Date -Format yyyyMMdd-HHmmss)"
Copy-Item $RunDist $Bak -Recurse -Force

Remove-Item $RunDist -Recurse -Force
Copy-Item $SrcDist $RunDist -Recurse -Force

Write-Host ""
Write-Host "RUNTIME=ATUALIZADO"
Write-Host "JA_FRONTEND_BUILD=OK"
Write-Host "BACKUP=$Bak"
Write-Host "LOG=$Log"
