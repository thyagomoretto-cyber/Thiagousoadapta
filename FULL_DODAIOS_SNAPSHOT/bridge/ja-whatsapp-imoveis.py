#!/usr/bin/env python3
"""Le um grupo do WhatsApp Web e coloca os imoveis na fila do DodaiOS.

  python ja-whatsapp-imoveis.py --entrar            abre para ler o QR Code
  python ja-whatsapp-imoveis.py --grupo "Imoveis"   le o grupo

Cada mensagem de texto comeca um imovel, e as fotos abaixo dela pertencem a ele.
So le: nunca envia mensagem. Usa um perfil separado do Chrome, guardado nesta
maquina e fora do repositorio.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
ROOT = Path(os.environ.get("JA_WHATSAPP_RAIZ") or Path.home() / ".dodaios")
PROFILE = ROOT / "whatsapp-perfil"
URL = os.environ.get("JA_WHATSAPP_URL") or "https://web.whatsapp.com/"
DIAGNOSTIC = Path(os.environ.get("JA_KENLO_RELATORIOS") or Path.home() / "Downloads") / "whatsapp-diagnostico.txt"
LOGIN_TIMEOUT_MS = 180_000
ALREADY_IN_MS = 45_000
READY = '#pane-side, [data-testid="chat-list"], [aria-label="Lista de conversas"]'
MESSAGES = "[data-id]"
SEARCH = (
    'input[aria-label*="esquis"], input[placeholder*="esquis"], input[aria-label*="earch"], input[placeholder*="earch"], '
    '[contenteditable="true"][role="textbox"], [data-testid="chat-list-search"]'
)
CHATS_WAIT_MS = 45_000
NEW_PROPERTY = re.compile(r"\bc[oó]digo\b", re.IGNORECASE)
MAX_PAGES = 40
SYNC_WAIT_S = 120
STILL_ROUNDS = 3
WHEEL_PIXELS = 500
WHEEL_WAIT_MS = 900
VIEWER_WAIT_MS = 1_500
VIEWER_STEP_MS = 500
PHOTO_WAIT_S = 20
MAX_MISSED_PHOTOS = 2

# O WhatsApp muda a estrutura da pagina: sem o seletor de texto, usa o texto visivel.
READ_MESSAGES_JS = """() => {
  const large = (image) => image.naturalWidth > 60 || image.width > 60;
  const noise = /^(\\d{1,2}:\\d{2}|encaminhada|forwarded|\\+\\d{1,3}|[\\s\\u200e]*)$/i;
  return [...(document.querySelector('#main') || document).querySelectorAll('[data-id]')].filter((node) => !node.parentElement.closest('[data-id]')).map((node) => {
    const texts = [...node.querySelectorAll('span.selectable-text, [data-testid="selectable-text"]')];
    const images = [...node.querySelectorAll('img')].filter(large);
    const more = images.length ? (node.innerText.match(/^\\s*\\+(\\d{1,3})\\s*$/m) || [])[1] : 0;
    const plain = node.innerText.split('\\n').filter((line) => !noise.test(line.trim())).join('\\n').trim();
    return { id: node.getAttribute('data-id'), text: texts.map((item) => item.innerText).join('\\n').trim() || plain, images: images.length, more: more ? Number(more) : 0 };
  });
}"""

SHAPE_JS = """() => ({
  endereco: location.href.slice(0, 60),
  tem_main: !!document.querySelector('#main'),
  tem_lista: !!document.querySelector('#pane-side'),
  tamanho_texto: document.body.innerText.length,
  campos: [...document.querySelectorAll('input, textarea, [contenteditable=true]')].map((node) => [node.tagName, node.type || '', node.getAttribute('role'), node.getAttribute('aria-label'), node.getAttribute('placeholder'), node.getAttribute('data-testid')].join(' | ')).slice(0, 15),
  titulos: document.querySelectorAll('span[title]').length,
  botoes: [...document.querySelectorAll('[role=button], button')].map((node) => (node.getAttribute('aria-label') || node.innerText || '').slice(0, 30)).filter(Boolean).slice(0, 20),
  linhas: document.querySelectorAll('[data-id]').length,
  linhas_div: document.querySelectorAll('div[data-id]').length,
  papel_linha: document.querySelectorAll('[role=row]').length,
  texto_selecionavel: document.querySelectorAll('span.selectable-text, [data-testid="selectable-text"]').length,
  amostra: [...document.querySelectorAll('[data-id]')].slice(-30).map((node) => ({
    tag: node.tagName,
    dentro_de_outra: !!node.parentElement.closest('[data-id]'),
    testes: [...new Set([...node.querySelectorAll('[data-testid]')].map((item) => item.getAttribute('data-testid')))].slice(0, 12),
    imagens: [...node.querySelectorAll('img')].map((image) => [image.src.slice(0, 5), image.width, image.naturalWidth]).slice(0, 6),
    fundos: node.querySelectorAll('[style*="background-image"]').length,
    texto: node.innerText.slice(0, 60).replace(/\\d/g, '9'),
  })),
})"""
FIRST_IMAGE_JS = """(id) => {
  const node = [...document.querySelectorAll('[data-id]')].find((item) => item.getAttribute('data-id') === id);
  return [...(node ? node.querySelectorAll('img') : [])].find((image) => image.naturalWidth > 60 || image.width > 60) || null;
}"""

SAVE_LARGEST_JS = """async () => {
  const area = (image) => { const box = image.getBoundingClientRect(); return box.width * box.height; };
  const images = [...document.querySelectorAll("img[src^='blob:']")].filter((image) => area(image) > 0).sort((a, b) => area(b) - area(a));
  if (!images.length) return null;
  const blob = await (await fetch(images[0].src)).blob();
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let binary = '';
  for (let at = 0; at < bytes.length; at += 8192) binary += String.fromCharCode(...bytes.subarray(at, at + 8192));
  return { src: images[0].src, data: btoa(binary), type: blob.type };
}"""


def group_messages(messages: list[dict]) -> list[dict]:
    """Junta cada texto com as fotos que vieram logo abaixo dele."""
    groups: list[dict] = []
    for message in messages:
        # O quadro "+4" ja e uma das imagens contadas e esconde mais quatro.
        more = message.get("more", 0)
        count = message.get("images", 0) + (more - 1 if more else 0)
        text = (message.get("text") or "").strip()
        if text and (not count or NEW_PROPERTY.search(text)):
            groups.append({"text": text, "first_photo": message["id"] if count else None, "photos": count, "albuns": [(message["id"], count)] if count else []})
        elif groups and count:
            current = groups[-1]
            current["first_photo"] = current["first_photo"] or message["id"]
            current["photos"] += count
            current["albuns"].append((message["id"], count))  # WhatsApp divide muitas fotos em mais de um album
            if text:
                current["text"] += "\n" + text
    return groups


def fill_screen(context):
    """Abre a janela ocupando a tela: pequena, o Kenlo esconde partes da pagina."""
    try:
        page = context.pages[0] if context.pages else context.new_page()
        session = context.new_cdp_session(page)
        window = session.send("Browser.getWindowForTarget")["windowId"]
        session.send("Browser.setWindowBounds", {"windowId": window, "bounds": {"windowState": "normal"}})
        session.send("Browser.setWindowBounds", {"windowId": window, "bounds": {"windowState": "maximized"}})
        session.detach()
    except Exception as exc:
        print(f"AVISO=janela nao maximizada: {exc}", flush=True)
    return context


def browser(playwright):
    PROFILE.mkdir(parents=True, exist_ok=True)
    channel = os.environ.get("JA_WHATSAPP_CANAL", "chrome") or None
    return fill_screen(playwright.chromium.launch_persistent_context(str(PROFILE), channel=channel, headless=bool(os.environ.get("JA_WHATSAPP_OCULTO")), accept_downloads=False, no_viewport=True))


def open_group(page, name: str) -> None:
    """Clica no grupo se ele estiver na lista; se nao, procura pela busca."""
    group = page.locator(f'span[title="{name}"], span:text-is("{name}")').first
    try:
        group.wait_for(state="visible", timeout=CHATS_WAIT_MS)
    except Exception:
        page.locator(SEARCH).first.click(timeout=CHATS_WAIT_MS)
        page.keyboard.type(name, delay=30)
        group.wait_for(state="visible", timeout=CHATS_WAIT_MS)
    group.click()
    page.wait_for_selector(f"#main {MESSAGES}, {MESSAGES}", timeout=30_000)
    page.wait_for_timeout(1500)


def wait_synced(page) -> None:
    """Esta janela e um aparelho separado: as mensagens novas chegam ao sincronizar."""
    limit = time.monotonic() + SYNC_WAIT_S
    while time.monotonic() < limit:
        if not re.search(r"sincronizando|syncing", page.evaluate("() => document.body.innerText").lower()):
            return
        print("WHATSAPP_SINCRONIZANDO", flush=True)
        page.wait_for_timeout(3000)


def wheel(page, distance: int) -> None:
    """Rola a conversa como uma pessoa: sem pular, para o WhatsApp carregar o texto."""
    box = page.evaluate("() => { const box = (document.querySelector('#main') || document.body).getBoundingClientRect(); return [box.left + box.width / 2, box.top + box.height / 2]; }")
    page.mouse.move(box[0], box[1])
    page.mouse.wheel(0, distance)
    page.wait_for_timeout(WHEEL_WAIT_MS)


def older_than_start(page, first_code: int) -> bool:
    from dodaios.core import property_intake as intake

    codes = [intake.code_of(intake.property_key(message["text"])) for message in page.evaluate(READ_MESSAGES_JS) if NEW_PROPERTY.search(message.get("text") or "")]
    return first_code > 0 and any(code is not None and code < first_code for code in codes)


def read_all(page, first_code: int = 0) -> list[dict]:
    """Sobe ate antes do primeiro codigo e desce lendo tudo, em ordem, ate o fim do grupo."""
    wait_synced(page)
    page.wait_for_timeout(2000)
    last_top, still = "", 0
    for _ in range(MAX_PAGES):
        if older_than_start(page, first_code):
            break
        top = page.evaluate("() => (document.querySelector('#main [data-id]') || {getAttribute() { return ''; }}).getAttribute('data-id')")
        still = still + 1 if top == last_top else 0
        last_top = top
        if still >= STILL_ROUNDS:
            break
        wheel(page, -WHEEL_PIXELS)
    found: dict[str, dict] = {}
    still = 0
    for _ in range(MAX_PAGES * 2):
        before = len(found)
        for message in page.evaluate(READ_MESSAGES_JS):
            known = found.setdefault(message["id"], message)
            if message.get("text") and not known.get("text"):
                known.update(message)
        still = still + 1 if len(found) == before else 0
        if still >= STILL_ROUNDS:
            break
        wheel(page, WHEEL_PIXELS)
    return list(found.values())


def reveal(page, message_id: str) -> None:
    """Traz a mensagem de volta para a tela, para abrir as fotos dela."""
    for distance in (-WHEEL_PIXELS, WHEEL_PIXELS):
        for _ in range(MAX_PAGES):
            if page.evaluate(FIRST_IMAGE_JS, message_id):
                return
            wheel(page, distance)


def viewer_place(page) -> tuple[int, int]:
    """Posicao da foto aberta, como em "3 de 8"; zero se a tela nao mostrar."""
    found = re.search(r"\b(\d+) de (\d+)\b", page.evaluate("() => document.body.innerText"))
    return (int(found.group(1)), int(found.group(2))) if found else (0, 0)


def wait_place(page, wanted: int) -> None:
    limit = time.monotonic() + PHOTO_WAIT_S
    while time.monotonic() < limit and viewer_place(page)[0] > wanted:
        page.wait_for_timeout(200)


def next_photo(page, seen: set[str]) -> dict | None:
    """Espera a foto seguinte carregar em vez de achar que o album acabou."""
    limit = time.monotonic() + PHOTO_WAIT_S
    while time.monotonic() < limit:
        photo = page.evaluate(SAVE_LARGEST_JS)
        if photo and photo["src"] not in seen:
            return photo
        page.wait_for_timeout(400)
    return None


def save_photos(page, message_id: str, count: int, folder: Path, first_number: int = 1) -> list[str]:
    """Abre a primeira foto e percorre o visualizador para pegar o tamanho real."""
    folder.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    reveal(page, message_id)
    image = page.evaluate_handle(FIRST_IMAGE_JS, message_id).as_element()
    if not image:
        return saved
    image.click()
    page.wait_for_timeout(VIEWER_WAIT_MS)
    # O visualizador mostra "3 de 8": pode abrir no meio do album, entao volta ao comeco.
    place, total = viewer_place(page)
    for _ in range(max(place - 1, 0)):
        page.keyboard.press("ArrowLeft")
        wait_place(page, viewer_place(page)[0] - 1)
    count = total or count
    seen: set[str] = set()
    missed = 0
    for number in range(count):
        photo = next_photo(page, seen)
        if photo:
            seen.add(photo["src"])
            path = folder / f"{first_number + number:02d}.{'png' if 'png' in photo['type'] else 'jpg'}"
            path.write_bytes(base64.b64decode(photo["data"]))
            saved.append(str(path))
        else:
            missed += 1
            if missed > MAX_MISSED_PHOTOS:
                break  # uma foto lenta nao derruba as seguintes
        if number + 1 < count:
            page.keyboard.press("ArrowRight")
            page.wait_for_timeout(VIEWER_STEP_MS)
    if len(saved) != count:
        print(f"WHATSAPP_FOTOS_INCOMPLETAS={len(saved)} de {count}", flush=True)
    page.keyboard.press("Escape")
    page.wait_for_timeout(500)
    return saved


def diagnose(page) -> None:
    """Grava a estrutura da pagina, sem conteudo de conversas."""
    DIAGNOSTIC.parent.mkdir(parents=True, exist_ok=True)
    DIAGNOSTIC.write_text(json.dumps(page.evaluate(SHAPE_JS), ensure_ascii=False, indent=1), encoding="utf-8")


def open_chat(page, name: str) -> None:
    """Abre o WhatsApp e o grupo; se precisar, espera a leitura do QR Code."""
    page.goto(URL)
    try:
        page.wait_for_selector(READY, timeout=ALREADY_IN_MS)
    except Exception:
        print("Leia o QR Code com o celular. Aguardando ate 3 minutos...", flush=True)
        page.wait_for_selector(READY, timeout=LOGIN_TIMEOUT_MS)
    try:
        open_group(page, name)
    except Exception:
        diagnose(page)
        raise SystemExit("WHATSAPP_GRUPO_NAO_ABRIU: veja o diagnostico.") from None


def scan(page) -> dict:
    """Le o grupo ja aberto e coloca na fila o que ainda nao era conhecido."""
    from dodaios.core import cadastro_plan as plan, property_intake as intake

    new, known, photos, last_code = 0, 0, 0, 0
    try:
        first_code = int(plan.load_rules().get("codigo_inicial", 0))
    except (OSError, ValueError):
        first_code = 0
    items = group_messages(read_all(page, first_code))
    if not items:
        diagnose(page)
    print("WHATSAPP_FICHAS=" + json.dumps([{"inicio": re.sub(r"\d{4,}", "#", item["text"])[:30], "fotos": item["photos"]} for item in items[-6:]], ensure_ascii=False), flush=True)
    for item in reversed(items):
        key = intake.property_key(item["text"])
        last_code = max(last_code, intake.code_of(key) or 0)
        if intake.before_start(key, first_code):
            continue
        stored: list[str] = []
        if item["first_photo"] and not intake.has_photos(key):
            for album, amount in item["albuns"]:
                stored += save_photos(page, album, amount, intake.photo_folder(key), len(stored) + 1)
        _key, is_new = intake.receive(item["text"], stored)
        new += is_new
        known += not is_new
        photos += len(stored)
    return {"novos": new, "ja_conhecidos": known, "fotos": photos, "mensagens": len(items), "maior_codigo": last_code, "codigo_inicial": first_code}


def read_group(name: str) -> dict:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        context = browser(playwright)
        page = context.pages[0] if context.pages else context.new_page()
        open_chat(page, name)
        result = scan(page)
        context.close()
    return result


def login() -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        context = browser(playwright)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(URL)
        try:
            page.wait_for_selector(READY, timeout=ALREADY_IN_MS)
        except Exception:
            print("Leia o QR Code com o celular. Aguardando ate 3 minutos...", flush=True)
            page.wait_for_selector(READY, timeout=LOGIN_TIMEOUT_MS)
        time.sleep(5)
        context.close()
    print("WHATSAPP_LOGIN=OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--entrar", action="store_true")
    parser.add_argument("--grupo", default="")
    args = parser.parse_args()
    if args.entrar:
        login()
        return 0
    if not args.grupo.strip():
        print("Informe --grupo")
        return 1
    print("WHATSAPP_LIDO=" + json.dumps(read_group(args.grupo.strip()), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
