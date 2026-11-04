#!/usr/bin/env python3
"""Agente que cadastra no Kenlo os imoveis lidos do grupo do WhatsApp.

  python ja-kenlo-cadastro.py --entrar           abre o Kenlo para o primeiro login
  python ja-kenlo-cadastro.py --imovel codigo-1  preenche e para antes de salvar
  python ja-kenlo-cadastro.py --proximo          faz o mesmo com o proximo da fila
  python ja-kenlo-cadastro.py --rodar             le o grupo e cadastra em sequencia
  acrescente --salvar para salvar de verdade

Usa o mesmo perfil separado do Chrome do leitor do WhatsApp. O login vem do
Chaves do macOS, onde o dono guardou; nunca fica em arquivo nem no repositorio.
Sem login guardado, o dono entra na janela. Se um campo falhar, nada e salvo.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
ROOT = Path(os.environ.get("JA_WHATSAPP_RAIZ") or Path.home() / ".dodaios")
PROFILE = ROOT / "whatsapp-perfil"
REPORTS = Path(os.environ.get("JA_KENLO_RELATORIOS") or Path.home() / "Downloads")
URL = os.environ.get("JA_KENLO_URL") or ""
LOGIN_HOST = "signin.valuegaia"
KEYCHAIN_ITEM = "ja-kenlo"
YES = re.compile(r"^\s*sim\s*$", re.IGNORECASE)
OWNER_WAIT_MS = 3_000
LOGIN_WAIT_S = 300
REVIEW_WAIT_S = int(os.environ.get("JA_KENLO_ESPERA") or 1800)
FIELD_WAIT_MS = 15_000
UPLOAD_WAIT_S = 60
MAX_ROUNDS = 200

SEARCH_JS = r"""
() => {
  const fold = (text) => (text || '').normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[*:?]/g, '').replace(/\s+/g, ' ').trim().toLowerCase();
  const visible = (node) => { const box = node.getBoundingClientRect(); const style = getComputedStyle(node); return box.width > 0 && box.height > 0 && style.visibility !== 'hidden'; };
  const own = (node) => [...node.childNodes].filter((child) => child.nodeType === 3).map((child) => child.textContent).join(' ');
  const after = (first, second) => !!(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING);
  window.__ja = {
    fold, visible,
    heading(name) {
      const wanted = fold(name);
      return [...document.querySelectorAll('h1,h2,h3,h4,h5,h6,div,span,legend,label,p')].find((node) => fold(own(node)) === wanted && visible(node)) || null;
    },
    label(section, name) {
      const start = this.heading(section);
      const wanted = fold(name);
      const hits = [...document.querySelectorAll('label,span,div,td,th,b,strong,p,a')].filter((node) => fold(own(node) || node.innerText) === wanted && visible(node) && (!start || after(start, node)));
      const best = hits.sort((a, b) => a.querySelectorAll('*').length - b.querySelectorAll('*').length)[0];
      if (best) return best;
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      while (walker.nextNode()) {
        const piece = walker.currentNode;
        if (fold(piece.textContent) === wanted && visible(piece.parentElement) && (!start || after(start, piece))) return piece;
      }
      return null;
    },
    control(section, name, types) {
      const label = this.label(section, name);
      if (!label) return null;
      if (label.htmlFor && document.getElementById(label.htmlFor)) { const direct = document.getElementById(label.htmlFor); if (types.includes(direct.tagName.toLowerCase() + ':' + (direct.type || ''))) return direct; }
      const all = [...document.querySelectorAll('input,select,textarea')];
      const kind = (node) => node.tagName.toLowerCase() + ':' + (node.type || '');
      return all.find((node) => types.includes(kind(node)) && after(label, node) && (node.tagName === 'SELECT' || visible(node))) || null;
    },
    checkbox(section, name) {
      const label = this.label(section, name);
      if (!label) return null;
      const near = (label.closest ? label : label.parentElement).closest('label')?.querySelector('input[type=checkbox]');
      if (near) return near;
      if (label.htmlFor) { const direct = document.getElementById(label.htmlFor); if (direct) return direct; }
      const boxes = [...document.querySelectorAll('input[type=checkbox]')].filter((node) => !after(label, node));
      return boxes[boxes.length - 1] || null;
    },
  };
}
"""
TEXT_TYPES = ["input:text", "input:tel", "input:number", "input:email", "input:search", "input:", "textarea:textarea"]
SET_SELECT_JS = r"""
([node, wanted]) => {
  const fold = window.__ja.fold;
  const options = [...node.options];
  const option = options.find((item) => fold(item.text) === fold(wanted)) || options.find((item) => fold(item.text).startsWith(fold(wanted))) || options.find((item) => fold(item.text).includes(fold(wanted)));
  if (!option) return { ok: false, opcoes: options.map((item) => item.text).slice(0, 30) };
  node.value = option.value;
  node.dispatchEvent(new Event('input', { bubbles: true }));
  node.dispatchEvent(new Event('change', { bubbles: true }));
  if (window.jQuery) window.jQuery(node).trigger('change').trigger('chosen:updated').trigger('liszt:updated');
  return { ok: true, escolhido: option.text };
}
"""
MAP_JS = r"""
() => [...document.querySelectorAll('input,select,textarea,button')].filter((node) => node.type !== 'hidden').map((node) => {
  const near = node.labels?.[0]?.innerText || node.closest('div,td')?.innerText?.slice(0, 40) || '';
  return [node.tagName, node.type || '', node.id || '', node.name || '', window.__ja.visible(node) ? 'visivel' : 'oculto', near.replace(/\s+/g, ' ')].join(' | ');
}).slice(0, 400)
"""


def digits(text: str) -> str:
    return re.sub(r"\D", "", text or "").lstrip("0")


class Form:
    """Preenche o formulario pelos rotulos que aparecem na tela."""

    def __init__(self, page) -> None:
        self.page = page
        self.log: list[str] = []
        self.failed: list[str] = []
        self.known_owner = False

    def _control(self, section: str, field: str, types: list[str], wait_ms: int = FIELD_WAIT_MS):
        limit = time.monotonic() + wait_ms / 1000
        while True:
            self.page.evaluate(SEARCH_JS)
            handle = self.page.evaluate_handle("([s, f, t]) => window.__ja.control(s, f, t)", [section, field, types]).as_element()
            if handle or time.monotonic() > limit:
                return handle
            self.page.wait_for_timeout(300)

    def text(self, section: str, field: str, value: str) -> None:
        box = self._control(section, field, TEXT_TYPES)
        if not box:
            raise LookupError("campo nao encontrado")
        box.click()
        box.press("ControlOrMeta+a")
        box.press("Backspace")
        box.type(value, delay=25)
        box.press("Tab")
        shown = box.input_value()
        if digits(shown) != digits(value) and not (shown.strip() and not digits(value)):
            raise ValueError(f"ficou {shown!r}")

    def phone(self, section: str, field: str, value: str) -> None:
        """Telefone ja cadastrado: o Kenlo oferece o contato e a resposta e Sim."""
        self.text(section, field, value)
        answer = self.page.get_by_role("button", name=YES).or_(self.page.locator("a, .btn").filter(has_text=YES)).first
        try:
            answer.wait_for(state="visible", timeout=OWNER_WAIT_MS)
        except Exception:
            return
        answer.click()
        self.page.wait_for_timeout(1200)
        self.known_owner = True
        self.log.append("OK    Proprietario ja cadastrado: usado o contato existente")

    def name(self, section: str, field: str, value: str) -> None:
        """Nome com lista de sugestoes: digita e fecha a lista sem escolher."""
        if self.known_owner:
            return
        box = self._control(section, field, TEXT_TYPES)
        if not box:
            raise LookupError("campo nao encontrado")
        box.click()
        box.fill(value)
        self.page.wait_for_timeout(800)
        self.page.keyboard.press("Escape")
        box.press("Tab")

    def long_text(self, section: str, field: str, value: str) -> None:
        box = self._control(section, field, ["textarea:textarea"])
        if not box:
            raise LookupError("campo nao encontrado")
        box.fill(value)

    def choose(self, section: str, field: str, value: str) -> None:
        node = self._control(section, field, ["select:select-one"])
        if not node:
            raise LookupError("lista nao encontrada")
        result = self.page.evaluate(SET_SELECT_JS, [node, value])
        if not result["ok"]:
            raise ValueError(f"sem a opcao; existem: {result['opcoes']}")
        self.page.wait_for_timeout(500)

    def tick(self, section: str, field: str) -> None:
        self.page.evaluate(SEARCH_JS)
        box = self.page.evaluate_handle("([s, f]) => window.__ja.checkbox(s, f)", [section, field]).as_element()
        if not box:
            raise LookupError("caixa nao encontrada")
        if not box.is_checked():
            try:
                box.click(timeout=3000)
            except Exception:
                self.page.evaluate_handle("([s, f]) => window.__ja.label(s, f)", [section, field]).as_element().click()
        self.page.wait_for_timeout(250)
        if not box.is_checked():
            raise ValueError("nao ficou marcada")

    def option(self, section: str, field: str, value: str) -> None:
        self.page.evaluate(SEARCH_JS)
        label = self.page.evaluate_handle("([s, f]) => window.__ja.label(s, f)", [section, field])
        if self.page.evaluate("(node) => !node", label):
            raise LookupError("pergunta nao encontrada")
        radio = self.page.evaluate_handle(
            """([label, wanted]) => [...document.querySelectorAll('input[type=radio]')].find((node) =>
                (label.compareDocumentPosition(node) & 4) && window.__ja.fold(node.parentElement.innerText || node.nextSibling?.textContent).startsWith(window.__ja.fold(wanted)))""",
            [label, value]).as_element()
        if not radio:
            raise LookupError("opcao nao encontrada")
        radio.check(force=True)

    def click(self, section: str, field: str) -> None:
        self.page.evaluate(SEARCH_JS)
        target = self.page.evaluate_handle(
            """([s, f]) => window.__ja.label(s, f) || [...document.querySelectorAll('button,a,input[type=button]')].find((node) => window.__ja.fold(node.innerText || node.value) === window.__ja.fold(f) && window.__ja.visible(node))""",
            [section, field]).as_element()
        if not target:
            raise LookupError("botao nao encontrado")
        target.click()
        self.page.wait_for_timeout(1200)

    def street(self, section: str, field: str, value: dict) -> None:
        """Logradouro: abre a busca, digita e escolhe o resultado do bairro certo."""
        self.page.evaluate(SEARCH_JS)
        label = self.page.evaluate_handle("([s, f]) => window.__ja.label(s, f)", [section, field])
        if self.page.evaluate("(node) => !node", label):
            raise LookupError("logradouro nao encontrado")
        opener = self.page.evaluate_handle(
            """(label) => [...document.querySelectorAll('.select2-selection, .select2-choice, .chosen-single, input[type=text], [role=combobox]')].find((node) => (label.compareDocumentPosition(node) & 4) && window.__ja.visible(node))""",
            label).as_element()
        if not opener:
            raise LookupError("busca do logradouro nao encontrada")
        opener.click()
        self.page.wait_for_timeout(400)
        self.page.keyboard.type(value["rua"], delay=20)
        chosen = ""
        limit = time.monotonic() + 12
        while time.monotonic() < limit and not chosen:
            self.page.wait_for_timeout(500)
            chosen = self.page.evaluate(
                """([street, area]) => {
                  const fold = window.__ja.fold;
                  const items = [...document.querySelectorAll('li, [role=option]')].filter((node) => window.__ja.visible(node) && fold(node.innerText).includes(fold(street)));
                  const best = items.find((node) => fold(node.innerText).includes(fold(area))) || null;
                  if (best) { best.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); best.dispatchEvent(new MouseEvent('mouseup', { bubbles: true })); best.click(); return best.innerText; }
                  return '';
                }""", [value["rua"], value["bairro"]])
        if not chosen:
            raise LookupError("rua nao apareceu para este bairro")
        self.page.wait_for_timeout(1500)

    def photos(self, paths: list[str]) -> None:
        """Envia uma por vez: juntas, chegam fora de ordem. A primeira vira capa."""
        for done, path in enumerate(paths):
            box = self.page.locator("input[type=file]").first
            box.set_input_files(path)
            limit = time.monotonic() + UPLOAD_WAIT_S
            while self._tiles() <= done:
                if time.monotonic() > limit:
                    raise TimeoutError(f"foto {Path(path).name} nao terminou de subir")
                self.page.wait_for_timeout(400)
        cover = self.page.get_by_text("Foto de capa", exact=True).first
        tick = cover.locator("xpath=preceding::input[@type='checkbox'][1]")
        if not tick.is_checked():
            tick.click(force=True)
        self.page.wait_for_timeout(300)
        if not tick.is_checked():
            raise ValueError("capa nao ficou marcada")

    def _tiles(self) -> int:
        return self.page.get_by_text("Foto de capa", exact=True).count()

    def run(self, steps: list[dict], photos: list[str]) -> None:
        actions = {"texto": self.text, "telefone": self.phone, "dinheiro": self.text, "nome": self.name, "texto_longo": self.long_text, "lista": self.choose,
                   "logradouro": self.street, "opcao": self.option}
        for step in steps:
            section, field, how = step["secao"], step["campo"], step["como"]
            try:
                if how == "fotos":
                    self.photos(photos)
                elif how == "marcar":
                    self.tick(section, field)
                elif how == "clicar":
                    self.click(section, field)
                else:
                    actions[how](section, field, step["valor"])
                self.log.append(f"OK    {section} > {field}")
            except Exception as exc:
                self.failed.append(field)
                self.log.append(f"FALHOU {section} > {field}: {str(exc).splitlines()[0][:220]}")


def browser(playwright):
    PROFILE.mkdir(parents=True, exist_ok=True)
    channel = os.environ.get("JA_WHATSAPP_CANAL", "chrome") or None
    return playwright.chromium.launch_persistent_context(str(PROFILE), channel=channel, headless=bool(os.environ.get("JA_WHATSAPP_OCULTO")), no_viewport=True)


def saved_login() -> tuple[str, str]:
    """E-mail e senha guardados no Chaves do macOS; vazio se nao houver."""
    try:
        found = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_ITEM], capture_output=True, text=True)
        secret = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_ITEM, "-w"], capture_output=True, text=True)
    except OSError:
        return "", ""
    account = re.search(r'"acct"<blob>="([^"]+)"', found.stdout)
    return (account.group(1), secret.stdout.rstrip("\n")) if account and secret.returncode == 0 else ("", "")


def sign_in(page) -> bool:
    """Tenta uma vez so, para uma senha errada nao bloquear a conta."""
    email, password = saved_login()
    if not password:
        print("LOGIN_AUTOMATICO=sem login guardado", flush=True)
        return False
    try:
        secret = page.locator("input[type=password]").first
        secret.wait_for(state="visible", timeout=20_000)
        secret.locator("xpath=preceding::input[not(@type='hidden')][1]").fill(email)
        secret.fill(password)
        page.get_by_role("button", name=re.compile("^entrar$", re.IGNORECASE)).first.click()
        page.wait_for_url(lambda url: LOGIN_HOST not in url, timeout=45_000)
    except Exception as exc:
        print(f"LOGIN_AUTOMATICO=falhou ({type(exc).__name__})", flush=True)
        return False
    print("LOGIN_AUTOMATICO=OK", flush=True)
    return True


def wait_login(page, target: str) -> None:
    page.goto(target)
    page.wait_for_timeout(2500)
    if LOGIN_HOST not in page.url:
        return
    if sign_in(page):
        page.wait_for_timeout(2000)
        page.goto(target)
        return
    print("Entre no Kenlo nessa janela. Aguardando ate 5 minutos...", flush=True)
    limit = time.monotonic() + LOGIN_WAIT_S
    while LOGIN_HOST in page.url:
        if time.monotonic() > limit:
            raise SystemExit("KENLO_SEM_LOGIN: entre no Kenlo e tente de novo.")
        page.wait_for_timeout(1000)
    page.wait_for_timeout(2000)
    page.goto(target)


def prepare(item: dict, rules: dict) -> tuple[dict, list[str]]:
    """Ficha, sequencia de fotos, anuncio e plano do imovel."""
    from dodaios.core import cadastro_plan as plan, photo_order as order, photo_vision as vision
    from dodaios.core.property_sheet import parse_sheet

    sheet = parse_sheet(item["texto"])
    kind = order.sequence_kind(item["tipo"], item["condominio"])
    paths = [Path(path) for path in item.get("fotos", []) if Path(path).exists()]
    notes: list[str] = []
    final = item.get("ordem_fotos") or []
    if not final:
        arranged = order.arrange(kind, vision.classify_all(paths, kind, rules["empresa"]), int(sheet["suites"] or 0))
        final = [photo["caminho"] for photo in arranged["ordem"]]
        notes = arranged["avisos"] + arranged["duvidas"]
        notes += [f"Repetida fora do anuncio: {Path(photo['caminho']).name}" for photo in arranged["repetidas"]]
        notes += [f"{Path(photo['caminho']).name}: {photo['ambiente']} ({photo['fonte']})" for photo in arranged["ordem"]]
    text = plan.clean_ad(vision.write_ad(plan.ad_prompt(item, sheet)), sheet) or plan.template_ad(item, sheet, rules["nome_empresa"])
    built = plan.build_plan(item, sheet, rules, text)
    built["conferir"] += notes + vision.problems
    built["ficha"] = sheet
    if not final:
        built["faltando"].append("fotos")
    return built, final


def report(key: str, form: Form | None, built: dict, field_map: list[str], result: str) -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)
    path = REPORTS / f"kenlo-cadastro-{key}.txt"
    lines = [f"Cadastro Kenlo {key} em {datetime.now():%d/%m/%Y %H:%M}", f"Resultado: {result}", "",
             "Ficha lida: " + json.dumps({name: value for name, value in built["ficha"].items() if value}, ensure_ascii=False), "",
             "Falta na ficha: " + (", ".join(built["faltando"]) or "nada"), "", "Conferir:", *[f"- {note}" for note in built["conferir"]], "",
             "Campos:", *(form.log if form else []), "", "Mapa do formulario (sem valores):", *field_map]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def fill(page, key: str, save: bool) -> bool:
    """Cadastra um imovel na aba do Kenlo; devolve se tudo correu bem."""
    from dodaios.core import cadastro_plan as plan, property_intake as intake

    rules = plan.load_rules()
    item = intake.get(key)
    if not item:
        print(f"KENLO_RESULTADO=SEM_IMOVEL {key}", flush=True)
        return False
    built, photos = prepare(item, rules)
    if built["faltando"]:
        intake.mark(key, intake.REVIEW, "Falta na ficha: " + ", ".join(built["faltando"]))
        print(f"KENLO_RESULTADO=FALTANDO {key} {report(key, None, built, [], 'parado antes de preencher')}", flush=True)
        return False
    if save and key in rules.get("ja_cadastrados", {}):
        print(f"KENLO_RESULTADO=JA_CADASTRADO {rules['ja_cadastrados'][key]}", flush=True)
        return False
    if save and item["tipo"] not in rules["ensinado"]:
        intake.mark(key, intake.REVIEW, f"Tipo ainda nao ensinado: {item['tipo']}")
        print(f"KENLO_RESULTADO=TIPO_NAO_ENSINADO {key} {item['tipo']}", flush=True)
        return False
    page.bring_to_front()
    page.goto("about:blank")
    wait_login(page, URL or plan.NEW_PROPERTY_URL)
    form = Form(page)
    page.wait_for_timeout(2500)
    form.run(built["passos"], photos)
    page.evaluate(SEARCH_JS)
    field_map = page.evaluate(MAP_JS)
    if form.failed:
        intake.mark(key, intake.REVIEW, "Falhou em: " + ", ".join(form.failed))
        print(f"KENLO_RESULTADO=FALHOU {key} {report(key, form, built, field_map, 'campos com falha: nada foi salvo')}", flush=True)
        wait_closed(page)
        return False
    if not save:
        print(f"KENLO_RESULTADO=PREENCHIDO {key} {report(key, form, built, field_map, 'preenchido, parado antes de salvar')}", flush=True)
        intake.mark(key, intake.PENDING, "")
        wait_closed(page)
        return True
    page.get_by_role("button", name=re.compile("^salvar$", re.IGNORECASE)).first.click()
    page.wait_for_selector("text=/refer[eê]ncia/i", timeout=60_000)
    found = re.search(r"refer[eê]ncia\s+([A-Z]{1,3}\d+)", page.content(), re.IGNORECASE)
    reference = found.group(1) if found else ""
    page.get_by_role("button", name=YES).first.click()
    page.wait_for_timeout(1500)
    intake.mark(key, intake.DONE, f"Cadastrado no Kenlo: {reference}")
    print(f"KENLO_RESULTADO=SALVO {key} {reference} {report(key, form, built, field_map, f'salvo com a referencia {reference}')}", flush=True)
    return True


def register(key: str, save: bool) -> int:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        context = browser(playwright)
        page = context.pages[0] if context.pages else context.new_page()
        done = fill(page, key, save)
        close(context)
    return 0 if done else 1


def close(context) -> None:
    try:
        context.close()
    except Exception:
        return


def reader():
    """Carrega o leitor do WhatsApp, que divide a mesma janela."""
    from importlib import util

    spec = util.spec_from_file_location("ja_whatsapp", Path(__file__).with_name("ja-whatsapp-imoveis.py"))
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_all(group: str, save: bool, fallback: str) -> int:
    """Uma janela, duas abas: cadastra em sequencia ate o grupo nao ter novos."""
    from playwright.sync_api import sync_playwright

    whatsapp = reader()
    with sync_playwright() as playwright:
        context = browser(playwright)
        chat = context.pages[0] if context.pages else context.new_page()
        kenlo = context.new_page()
        whatsapp.open_chat(chat, group)
        handled: set[str] = set()
        count = 0
        for _ in range(MAX_ROUNDS):
            chat.bring_to_front()
            print("WHATSAPP_LIDO=" + json.dumps(whatsapp.scan(chat), ensure_ascii=False), flush=True)
            key = next_key()
            if not key or key in handled:
                break
            while key and key not in handled:
                handled.add(key)
                count += fill(kenlo, key, save)
                if not save or kenlo.is_closed():
                    print(f"CADASTROS_FEITOS={count}", flush=True)
                    close(context)
                    return 0
                key = next_key()
        print(f"CADASTROS_FEITOS={count}", flush=True)
        if not handled:
            print("KENLO_RESULTADO=FILA_VAZIA", flush=True)
            if fallback and not save:
                fill(kenlo, fallback, False)
        close(context)
    return 0


def wait_closed(page) -> None:
    """Deixa a tela aberta para o dono conferir, ate ele fechar a janela."""
    print("Confira o formulario. Feche a janela quando terminar.", flush=True)
    limit = time.monotonic() + REVIEW_WAIT_S
    while time.monotonic() < limit and not page.is_closed():
        try:
            page.wait_for_timeout(1000)
        except Exception:
            return


def next_key() -> str:
    from dodaios.core import cadastro_plan as plan, property_intake as intake

    done = plan.load_rules().get("ja_cadastrados", {})
    for _ in range(1000):
        item = intake.next_pending()
        if not item:
            return ""
        if item["chave"] not in done:
            return item["chave"]
        intake.mark(item["chave"], intake.DONE, f"Ja cadastrado: {done[item['chave']]}")
    return ""


def login() -> None:
    from playwright.sync_api import sync_playwright

    from dodaios.core import cadastro_plan as plan

    with sync_playwright() as playwright:
        context = browser(playwright)
        page = context.pages[0] if context.pages else context.new_page()
        wait_login(page, URL or plan.NEW_PROPERTY_URL)
        context.close()
    print("KENLO_LOGIN=OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--entrar", action="store_true")
    parser.add_argument("--imovel", default="")
    parser.add_argument("--proximo", action="store_true")
    parser.add_argument("--salvar", action="store_true")
    parser.add_argument("--rodar", action="store_true")
    parser.add_argument("--grupo", default="Agenciamentos")
    parser.add_argument("--se-vazio", default="")
    args = parser.parse_args()
    if args.entrar:
        login()
        return 0
    if args.rodar:
        return run_all(args.grupo.strip(), args.salvar, args.se_vazio.strip())
    key = args.imovel.strip() or (next_key() if args.proximo else "")
    if not key:
        print("KENLO_RESULTADO=FILA_VAZIA")
        return 0
    return register(key, args.salvar)


if __name__ == "__main__":
    sys.exit(main())
