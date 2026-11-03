$lms = 'C:\Users\ME Arquitetura\.lmstudio\bin\lms.exe'

Start-Sleep -Seconds 8

& $lms daemon up
Start-Sleep -Seconds 3

& $lms load "qwen/qwen3.5-9b" --context-length 32768 --gpu max --yes
Start-Sleep -Seconds 2

& $lms server start --port 1234 --bind 0.0.0.0
