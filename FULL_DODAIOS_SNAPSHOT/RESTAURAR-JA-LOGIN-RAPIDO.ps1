$R="$env:USERPROFILE\.dodaios"
$Base="$R\JA_BASELINE_LOGIN_RAPIDO"
$Src="$R\dodaios\ui\web\frontend"
$RunDist="$R\.venv\Lib\site-packages\dodaios\ui\web\dist"

Write-Host "===== RESTAURANDO JA LOGIN RAPIDO ====="

Copy-Item "$Base\UserSelectorGate.tsx" `
"$Src\src\components\UserSelectorGate.tsx" -Force

Copy-Item "$Base\App.tsx" `
"$Src\src\App.tsx" -Force

Remove-Item $RunDist -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item "$Base\dist" $RunDist -Recurse -Force

Write-Host "JA_LOGIN_RAPIDO=RESTAURADO"
