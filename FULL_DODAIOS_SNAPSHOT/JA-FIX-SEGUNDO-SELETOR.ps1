$ErrorActionPreference="Stop"

$R="$env:USERPROFILE\.dodaios"
$Py="$R\.venv\Scripts\python.exe"
$Src="$R\dodaios\ui\web\frontend"
$Gate="$Src\src\components\UserSelectorGate.tsx"
$RunDist="$R\.venv\Lib\site-packages\dodaios\ui\web\dist"
$Tmp="$R\ja_builds\second-selector-final"
$Stamp=Get-Date -Format "yyyyMMdd-HHmmss"
$Bak="$R\ja_backups\second-selector-final-$Stamp"

Write-Host "===== JA FIX SEGUNDO SELETOR ====="

New-Item $Bak -ItemType Directory -Force | Out-Null
Copy-Item $Gate "$Bak\UserSelectorGate.tsx" -Force
Copy-Item $RunDist "$Bak\dist" -Recurse -Force

$T=Get-Content $Gate -Raw

# 1. Ao montar novamente, se já escolheu usuário nesta sessão,
# entra direto sem mostrar o seletor.
$Old=@"
  useEffect(() => {
    void loadProfiles();
  }, []);
"@

$New=@"
  useEffect(() => {
    try {
      const selected = window.sessionStorage.getItem("ja.selectedUser");

      if (selected) {
        onSelected(selected);
        return;
      }
    } catch {
      // segue fluxo normal
    }

    void loadProfiles();
  }, []);
"@

if(!$T.Contains($Old)){
    Write-Host "ERRO=USEEFFECT_NAO_ENCONTRADO"
    Read-Host "ENTER"
    exit
}

$T=$T.Replace($Old,$New)

# 2. Salva a escolha ANTES de abrir o AppShell
$Old2=@"
      // JA: interface abre enquanto a ativacao termina
      onSelected(profile.id);
"@

$New2=@"
      try {
        window.sessionStorage.setItem("ja.selectedUser", profile.id);
      } catch {
        // segue mesmo sem storage
      }

      // JA: interface abre enquanto a ativacao termina
      onSelected(profile.id);
"@

if(!$T.Contains($Old2)){
    Write-Host "ERRO=ONSELECTED_NAO_ENCONTRADO"
    Read-Host "ENTER"
    exit
}

$T=$T.Replace($Old2,$New2)

Set-Content $Gate $T -Encoding UTF8

Write-Host "SOURCE_PATCH=OK"

Remove-Item $Tmp -Recurse -Force -ErrorAction SilentlyContinue
New-Item $Tmp -ItemType Directory -Force | Out-Null

Set-Location $Src

& "$env:ProgramFiles\nodejs\npx.cmd" vite build --outDir "$Tmp\dist" --emptyOutDir

if($LASTEXITCODE -ne 0){
    Write-Host "VITE_BUILD=ERRO"
    Copy-Item "$Bak\UserSelectorGate.tsx" $Gate -Force
    Read-Host "ENTER"
    exit
}

Write-Host "VITE_BUILD=OK"

$Bad=0

Get-ChildItem "$Tmp\dist\assets" -Filter *.js -File | ForEach-Object {
    node --check $_.FullName 2>$null
    if($LASTEXITCODE -ne 0){$Bad++}
}

if($Bad -gt 0){
    Write-Host "JS_VALIDATION=ERRO ($Bad)"
    Copy-Item "$Bak\UserSelectorGate.tsx" $Gate -Force
    Read-Host "ENTER"
    exit
}

Write-Host "JS_VALIDATION=OK"

Remove-Item $RunDist -Recurse -Force
Copy-Item "$Tmp\dist" $RunDist -Recurse -Force

& $Py "$R\ja_patches\register_fix.py" `
"multiuser_no_second_selector_final" `
$Gate `
"Usuario escolhido permanece ativo durante remontagem do frontend"

Write-Host ""
Write-Host "SEGUNDO_SELETOR=CORRIGIDO"
Write-Host "PERSISTENT=YES"
Write-Host "BACKUP=$Bak"
Write-Host ""

Read-Host "ENTER PARA FECHAR"
