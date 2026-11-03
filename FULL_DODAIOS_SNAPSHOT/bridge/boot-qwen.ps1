$env:USERPROFILE  = "C:\Users\ME Arquitetura"
$env:HOME         = "C:\Users\ME Arquitetura"
$env:LOCALAPPDATA = "C:\Users\ME Arquitetura\AppData\Local"
$env:APPDATA      = "C:\Users\ME Arquitetura\AppData\Roaming"

Start-Sleep -Seconds 10

& "C:\Users\ME Arquitetura\.lmstudio\bin\lms.exe" server start | Out-Null

Start-Sleep -Seconds 8

$loaded = ((& "C:\Users\ME Arquitetura\.lmstudio\bin\lms.exe" ps 2>&1) -join "
")

if ($loaded -notmatch '(?m)^qwen/qwen3\.5-9b\s') {
    & "C:\Users\ME Arquitetura\.lmstudio\bin\lms.exe" load "qwen/qwen3.5-9b" --context-length 32768 --gpu max --yes | Out-Null
}
