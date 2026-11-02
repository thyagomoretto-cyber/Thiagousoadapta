$R="$env:USERPROFILE\.dodaios"
$Pkg="$R\.venv\Lib\site-packages\dodaios"
$Src="$R\dodaios\ui\web\frontend"
$Base="$R\JA_BASELINE_ESTAVEL_WINDOWS"

Write-Host "===== RESTAURANDO JA BASELINE ESTAVEL WINDOWS ====="

Copy-Item "$Base\App.tsx" "$Src\src\App.tsx" -Force
Copy-Item "$Base\UserSelectorGate.tsx" "$Src\src\components\UserSelectorGate.tsx" -Force

Remove-Item "$Pkg\ui\web\dist" -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item "$Base\dist" "$Pkg\ui\web\dist" -Recurse -Force

Copy-Item "$Base\desktop_app.py" "$Pkg\ui\desktop_app.py" -Force

if(Test-Path "$Base\multiuser_routes.py"){
    Copy-Item "$Base\multiuser_routes.py" "$Pkg\ui\web\multiuser_routes.py" -Force
}

Write-Host "JA_BASELINE_ESTAVEL_WINDOWS=RESTAURADO"
