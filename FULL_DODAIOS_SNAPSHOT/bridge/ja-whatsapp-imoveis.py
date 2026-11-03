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
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("JA_WHATSAPP_RAIZ") or Path.home() / ".dodaios")
PROFILE = ROOT / "whatsapp-perfil"
URL = os.environ.get("JA_WHATSAPP_URL") or "https://web.whatsapp.com/"
LOGIN_TIMEOUT_MS = 180_000
READY = '#pane-side, [data-testid="chat-list"], [aria-label="Lista de conversas"]'
MESSAGES = "div[data-id]"
SCROLLS = 12
VIEWER_WAIT_MS = 1_500
OPEN_IMAGE_JS = "img[src^='blob:']"

READ_MESSAGES_JS = """() => [...document.querySelectorAll('div[data-id]')].map((node) => {
  const texts = [...node.querySelectorAll('span.selectable-text, [data-testid="selectable-text"]')];
  const images = [...node.querySelectorAll("img[src^='blob:']")].filter((image) => image.naturalWidth > 60 || image.width > 60);
  const more = (node.innerText.match(/\\+(\\d+)/) || [])[1];
  return { id: node.getAttribute('data-id'), text: texts.map((item) => item.innerText).join('\\n').trim(), images: images.length, more: more ? Number(more) : 0 };
})"""

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
        count = message.get("images", 0) + message.get("more", 0)
        text = (message.get("text") or "").strip()
        if text and not count:
            groups.append({"text": text, "first_photo": None, "photos": 0})
        elif groups and count:
            current = groups[-1]
            current["first_photo"] = current["first_photo"] or message["id"]
            current["photos"] += count
            if text:
                current["text"] += "\n" + text
    return groups


def browser(playwright):
    PROFILE.mkdir(parents=True, exist_ok=True)
    channel = os.environ.get("JA_WHATSAPP_CANAL", "chrome") or None
    return playwright.chromium.launch_persistent_context(str(PROFILE), channel=channel, headless=bool(os.environ.get("JA_WHATSAPP_OCULTO")), accept_downloads=False)


def open_group(page, name: str) -> None:
    box = page.locator('[contenteditable="true"][role="textbox"], [data-testid="chat-list-search"]').first
    box.click()
    box.fill(name)
    page.wait_for_timeout(1500)
    page.locator(f'span[title="{name}"]').first.click()
    page.wait_for_selector(MESSAGES, timeout=30_000)


def load_history(page) -> None:
    for _ in range(SCROLLS):
        page.evaluate("() => { const item = document.querySelector('div[data-id]'); if (item) item.scrollIntoView(); }")
        page.wait_for_timeout(600)


def save_photos(page, message_id: str, count: int, folder: Path) -> list[str]:
    """Abre a primeira foto e percorre o visualizador para pegar o tamanho real."""
    folder.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    page.locator(f'div[data-id="{message_id}"] {OPEN_IMAGE_JS}').first.click()
    page.wait_for_timeout(VIEWER_WAIT_MS)
    seen: set[str] = set()
    for number in range(count):
        photo = page.evaluate(SAVE_LARGEST_JS)
        if not photo or photo["src"] in seen:
            break
        seen.add(photo["src"])
        path = folder / f"{number + 1:02d}.{'png' if 'png' in photo['type'] else 'jpg'}"
        path.write_bytes(base64.b64decode(photo["data"]))
        saved.append(str(path))
        page.keyboard.press("ArrowRight")
        page.wait_for_timeout(VIEWER_WAIT_MS)
    page.keyboard.press("Escape")
    page.wait_for_timeout(500)
    return saved


def read_group(name: str) -> dict:
    from playwright.sync_api import sync_playwright

    from dodaios.core import property_intake as intake

    new, known, photos = 0, 0, 0
    with sync_playwright() as playwright:
        context = browser(playwright)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(URL)
        try:
            page.wait_for_selector(READY, timeout=60_000)
        except Exception as exc:
            context.close()
            raise SystemExit("WHATSAPP_SEM_LOGIN: rode com --entrar e leia o QR Code.") from exc
        open_group(page, name)
        load_history(page)
        for item in group_messages(page.evaluate(READ_MESSAGES_JS)):
            key = intake.property_key(item["text"])
            stored: list[str] = []
            if item["first_photo"] and not intake.has_photos(key):
                stored = save_photos(page, item["first_photo"], item["photos"], intake.photo_folder(key))
            _key, is_new = intake.receive(item["text"], stored)
            new += is_new
            known += not is_new
            photos += len(stored)
        context.close()
    return {"novos": new, "ja_conhecidos": known, "fotos": photos}


def login() -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        context = browser(playwright)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(URL)
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
