$R="$env:USERPROFILE\.dodaios"
$Base="$R\JA_BASELINE_ESTAVEL"
$Src="$R\dodaios\ui\web\frontend"
$Pkg="$R\.venv\Lib\site-packages\dodaios"

Write-Host "===== RESTAURANDO JA BASELINE ESTAVEL ====="

Copy-Item "$Base\App.tsx" `
"$Src\src\App.tsx" -Force

Copy-Item "$Base\UserSelectorGate.tsx" `
"$Src\src\components\UserSelectorGate.tsx" -Force

Remove-Item "$Pkg\ui\web\dist" -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item "$Base\dist" `
"$Pkg\ui\web\dist" -Recurse -Force

Copy-Item "$Base\desktop_app.py" `
"$Pkg\ui\desktop_app.py" -Force

Write-Host "JA_BASELINE_ESTAVEL=RESTAURADO"
