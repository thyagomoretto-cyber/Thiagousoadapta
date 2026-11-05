"""Perguntas de qualquer agente ao dono, por voz e na tela, em qualquer tarefa.

Quem trava chama ``ask_owner``: o app fala a pergunta, mostra em qualquer tela e
espera a resposta. Agentes podem rodar em outro processo, entao a pergunta aberta
fica num arquivo local. O que o dono confirma fica em ``respostas-aprendidas.json``,
fora do repositorio, e nao precisa ser perguntado de novo.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Final

POLL_S: Final[float] = 1.0
_NEVER_CLICK: Final[re.Pattern[str]] = re.compile(r"\b(salvar|publicar|excluir|apagar|deletar|remover|enviar)\b")
LEARNABLE: Final[frozenset[str]] = frozenset({"pular", "clicar", "valor", "texto", "passos"})
SHOW: Final[str] = "Mostrar"
RUN: Final[str] = "Executar o que escrevi"
_MAC_DIALOG: Final[tuple[str, ...]] = (
    "on run argv", "beep", "activate",
    'set picked to display dialog (item 1 of argv) default answer "" buttons (items 3 thru -1 of argv) default button (count of (items 3 thru -1 of argv)) with title "DodaiOS" giving up after (item 2 of argv as integer)',
    'return (button returned of picked) & "|||" & (text returned of picked)', "end run",
)
DEFAULT_WAIT_S: Final[float] = 600.0
BUSY_WAIT_S: Final[float] = 120.0


def _folder() -> Path:
    from dodaios.core.paths import user_data_dir

    return user_data_dir() / "data" / "agente"


def image_path() -> Path:
    return _folder() / "pergunta.png"


def _fold(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in plain if not unicodedata.combining(c)).lower().strip()


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(handle, "w", encoding="utf-8") as output:
        json.dump(data, output, ensure_ascii=False)
    os.replace(temporary, path)


def _read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def owner_name() -> str:
    return str(_read(_folder() / "perfil.json", {}).get("dono", ""))


def speak(text: str) -> None:
    """Voz do proprio sistema, sem travar quem perguntou."""
    spoken = text[:400]
    try:
        if sys.platform == "darwin":
            voices = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=10).stdout
            voice = next((line.split("  ")[0].strip() for line in voices.splitlines() if "pt_BR" in line), "")
            command = ["say", *(["-v", voice] if voice else []), spoken]
        elif sys.platform == "win32":
            script = "Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak($env:JA_FALA)"
            command = ["powershell", "-NoProfile", "-Command", script]
        else:
            engine = shutil.which("spd-say") or shutil.which("espeak-ng") or shutil.which("espeak")
            if not engine:
                return
            command = [engine, "-v", "pt", spoken] if "espeak" in engine else [engine, "-l", "pt", spoken]
        subprocess.Popen(command, env={**os.environ, "JA_FALA": spoken}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return


APP_NAME = "DodaiOS"


def dialog_command(text: str, options: list[str], seconds: float) -> list[str] | None:
    """Janela do proprio sistema, por cima de todos os aplicativos."""
    if sys.platform == "darwin":
        lines = [item for line in _MAC_DIALOG for item in ("-e", line)]
        # Tres botoes no maximo: quando ha escolhas, o ultimo sempre executa o que foi escrito.
        buttons = [*options[:2], RUN] if len(options) > 2 else (options or [RUN])
        return ["osascript", *lines, text[:900], str(int(seconds)), *buttons]
    if sys.platform == "win32":
        script = "Add-Type -AssemblyName Microsoft.VisualBasic; [Microsoft.VisualBasic.Interaction]::InputBox($env:JA_FALA, 'DodaiOS')"
        return ["powershell", "-NoProfile", "-Command", script]
    if shutil.which("zenity"):
        return ["zenity", "--entry", "--title=DodaiOS", f"--text={text[:900]}", f"--timeout={int(seconds)}"]
    return None


def dialog_answer(output: str) -> str:
    button, _, typed = output.strip().partition("|||")
    return (typed or button).strip()


PANEL_URL = "http://127.0.0.1:47821/api/company-voice/pergunta/janela"
PANEL_START_S = 6.0
PANEL_FRESH_S = 9.0
PANEL_JS = r"""
ObjC.import('Cocoa');
ObjC.import('WebKit');
function run(argv) {
  var app = $.NSApplication.sharedApplication;
  app.setActivationPolicy(1);
  var area = $.NSScreen.mainScreen.visibleFrame;
  var width = 560, height = 340;
  var box = $.NSMakeRect(area.origin.x + (area.size.width - width) / 2, area.origin.y + area.size.height - height - 16, width, height);
  var panel = $.NSPanel.alloc.initWithContentRectStyleMaskBackingDefer(box, 1 | 128 | 32768, 2, false);
  panel.setLevel(1000);
  panel.setCollectionBehavior(1 | 256);
  panel.setHidesOnDeactivate(false);
  panel.setFloatingPanel(true);
  panel.setTitlebarAppearsTransparent(true);
  panel.setTitleVisibility(1);
  panel.setBackgroundColor($.NSColor.blackColor);
  var web = $.WKWebView.alloc.initWithFrameConfiguration(panel.contentView.bounds, $.WKWebViewConfiguration.alloc.init);
  web.setAutoresizingMask(18);
  web.loadRequest($.NSURLRequest.requestWithURL($.NSURL.URLWithString(argv[0])));
  panel.contentView.addSubview(web);
  panel.orderFrontRegardless;
  panel.makeKeyWindow;
  app.run;
}
"""
PANEL_HTML = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>DodaiOS</title><style>
*{box-sizing:border-box}[hidden]{display:none!important}html,body{margin:0;height:100%;background:#0a0a0a;color:#fafafa;font:15px/1.4 -apple-system,system-ui,sans-serif}
main{height:100%;overflow:auto;padding:30px 20px 16px}h1{font-size:16px;margin:0 0 8px}p{margin:0 0 12px;white-space:pre-wrap}
img{display:block;max-width:100%;max-height:150px;margin:0 0 12px;border-radius:8px}.row{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px}
button{font:inherit;padding:8px 14px;border-radius:10px;border:1px solid #3a3a3a;background:#0a0a0a;color:#fafafa;cursor:pointer}
button.main{background:#fafafa;color:#0a0a0a;border-color:#fafafa}.send{display:flex;gap:8px}
textarea{flex:1;resize:none;font:inherit;padding:8px 10px;border-radius:10px;border:1px solid #3a3a3a;background:#161616;color:#fafafa}
#status{min-height:16px;margin-top:4px;font-size:12px;color:#a3a3a3}</style></head><body><main>
<h1>O agente precisa de você</h1><p id="text">Carregando...</p><img id="image" alt="Tela do agente" hidden><div class="row" id="options"></div>
<div class="send"><textarea id="field" rows="1" placeholder="Responda aqui"></textarea><button class="main" id="send">Enviar</button></div><div id="status"></div>
</main><script>
const base = "/api/company-voice/pergunta";
const nodes = Object.fromEntries(["text", "image", "options", "field", "send", "status"].map((id) => [id, document.getElementById(id)]));
let shown = null;
async function reply(texto) {
  if (!texto.trim()) return;
  nodes.status.textContent = "Enviando...";
  try {
    const response = await fetch(base + "/responder", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ texto }) });
    nodes.status.textContent = response.ok ? "Enviado." : "Não consegui enviar. Tente de novo.";
    if (response.ok) nodes.field.value = "";
  } catch (error) { nodes.status.textContent = "Não consegui enviar. Tente de novo."; }
}
function show(question) {
  if (!question) { nodes.text.textContent = "Nenhuma pergunta aberta."; nodes.options.replaceChildren(); nodes.image.hidden = true; shown = null; return; }
  if (question.id === shown) return;
  shown = question.id;
  nodes.text.textContent = question.texto;
  nodes.status.textContent = "";
  nodes.image.hidden = !question.imagem;
  if (question.imagem) nodes.image.src = base + "/imagem?id=" + question.id;
  nodes.options.replaceChildren(...question.opcoes.map((option) => {
    const item = document.createElement("button");
    item.textContent = option;
    item.onclick = () => reply(option);
    return item;
  }));
  nodes.field.focus();
}
const check = () => fetch(base + "?janela=1").then((response) => response.json()).then((data) => show(data.pergunta)).catch(() => {});
nodes.send.onclick = () => reply(nodes.field.value);
nodes.field.addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); reply(nodes.field.value); } });
check();
setInterval(check, 3000);
</script></body></html>"""


def _panel_mark() -> Path:
    return _folder() / "janela-viva"


def panel_seen() -> None:
    _write(_panel_mark(), {"quando": time.time()})


def panel_alive() -> bool:
    return time.time() - float(_read(_panel_mark(), {}).get("quando", 0)) < PANEL_FRESH_S


def _open_panel(seconds: float) -> subprocess.Popen[str] | None:
    """So o aviso, flutuando sobre todas as telas; o app e os outros programas ficam onde estao."""
    if sys.platform != "darwin":
        return None
    _panel_mark().unlink(missing_ok=True)
    command = ["osascript", "-l", "JavaScript", "-e", PANEL_JS, PANEL_URL]
    if shutil.which("perl"):  # fecha sozinho se o agente morrer antes de responderem
        command = ["perl", "-e", "alarm shift; exec @ARGV", str(int(seconds) + 5), *command]
    try:
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
    except OSError:
        return None
    limit = time.monotonic() + PANEL_START_S
    while time.monotonic() < limit and process.poll() is None:
        if panel_alive():
            return process
        time.sleep(0.3)
    if process.poll() is None:
        process.terminate()
    return None


def bring_app_forward() -> bool:
    """Com o app aberto, a pergunta aparece so nele: traz o app para cima de tudo."""
    if sys.platform != "darwin":
        return False
    try:
        running = subprocess.run(["osascript", "-e", f'application "{APP_NAME}" is running'], capture_output=True, text=True, timeout=5)
        if running.stdout.strip() != "true":
            return False
        return subprocess.run(["open", "-a", APP_NAME], capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _open_dialog(question_id: str, text: str, options: list[str], seconds: float) -> subprocess.Popen[str] | None:
    command = dialog_command(text, options, seconds)
    if not command:
        return None
    try:
        process = subprocess.Popen(command, env={**os.environ, "JA_FALA": text[:900]}, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    except OSError:
        return None

    def deliver() -> None:
        reply = dialog_answer(process.communicate()[0] or "")
        waiting = current()
        if reply and waiting and waiting["id"] == question_id:
            answer(reply)

    threading.Thread(target=deliver, name="pergunta-janela", daemon=True).start()
    return process


def ask_owner(text: str, options: list[str] | None = None, seconds: float = DEFAULT_WAIT_S, image: bool = False) -> str:
    """Fala, abre uma unica janela por cima de tudo e devolve a resposta; vazio sem resposta."""
    limit = time.monotonic() + min(seconds, BUSY_WAIT_S)
    while current() and time.monotonic() < limit:  # outro agente esta perguntando
        time.sleep(POLL_S)
    name = owner_name()
    full = f"{name}, {text}" if name else text[:1].upper() + text[1:]
    question = ask(full, options or [], image)
    speak(full)
    window = _open_panel(seconds)
    if not window and not bring_app_forward():
        window = _open_dialog(question, full, options or [], seconds)
    reply = wait(question, seconds)
    if window and window.poll() is None:
        window.terminate()
    return reply


def ask(text: str, options: list[str], image: bool = False) -> str:
    question = {"id": uuid.uuid4().hex[:10], "texto": text, "opcoes": options, "imagem": image, "estado": "aberta",
                "quando": datetime.now(UTC).isoformat(timespec="seconds")}
    _write(_folder() / "pergunta.json", question)
    return question["id"]


def current() -> dict[str, Any] | None:
    question = _read(_folder() / "pergunta.json", None)
    return question if question and question.get("estado") == "aberta" else None


def answer(text: str) -> bool:
    question = current()
    if not question:
        return False
    _write(_folder() / "pergunta.json", {**question, "estado": "respondida", "resposta": text})
    return True


def wait(question_id: str, seconds: float) -> str:
    """Espera a resposta; vazio se o dono nao respondeu a tempo."""
    limit = time.monotonic() + seconds
    while time.monotonic() < limit:
        question = _read(_folder() / "pergunta.json", {})
        if question.get("id") != question_id:
            return ""
        if question.get("estado") == "respondida":
            return str(question.get("resposta", ""))
        time.sleep(POLL_S)
    _write(_folder() / "pergunta.json", {"id": question_id, "estado": "expirada"})
    return ""


def interpret(text: str) -> dict[str, str]:
    """Entende a resposta falada: clicar, digitar, pular, tentar, parar, sim ou nao."""
    original = text.strip().rstrip(".!")
    plain = _fold(original)
    click = re.search(r"\bcli[cq]\w*\s+(?:(?:em|no|na|o|a|botao)\s+)*(.+)$", original, re.IGNORECASE)
    if click:
        return {"acao": "clicar", "valor": click.group(1).strip(" \"'")}
    value = re.match(r"\s*(?:digit\w*|coloc\w*|preench\w*|escrev\w*|use|usa|o valor(?:\s+[eé])?|valor(?:\s+[eé])?)\s*:?\s+(.+)$", original, re.IGNORECASE)
    if value:
        return {"acao": "valor", "valor": value.group(1).strip(" \"'")}
    if re.search(r"\bmostr\w*|\beu faco\b|\bvou fazer\b", plain):
        return {"acao": "mostrar", "valor": ""}
    for action, pattern in (("parar", r"\bpar[ae]r?\b|\bcancel"), ("pular", r"\bpul\w*|\bdeix\w*|\bignor\w*|\bsegu\w*|\bcontinu\w*"),
                            ("tentar", r"\btent\w*|de novo|novamente"), ("nao", r"^nao\b"), ("sim", r"^(sim|pode|isso|confirmo|salva)\b")):
        if re.search(pattern, plain):
            return {"acao": action, "valor": ""}
    return {"acao": "", "valor": ""}


def understand(text: str, context: str) -> dict[str, str]:
    """Pedido em frase livre: o modelo traduz; sem ele, tenta o campo de novo."""
    from dodaios.core import photo_vision as vision

    prompt = (f"Um agente esta preenchendo um formulario. Situacao: {context}\nO dono respondeu: {text}\n"
              'Responda so um JSON {"acao": "valor|clicar|pular|tentar|parar", "valor": "texto exato, se houver"}. '
              "Use valor para o que deve ser escrito no campo e clicar para o nome do botao.")
    try:
        found = json.loads(re.search(r"\{.*\}", vision._chat(prompt, 60, 300), re.DOTALL).group(0))
        if found.get("acao") in ("valor", "clicar", "pular", "tentar", "parar"):
            return {"acao": found["acao"], "valor": str(found.get("valor") or "")}
    except Exception:
        pass
    return {"acao": "tentar", "valor": ""}


def plain_error(exc: BaseException) -> str:
    lines = [line.strip() for line in str(exc).splitlines() if line.strip()]
    text = lines[0][:140] if lines else type(exc).__name__
    return "a página não respondeu" if re.search(r"timeout", text, re.IGNORECASE) else text


def with_owner(label: str, work: Callable[[], Any], show: Callable[[], Any] | None = None, tries: int = 5) -> Any:
    """Regra geral: deu problema, pergunta ao dono em vez de parar sozinho."""
    for _ in range(tries):
        try:
            return work()
        except (Exception, SystemExit) as exc:
            problem = plain_error(exc)
            print(f"PROBLEMA={label}: {str(exc).strip()[:300]}", flush=True)
            if re.search(r"has been closed", problem):
                raise
            reply = ask_owner(f"tive um problema em {label}: {problem}. O que eu devo fazer?", [SHOW if show else "Tentar de novo", "Tentar de novo" if show else "Parar", "Parar"])
            action = interpret(reply)["acao"]
            if not reply or action == "parar":
                raise
            if action == "mostrar" and show:
                show()
    return work()


def forbidden_click(text: str) -> bool:
    """Publicar ou apagar nao acontece por resposta solta nem vira regra."""
    return bool(_NEVER_CLICK.search(_fold(text)))


def learned(key: str) -> dict[str, str] | None:
    found = _read(_folder() / "respostas-aprendidas.json", {}).get(key)
    return found if found and found.get("acao") in LEARNABLE else None


def learn(key: str, decision: dict[str, str]) -> None:
    if decision.get("acao") not in LEARNABLE or forbidden_click(decision.get("valor", "")):
        return
    path = _folder() / "respostas-aprendidas.json"
    _write(path, {**_read(path, {}), key: decision})
