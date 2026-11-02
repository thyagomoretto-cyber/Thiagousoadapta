$lms = "C:\Users\ME Arquitetura\.lmstudio\bin\lms.exe"

Start-Sleep -Seconds 5

& $lms server start | Out-Null

Start-Sleep -Seconds 5

$loaded = ((& $lms ps 2>&1) -join "
")

if ($loaded -notmatch '(?m)^qwen/qwen3\.5-9b\s') {
    & $lms load "qwen/qwen3.5-9b" --gpu max --yes
}

Start-Sleep -Seconds 2
