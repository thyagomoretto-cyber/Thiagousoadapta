# JA / DodaiOS — Relatório Técnico

Atualizado em: 02/11/2026

## Atualização de 02/11/2026

Correções incluídas no código e em `JA-Atualizacao/`. Ainda precisam ser validadas em boot real no Windows.

| Item | Situação |
|---|---|
| 2. Regex | Causa corrigida: faixa escapada no source e bundle ASCII no Vite |
| 3. Encoding | Corrigido nos arquivos afetados e nos scripts PowerShell que causavam a corrupção |
| 4. Multiusuário | Leitura de perfis e novas tentativas no frontend corrigidas |
| 6 e 7. Credential lock e event loop | Leitura de tokens fora do event loop nos pontos `async` |
| 8. Orb | `ui/orb` restaurado na raiz da instalação; o import `ui.orb` está correto |
| 9. TaskScheduler | Runtime antigo é atualizado pelo instalador |
| 10. Porta 47821 | Sem alteração: o re-bind é o watchdog funcionando |
| 13. Source e runtime | Patches levados às duas árvores |
| 17. Local models | Sem alteração: o autostart cobre só Ollama; `local-openai` usa o LM Studio |
| 18. Hotkeys | Dependência adicionada |
| 21. Reinício | `ja_update_auth.py` adicionado e rota do macOS isolada |

O `dist` deste repositório só recebeu o reparo do regex. A nova tela de usuário entra no próximo build.

## Prioridade atual

Fazer o JA abrir normalmente no Windows.

O problema atual ocorre durante o boot normal do aplicativo.

---

## Arquitetura principal

Raiz:

C:\Users\ME Arquitetura\.dodaios

Source:

C:\Users\ME Arquitetura\.dodaios\dodaios

Runtime:

C:\Users\ME Arquitetura\.dodaios\.venv\Lib\site-packages\dodaios

Launcher:

DodaiosApp.exe -m dodaios.ui.web.launcher

Porta principal:

47821

---

## 1. Aplicativo não completa a abertura

Os processos principais iniciam, porém a interface não conclui
corretamente o bootstrap.

Processos observados:

- DodaiosApp.exe
- pythonw.exe
- msedgewebview2.exe

O launcher principal observado é:

dodaios.ui.web.launcher

---

## 2. Frontend com regex JavaScript inválido

Erro observado:

The interface did not load.

Uncaught SyntaxError:
Invalid regular expression
Range out of order in character class

Já houve correção anterior usando:

/[\u0300-\u036f]/g

O problema reapareceu.

Estado:
REGRESSÃO ATIVA.

---

## 3. Encoding / Mojibake

Foram observados textos como:

Quem estÃ¡ usando?
Selecione um usuÃ¡rio
NÃ£o foi possÃ­vel carregar os usuÃ¡rios.

Possível divergência de encoding entre:

- source
- build
- dist
- patches

Estado:
ATIVO.

---

## 4. Multiusuário não carrega

Perfis conhecidos:

- thiago
- mel

Arquivos:

~/.dodaios/profiles/thiago/
~/.dodaios/profiles/mel/
~/.dodaios/active_profile.json

Backend:

dodaios/ui/web/multiuser_routes.py

Frontend:

dodaios/ui/web/frontend/src/components/UserSelectorGate.tsx

Sintoma:

Não foi possível carregar os usuários.

Estado:
REGRESSÃO ATIVA.

---

## 5. Segundo seletor de usuário

Foi corrigido anteriormente usando sessionStorage.

Chave:

ja.selectedUser

Fix registrado:

multiuser_no_second_selector_final

Estado:
CORRIGIDO ANTERIORMENTE, PRECISA SER REVALIDADO.

---

## 6. Credential lock com WinError 5

Arquivo:

C:\Users\ME Arquitetura\AppData\Local\Dodaios\credential-locks\plugin-storage.lock

Erro:

[WinError 5] Acesso negado.

Afetou carregamento de vários plugins.

Foi aplicado ajuste de ACL.

Resultados:

WRITE_TEST=OK
ACL_FIX=OK

Estado:
PRECISA SER VALIDADO EM BOOT LIMPO.

---

## 7. Event loop travando

Foi registrado:

Event loop STALLED for 19.8s

O stack envolvia:

plugin_registry.py
token_store.py
credential_lock.py
filelock
plugin-storage.lock

Estado:
CAUSA PROVÁVEL IDENTIFICADA.

---

## 8. Orb / Overlay não inicia

Erro:

On-screen overlay failed to start

Código observado:

from ui.orb.bus_bridge import OrbBusBridge

Erro:

ModuleNotFoundError: No module named 'ui'

Possível caminho correto:

from dodaios.ui.orb.bus_bridge import OrbBusBridge

Não alterar sem validar.

Estado:
ATIVO.

---

## 9. TaskStack / TaskScheduler quebrado

Erro:

TaskStack init failed

/api/tasks retorna 503.

Código:

scheduler.attach_owner_gate(self._society_owner_retired)

Erro:

AttributeError:
'TaskScheduler' object has no attribute 'attach_owner_gate'

Estado:
ATIVO.

---

## 10. Porta 47821 instável

Foram observados estados:

PORT_47821=OFF

e logo depois:

PORT_47821=<PID>

Logs também indicaram:

listening socket on 0.0.0.0:47821 is dead
re-binding
WinError 64 recovery

Estado:
PRECISA SER RETESTADO.

---

## 11. Botões nativos do Windows

Correção validada.

Configuração desejada:

"frameless": False
"easy_drag": False

Também foram aplicados:

WS_CAPTION
WS_SYSMENU
WS_THICKFRAME
WS_MINIMIZEBOX
WS_MAXIMIZEBOX

Resultado validado:

WINDOWS_NATIVE_CHROME=OK
MACOS=INALTERADO
FRONTEND=INALTERADO

Estado:
CORRIGIDO E VALIDADO.

Não alterar sem necessidade.

---

## 12. Baseline não totalmente confiável

Existe:

JA_BASELINE_ESTAVEL_WINDOWS

Porém o dist restaurado dessa baseline voltou a apresentar:

- regex inválido
- problemas no frontend
- multiusuário quebrado

Conclusão:

Não considerar essa baseline 100% estável.

---

## 13. Source e Runtime divergentes

Existem duas árvores:

Source:

C:\Users\ME Arquitetura\.dodaios\dodaios

Runtime:

C:\Users\ME Arquitetura\.dodaios\.venv\Lib\site-packages\dodaios

Alguns fixes foram aplicados diretamente no runtime.

Possíveis efeitos:

- source correto e runtime antigo
- runtime correto e source antigo
- rebuild sobrescrevendo fix
- patch guard restaurando arquivo antigo

Estado:
RISCO ESTRUTURAL IMPORTANTE.

---

## 14. Frontend source e dist divergentes

Source:

dodaios/ui/web/frontend/src/

Dist:

dodaios/ui/web/dist/

O build padrão:

npm run build

executa:

tsc -b && vite build

e já falhou por erros TypeScript não relacionados.

Também foi usado:

npx vite build

Estado:
RISCO DE REGRESSÃO.

---

## 15. Sistema de persistência

Arquivos/pastas conhecidos:

ja_patches/
ja_backups/
logs/

Patch manager:

ja_patches/manifest.json
apply_ja_patches.py

Anti-regressão:

fix_registry.json
register_fix.py
enforce_persistent_fixes.py

Tarefas:

JA Startup Patch Guard
JA Daily Maintenance

Regra:

backup -> alteração -> teste -> validação -> registro.

---

## 16. Qwen / Local OpenAI

Modelo:

qwen/qwen3.5-9b

LM Studio:

porta 1234

Base URL:

http://127.0.0.1:1234

brain.primary:

local-openai

Foi aplicado override em:

agent_chat/service.py

para:

local-openai -> api

Estado:
CORRIGIDO ANTERIORMENTE.

---

## 17. Local-model autostart inconsistente

Log observado:

local-models autostart skipped

Mas também:

Text-chat brain: local-openai active

Estado:
PRECISA SER ANALISADO.

---

## 18. Global Hotkeys ausente

Erro:

global_hotkeys module absent

Resultado:

hotkeys disabled

Estado:
ATIVO, MAS NÃO É O BLOQUEADOR PRINCIPAL.

---

## 19. Wake Word

Configuração observada:

wake word = ''

Modo:

stt_match only

Estado:
NÃO PRIORITÁRIO.

---

## 20. Áudio Realtek

24000 Hz falhou.

Fallback:

48000 Hz

funcionou.

Estado:
FALLBACK FUNCIONAL.

---

## 21. Reinício

Endpoint esperado:

POST /api/settings/restart-app

O reinício apresentou comportamento inconsistente.

Importante:

NÃO É A PRIORIDADE ATUAL.

Primeiro o aplicativo precisa abrir normalmente.

---

## 22. Repositório

Repositorio:

thyagomoretto-cyber/Thiagousoadapta

Branch:

principal

Visibilidade:

PUBLIC

---

## Regra de debug

Para qualquer bug:

1. observar o aplicativo em tempo real;
2. capturar PID;
3. capturar porta;
4. capturar comando;
5. capturar logs;
6. identificar falha exata;
7. alterar somente o componente responsável;
8. testar;
9. somente após validação registrar;
10. atualizar baseline depois.

---

## Ordem recomendada

1. Fazer o JA abrir.
2. Corrigir frontend / regex.
3. Corrigir encoding.
4. Corrigir multiusuário.
5. Confirmar credential locks.
6. Confirmar event-loop.
7. Confirmar porta 47821.
8. Corrigir Orb.
9. Corrigir TaskScheduler.
10. Validar Qwen.
11. Validar Reinício.
12. Criar nova baseline.

---

## Objetivo final

Tornar o fluxo:

source -> build -> runtime

determinístico e reproduzível.

Nenhum fix deve depender apenas de alteração manual em site-packages.
