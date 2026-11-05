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
import importlib.util
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
SELECT_WAIT_S = 30
SAVE_WAIT_MS = 60_000
ALONE_WAIT_MS = 5_000
VISION_TRIES = 6
LOAD_TIMEOUT_MS = int(os.environ.get("JA_KENLO_CARGA_MS") or 30_000)
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
SELECT_STATE_JS = r"""
([node, wanted]) => {
  const fold = window.__ja.fold;
  const texts = [...node.options].map((item) => fold(item.text));
  const chosen = node.selectedOptions[0] ? fold(node.selectedOptions[0].text) : '';
  const target = fold(wanted);
  return { travado: node.disabled, pronto: texts.some((text) => text === target || text.startsWith(target)), certo: chosen === target || chosen.startsWith(target) };
}
"""
SAVE_WARNING_JS = r"""
() => {
  const shown = [...document.querySelectorAll('.modal, .alert, .swal2-popup, .toast, .error, .erro, .has-error, .help-block, [role=alert], [class*=erro], [class*=invalid]')]
    .filter((node) => node.getClientRects().length).map((node) => (node.innerText || '').replace(/\s+/g, ' ').trim()).filter(Boolean).slice(0, 6);
  const focused = document.activeElement;
  const box = focused && focused.closest('div, td, li');
  const label = box && box.querySelector('label');
  if (label) shown.push(`campo em destaque: ${label.innerText.trim()}`);
  return shown.join(' | ').slice(0, 400);
}
"""
SAVE_JS = r"""
() => [...document.querySelectorAll('input[type=button], input[type=submit], button')]
  .filter((node) => node.getClientRects().length && /^\s*salvar\s*$/i.test(node.innerText || node.value || '')).pop() || null
"""
MAP_JS = r"""
() => [...document.querySelectorAll('input,select,textarea,button')].filter((node) => node.type !== 'hidden').map((node) => {
  const near = node.labels?.[0]?.innerText || node.closest('div,td')?.innerText?.slice(0, 40) || '';
  return [node.tagName, node.type || '', node.id || '', node.name || '', window.__ja.visible(node) ? 'visivel' : 'oculto', near.replace(/\s+/g, ' ')].join(' | ');
}).slice(0, 400)
"""


ANSWER_WAIT_S = float(os.environ.get("JA_ESPERA_RESPOSTA") or 600)
CONFIRM_WAIT_S = min(ANSWER_WAIT_S, 90)
MAX_QUESTIONS = 3
FIELD_TIMEOUT_MS = 4000
NAVIGATION_TIMEOUT_MS = 45_000
EMPTY_TRIES = 3
EMPTY_WAIT_S = min(ANSWER_WAIT_S, 180)
POPUP_JS = r"""
() => {
  const open = [...document.querySelectorAll('[role=dialog], .modal, .swal2-popup, .ui-dialog')].find((node) => {
    const box = node.getBoundingClientRect();
    return box.width > 80 && box.height > 40 && getComputedStyle(node).visibility !== 'hidden' && getComputedStyle(node).display !== 'none';
  });
  return open ? open.innerText.replace(/\s+/g, ' ').slice(0, 160) : '';
}
"""
RECORD_JS = r"""
() => {
  if (window.__jaClicks) return;
  window.__jaClicks = [];
  document.addEventListener('click', (event) => {
    const node = event.target.closest('button, a, [role=button], label, li, input, select') || event.target;
    if (node.type === 'password') return;
    const typed = node.matches('input, select, textarea') && !/button|submit|checkbox|radio/.test(node.type);
    const text = (node.innerText || node.value || node.getAttribute('aria-label') || node.title || '').trim().slice(0, 60);
    window.__jaClicks.push({ texto: typed ? '' : text });
  }, true);
}
"""
CONDO_JS = r"""
([name, street, area, city]) => {
  const fold = window.__ja.fold;
  const shown = [...document.querySelectorAll('li, [role=option], .select2-result, .tt-suggestion')].filter((node) => window.__ja.visible(node) && fold(node.innerText).includes(fold(name)));
  const items = shown.filter((node) => !shown.some((other) => other !== node && node.contains(other)));
  const road = fold(street).replace(/^(rua|avenida|av\.?)\s+/, '');
  const has = (node, text) => text && fold(node.innerText).includes(fold(text));
  const best = items.find((node) => road && fold(node.innerText).includes(road)) || items.find((node) => has(node, area) && has(node, city)) || items.find((node) => has(node, city));
  if (!best) return '';
  best.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
  best.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
  best.click();
  return best.innerText;
}
"""


def plain_problem(exc: Exception) -> str:
    text = str(exc).splitlines()[0][:120]
    return "o campo não respondeu" if "Timeout" in text else text


def digits(text: str) -> str:
    return re.sub(r"\D", "", text or "").lstrip("0")


class Form:
    """Preenche o formulario pelos rotulos que aparecem na tela."""

    def __init__(self, page, company: str = "", kind: str = "") -> None:
        self.page = page
        page.set_default_timeout(FIELD_TIMEOUT_MS)
        page.set_default_navigation_timeout(NAVIGATION_TIMEOUT_MS)
        self.log: list[str] = []
        self.failed: list[str] = []
        self.known_owner = False
        self.condo_found = False
        self.stopped = False
        self.company = company
        self.kind = kind

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
        """Finalidade e Tipo ficam travados ate carregar: espera e confere o que ficou."""
        limit = time.monotonic() + SELECT_WAIT_S
        while True:
            node = self._control(section, field, ["select:select-one"])
            if not node:
                raise LookupError("lista nao encontrada")
            state = self.page.evaluate(SELECT_STATE_JS, [node, value])
            if not state["travado"] and state["pronto"]:
                result = self.page.evaluate(SET_SELECT_JS, [node, value])
                if not result["ok"]:
                    raise ValueError(f"sem a opcao; existem: {result['opcoes']}")
                self.page.wait_for_timeout(700)
                node = self._control(section, field, ["select:select-one"])
                if node and self.page.evaluate(SELECT_STATE_JS, [node, value])["certo"]:
                    return
            if time.monotonic() > limit:
                raise ValueError(f"lista travada ou sem a opcao {value}")
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
        # "Buscar por" tambem mostra a palavra Logradouro; o aviso do campo e unico.
        self.page.keyboard.press("Escape")
        opener = self.page.get_by_text(re.compile("digite um logradouro", re.IGNORECASE)).first
        opener.wait_for(state="visible", timeout=FIELD_TIMEOUT_MS)
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
                  const best = items.find((node) => fold(node.innerText).includes(fold(area))) || (items.length === 1 ? items[0] : null);
                  if (best) { best.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); best.dispatchEvent(new MouseEvent('mouseup', { bubbles: true })); best.click(); return best.innerText; }
                  return '';
                }""", [value["rua"], value["bairro"]])
        if not chosen:
            raise LookupError("rua nao apareceu para este bairro")
        self.page.wait_for_timeout(1500)

    def condo(self, section: str, field: str, value: dict) -> None:
        """Escolhe o condominio pelo endereco; sem achar, segue pelo endereco normal."""
        self.page.wait_for_timeout(1200)  # o campo so aparece depois do Tipo
        self.page.evaluate(SEARCH_JS)
        label = self.page.evaluate_handle("([s, f]) => window.__ja.label(s, f)", [section, field])
        opener = None if self.page.evaluate("(node) => !node", label) else self.page.evaluate_handle(
            """(label) => [...document.querySelectorAll('.select2-selection, .select2-choice, .chosen-single, [role=combobox], [class*=select], select, input[type=text]')].find((node) => (label.compareDocumentPosition(node) & 4) && window.__ja.visible(node)) || null""",
            label).as_element()
        if not opener:
            self.log.append("AVISO condominio: campo nao apareceu; seguindo pelo endereco")
            return
        opener.click()
        self.page.wait_for_timeout(500)
        self.page.keyboard.type(value["busca"], delay=20)
        chosen = ""
        limit = time.monotonic() + 8
        while time.monotonic() < limit and not chosen:
            self.page.wait_for_timeout(500)
            chosen = self.page.evaluate(CONDO_JS, [value["busca"], value["rua"], value["bairro"], value["cidade"]])
        if not chosen:
            self.page.keyboard.press("Escape")
            self.log.append(f"AVISO condominio: {value['busca']} nao encontrado neste endereco; seguindo pelo endereco")
            return
        self.page.wait_for_timeout(1500)
        skip = self.page.get_by_text(re.compile(r"encontrou o tipo", re.IGNORECASE)).first
        try:
            skip.wait_for(state="visible", timeout=5000)
            skip.click()
            self.page.wait_for_timeout(1200)
        except Exception:
            pass
        self.condo_found = True

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

    def _do(self, step: dict, photos: list[str]) -> None:
        actions = {"texto": self.text, "telefone": self.phone, "dinheiro": self.text, "nome": self.name, "texto_longo": self.long_text, "lista": self.choose,
                   "logradouro": self.street, "opcao": self.option, "condominio": self.condo}
        section, field, how = step["secao"], step["campo"], step["como"]
        if how == "fotos":
            self.photos(photos)
        elif how == "perguntar_piso":
            self.ask_floor(section, step["valor"])
        elif how == "marcar":
            self.tick(section, field)
        elif how == "clicar":
            self.click(section, field)
        else:
            actions[how](section, field, step["valor"])

    def ask_floor(self, section: str, floors: list[str]) -> None:
        """Sem ver o piso nas fotos, pergunta qual e em vez de chutar."""
        from dodaios.core import agent_questions as questions

        decision = self._ask("não consegui identificar o piso pelas fotos. Qual é o piso? Escreva, por exemplo: porcelanato.", [questions.SHOW, "Pular este campo"])
        if decision["acao"] == "mostrar":
            demonstrate(self.page, "pode marcar o piso na janela do agente. Quando terminar, clique em Pronto.")
            return
        plain = decision["texto"].lower()
        chosen = [name for name in floors if name.lower() in plain]
        for name in chosen:
            self.tick(section, name)
        if not chosen and decision["acao"] != "pular":
            raise LookupError("piso nao informado")

    def _ask(self, text: str, options: list[str], seconds: float = ANSWER_WAIT_S) -> dict:
        """Fala com o dono, mostra a tela e espera; volta acao vazia sem resposta."""
        from dodaios.core import agent_questions as questions

        try:
            self.page.screenshot(path=str(questions.image_path()))
            shown = True
        except Exception:
            shown = False
        reply = questions.ask_owner(text, options, seconds, shown)
        self.log.append(f"PERGUNTA {text[:120]} -> {reply[:80] or 'sem resposta'}")
        return {**questions.interpret(reply), "respondeu": bool(reply), "texto": reply}

    def _apply(self, step: dict, decision: dict, photos: list[str]) -> None:
        if decision["acao"] == "passos":
            for click in json.loads(decision["valor"]):
                self.page.get_by_text(click["texto"], exact=False).first.click(timeout=5000)
                self.page.wait_for_timeout(800)
        elif decision["acao"] == "clicar":
            self.page.get_by_text(decision["valor"], exact=False).first.click(timeout=5000)
            self.page.wait_for_timeout(1000)
        elif decision["acao"] == "valor":
            step = {**step, "valor": decision["valor"]}
        if decision["acao"] != "pular":
            self._do(step, photos)

    def _try_alone(self, step: dict, problem: str, photos: list[str]) -> bool:
        """Antes de perguntar, olha a tela e tenta uma vez o que parecer resolver."""
        from dodaios.core import agent_questions as questions, company_lessons as lessons, photo_vision as vision

        field = step["campo"]
        try:
            taught = lessons.guidance(lessons.for_agent(self.company), self.kind, field, problem)
            self.log += [f"ENSINAMENTO USADO {field}: {taught[:120]}"] if taught else []
            hint = vision.screen_help(self.page.screenshot(type="jpeg", quality=70), field.strip("*:"), f"{problem}. Orientação do dono: {taught}" if taught else problem)
            if hint["acao"] == "esperar":
                self.page.wait_for_timeout(ALONE_WAIT_MS)
            elif hint["acao"] == "clicar" and hint["texto"] and not questions.forbidden_click(hint["texto"]):
                self.page.get_by_text(hint["texto"], exact=False).locator("visible=true").first.click(timeout=3000)
                self.page.wait_for_timeout(1200)
            else:
                return False
            self._do(step, photos)
            self.log.append(f"RESOLVEU SOZINHO {field}: {hint['acao']} {hint['texto'][:40]}")
            return True
        except Exception as exc:
            self.log.append(f"TENTOU SOZINHO {field}: {plain_problem(exc)}")
            return False

    def _resolve(self, step: dict, problem: str, photos: list[str]) -> bool:
        """Pergunta ao dono como seguir; o que ele confirmar vale para as proximas."""
        from dodaios.core import agent_questions as questions

        field = step["campo"]
        key = f"{self.company}|{step['secao']}|{field}|{problem[:40]}"
        known = questions.learned(key)
        if known:
            try:
                self._apply(step, known, photos)
                self.log.append(f"APRENDIDO {field}: {known['acao']}")
                return True
            except Exception:
                pass
        if self._try_alone(step, problem, photos):
            return True
        popup = self.page.evaluate(POPUP_JS)
        text = f"estou com um problema no campo {field.strip('*:')}. {problem}.{f' Apareceu na tela: {popup}.' if popup else ''} O que eu devo fazer?"
        for _ in range(MAX_QUESTIONS):
            decision = self._ask(text, [questions.SHOW, "Pular este campo", "Parar"])
            if not decision["acao"] and decision["texto"] and decision["texto"] != questions.RUN:
                value = step["valor"]
                decision = {**decision, **questions.understand(decision["texto"], f"campo {field}, valor da ficha: {value}, problema: {problem}")}
            action = decision["acao"]
            if action == "mostrar":
                clicks = demonstrate(self.page, "pode mostrar na janela do agente. Quando terminar, clique em Pronto.")
                self.page.wait_for_timeout(800)
                try:
                    self._do(step, photos)
                except Exception:
                    self.log.append(f"MOSTROU {field}: o dono fez direto na janela")
                if clicks and self._ask("anotei o que você fez. Salvo para fazer sempre assim?", ["Sim", "Não"], CONFIRM_WAIT_S)["acao"] == "sim":
                    questions.learn(key, {"acao": "passos", "valor": json.dumps(clicks, ensure_ascii=False)})
                    self.log.append(f"APRENDEU {field}: {len(clicks)} cliques")
                return True
            if not decision["respondeu"] or action == "parar":
                self.stopped = True
                return False
            if action == "clicar" and questions.forbidden_click(decision["valor"]):
                text = f"não posso clicar em {decision['valor']} por resposta. Diga outra coisa ou parar."
                continue
            if action not in ("tentar", "pular", "clicar", "valor"):
                text = "não entendi. Diga tentar de novo, pular, parar, clique em tal botão, ou coloque tal valor."
                continue
            try:
                self._apply(step, decision, photos)
            except Exception as exc:
                text = f"ainda não funcionou: {plain_problem(exc)}. O que eu devo fazer?"
                continue
            if action in questions.LEARNABLE:
                what = {"pular": "pular este campo", "clicar": f"clicar em {decision['valor']}", "valor": f"usar {decision['valor']}"}[action]
                keep = self._ask(f"funcionou. Salvo para fazer sempre assim: {what}?", ["Sim", "Não"], CONFIRM_WAIT_S)
                if keep["acao"] == "sim":
                    questions.learn(key, {"acao": action, "valor": decision["valor"]})
                    self.log.append(f"APRENDEU {field}: {what}")
            return True
        return False

    def run(self, steps: list[dict], photos: list[str]) -> None:
        for step in steps:
            section, field = step["secao"], step["campo"]
            if step.get("sem_condominio") and self.condo_found:
                self.log.append(f"PULADO {section} > {field}: veio do condominio")
                continue
            if self.stopped:
                self.failed.append(field)
                continue
            try:
                self._do(step, photos)
                self.log.append(f"OK    {section} > {field}")
            except Exception as exc:
                problem = plain_problem(exc)
                if step.get("opcional"):
                    self.log.append(f"PULADO {section} > {field}: nao existe neste tipo")
                elif self._resolve(step, problem, photos):
                    self.log.append(f"OK    {section} > {field} (com ajuda)")
                else:
                    self.failed.append(field)
                    self.log.append(f"FALHOU {section} > {field}: {problem}")


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
    return fill_screen(playwright.chromium.launch_persistent_context(str(PROFILE), channel=channel, headless=bool(os.environ.get("JA_WHATSAPP_OCULTO")), no_viewport=True))


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


def open_url(page, url: str | None = None) -> None:
    """O Kenlo pode nunca terminar de carregar tudo: quem confere a tela e quem chamou."""
    try:
        if url:
            page.goto(url, wait_until="domcontentloaded", timeout=LOAD_TIMEOUT_MS)
        else:
            page.reload(wait_until="domcontentloaded", timeout=LOAD_TIMEOUT_MS)
    except Exception as exc:
        if "timeout" not in str(exc).lower():
            raise
        print(f"AVISO=pagina ainda carregando: {page.url.split('?')[0]}", flush=True)


def wait_login(page, target: str) -> None:
    open_url(page, target)
    page.wait_for_timeout(2500)
    if LOGIN_HOST not in page.url:
        return
    if sign_in(page):
        page.wait_for_timeout(2000)
        open_url(page, target)
        return
    print("Entre no Kenlo nessa janela. Aguardando ate 5 minutos...", flush=True)
    limit = time.monotonic() + LOGIN_WAIT_S
    while LOGIN_HOST in page.url:
        if time.monotonic() > limit:
            raise SystemExit("KENLO_SEM_LOGIN: entre no Kenlo e tente de novo.")
        page.wait_for_timeout(1000)
    page.wait_for_timeout(2000)
    open_url(page, target)


def ask_counts(item: dict, sheet: dict, notes: list[str]) -> dict:
    """Nem ficha nem fotos: pergunta ao dono antes de preencher."""
    from dodaios.core import agent_questions as questions, cadastro_plan as plan

    filled = {**sheet}
    for field, name in plan.missing_counts(item, sheet):
        reply = questions.ask_owner(f"não achei na ficha nem nas fotos: quantos {name} tem o {item['chave']}? Escreva o número.", [])
        number = re.search(r"\d+", reply or "")
        if number:
            filled[field] = number.group(0)
        else:
            notes.append(f"{name.capitalize()}: sem resposta. Confira.")
    return filled


def prepare(item: dict, rules: dict) -> tuple[dict, list[str]]:
    """Ficha, sequencia de fotos, anuncio e plano do imovel."""
    from dodaios.core import company_lessons as lessons, kenlo_study as study
    from dodaios.core import cadastro_plan as plan, photo_order as order, photo_vision as vision, property_intake as intake
    from dodaios.core.property_sheet import parse_sheet

    sheet = plan.complete_sheet(item, parse_sheet(item["texto"]), rules)
    kind = order.sequence_kind(item["tipo"], item["condominio"])
    paths = [Path(path) for path in item.get("fotos", []) if Path(path).exists()]
    notes: list[str] = []
    doubts: list[str] = []
    final = item.get("ordem_fotos") or []
    if not final:
        arranged = order.arrange(kind, vision.classify_all(paths, kind, rules["empresa"]), int(sheet["suites"] or 0))
        final = [photo["caminho"] for photo in arranged["ordem"]]
        doubts = arranged["duvidas"]
        notes = arranged["avisos"] + doubts
        notes += [f"Falta foto no anuncio: {name}" for name in arranged["faltando"]]
        notes += [f"Repetida fora do anuncio: {Path(photo['caminho']).name}" for photo in arranged["repetidas"]]
        notes += [f"{Path(photo['caminho']).name}: {photo['ambiente']} ({photo['fonte']})" for photo in arranged["ordem"]]
        intake.update(item["chave"], analise_fotos={"fotos": len(final), "duvidas": doubts, "avisos": arranged["avisos"], "repetidas": len(arranged["repetidas"]), "faltando": arranged["faltando"], "problemas": vision.problems[-3:]})
    details = vision.detect_details([Path(path) for path in final])
    similar = study.suggest(item.get("tipo", ""), plan.KIND_LABELS.get(item.get("tipo", ""), ("", ""))[0] if item.get("finalidade") != "residencial" else "Residencial", sheet.get("bairro", ""), sheet.get("condominio_nome", ""), order.VISIBLE_ITEMS)
    if similar["fonte"]:
        notes.append(f"Consultei {similar['fonte']}: {', '.join(similar['campos']) or 'sem campo a sugerir'}. Confira.")
    sheet = plan.fill_counts({**sheet, "sugestoes": similar, "itens_condominio": similar["marcados"], "pisos_fotos": details["piso"], "itens_fotos": details["itens"], "itens_ficha": plan.written_items(item, sheet)}, details, notes, item.get("tipo", ""))
    sheet = plan.apply_room_rules(item.get("tipo", ""), ask_counts(item, sheet, notes), notes)
    if sheet.get("condominio_nome") and not sheet.get("condominio_valor"):
        fee = study.condominium_fee(sheet["condominio_nome"], sheet.get("dormitorios"))
        if fee["valor"]:
            sheet = {**sheet, "condominio_valor": fee["valor"]}
            notes.append(f"Condomínio R$ {fee['valor']}, de {fee['imoveis']} imóveis lidos com {sheet.get('dormitorios')} dormitórios. Confira.")
    text = plan.clean_ad(vision.write_ad(plan.ad_prompt(item, sheet, rules)), sheet) or plan.template_ad(item, sheet, rules["nome_empresa"], rules)
    built = plan.build_plan(item, sheet, rules, text)
    built["conferir"] += notes + vision.problems
    built["passos"], taught = lessons.apply(lessons.for_agent(rules["empresa"]), item.get("tipo", ""), built["passos"])
    built["conferir"] += taught
    built["ficha"] = sheet
    built["divergencias"] = plan.compare_with_photos(sheet, details)
    if not details.get("contagens") and not details["itens"]:
        built["conferir"].append("Fotos nao conferidas com a ficha: modelo de imagens sem resposta.")
    built["duvidas_fotos"] = doubts
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


def vision_ready(key: str) -> tuple[bool, bool]:
    """Sem o modelo nao ha fotos em ordem, itens nem descricao: o dono decide antes."""
    from dodaios.core import agent_questions as questions, photo_vision as vision

    for _ in range(VISION_TRIES):
        if vision.model_ready():
            return True, True
        reply = questions.ask_owner(f"o modelo de imagens não está respondendo, então não consigo ordenar as fotos, ver os itens nem refazer a descrição do {key}. Ligue o computador da Maria e clique em Tentar de novo.",
                                    ["Tentar de novo", "Seguir sem fotos", "Parar"])
        action = questions.interpret(reply)["acao"]
        if not reply or action in ("parar", "nao"):
            return False, False
        if action == "pular":
            return True, False
    return False, False


def owner_accepts(key: str, differences: list[str]) -> bool:
    """Ficha e fotos discordam: o dono decide antes de preencher."""
    from dodaios.core import agent_questions as questions

    reply = questions.ask_owner(f"conferi o {key} e achei diferença: {'; '.join(differences)}. Sigo com o que está na ficha?", ["Seguir com a ficha", "Parar"])
    return bool(reply) and questions.interpret(reply)["acao"] not in ("parar", "nao")


def final_record(page, item: dict) -> dict | None:
    """Acha no Kenlo o cadastro finalizado, pela rua e pelo numero, e le sem alterar."""
    from dodaios.core.property_sheet import parse_sheet

    spec = importlib.util.spec_from_file_location("ja_kenlo_leitura", Path(__file__).resolve().parent / "ja-kenlo-leitura.py")
    reading = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reading)
    sheet = parse_sheet(item.get("texto", ""))
    if not sheet["logradouro"] or not sheet["numero"]:
        return None
    reading.open_list(page, sys.modules[__name__])
    frame = reading.list_frame(page)
    frame.get_by_text(re.compile("limpar filtros", re.IGNORECASE)).locator("visible=true").first.click(timeout=5000)
    page.wait_for_timeout(800)
    frame.get_by_placeholder(re.compile("Jos[eé] de Souza", re.IGNORECASE)).fill(re.sub(r"^\w+\.?\s+", "", sheet["logradouro"]))
    with page.expect_response(reading.is_list_answer, timeout=reading.RESPONSE_TIMEOUT_MS) as waited:
        reading.search_button(page).click()
    hits = waited.value.json().get("hits", [])
    found = next((hit for hit in hits if str(hit.get("location_street_number", "")).strip() == sheet["numero"]), None)
    return reading.read_one(page, found) if found else None


def learn_from_finished(page) -> None:
    """Compara os cadastros finalizados e pergunta antes de mudar qualquer regra."""
    from dodaios.core import agent_questions as questions, cadastro_plan as plan, kenlo_learning as learning, property_intake as intake

    rules = plan.load_rules()
    for item in learning.waiting(intake.all_items(), int(rules.get("codigo_inicial", 0)), intake.code_of):
        key = item["chave"]
        try:
            final = final_record(page, item)
        except Exception as exc:
            print(f"AVISO=comparacao de {key}: {str(exc).splitlines()[0][:120]}", flush=True)
            final = None
        if not final:
            intake.update(key, tentativas=int(item.get("tentativas", 0)) + 1)
            continue
        changes = learning.differences(item["preenchido"], rules, final["campos"])
        print(f"APRENDIZADO={key} diferencas={len(changes)}", flush=True)
        for change in changes:
            name = change["campo"].strip("*: ")
            reply = questions.ask_owner(f"no {key} eu coloquei {change['agente']} em {name} e no Kenlo está {change['kenlo']}. Faço sempre assim em {item.get('tipo', 'imóvel')}?", ["Sim, sempre", "Só neste imóvel"])
            if learning.answer_is_yes(reply):
                rules = learning.remember(plan.load_rules(), item.get("tipo", ""), change["campo"], change["kenlo"])
                plan.rules_path().write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")
        intake.update(key, comparado=True)


def fill(page, key: str, save: bool) -> bool:
    """Cadastra um imovel na aba do Kenlo; devolve se tudo correu bem."""
    from dodaios.core import agent_questions as questions, cadastro_plan as plan, kenlo_learning as learning, property_intake as intake

    rules = plan.load_rules()
    item = intake.get(key)
    if not item:
        print(f"KENLO_RESULTADO=SEM_IMOVEL {key}", flush=True)
        return False
    go_on, vision_on = vision_ready(key)
    if not go_on:
        intake.mark(key, intake.REVIEW, "Modelo de imagens desligado")
        print(f"KENLO_RESULTADO=SEM_MODELO {key}", flush=True)
        return False
    save = save and vision_on  # sem conferir as fotos, nunca publica
    built, photos = prepare(item, rules)
    if built["faltando"]:
        intake.mark(key, intake.REVIEW, "Falta na ficha: " + ", ".join(built["faltando"]))
        questions.ask_owner(f"parei o {key}: falta {', '.join(built['faltando'])} na ficha. Corrija a ficha e peça de novo.", ["Entendi"])
        print(f"KENLO_RESULTADO=FALTANDO {key} {report(key, None, built, [], 'parado antes de preencher')}", flush=True)
        return False
    if built["divergencias"] and not owner_accepts(key, built["divergencias"]):
        intake.mark(key, intake.REVIEW, "Ficha diferente das fotos: " + "; ".join(built["divergencias"]))
        print(f"KENLO_RESULTADO=DIVERGENCIA {key} {report(key, None, built, [], 'parado: ficha diferente das fotos')}", flush=True)
        return False
    if save and built["duvidas_fotos"] and not owner_accepts(key, [f"fotos em dúvida: {', '.join(built['duvidas_fotos'])}"]):
        # O Especialista em Fotos so libera o imovel com a ordem certa.
        intake.mark(key, intake.REVIEW, f"Fotos em duvida: {len(built['duvidas_fotos'])}. Confira a ordem.")
        print(f"KENLO_RESULTADO=FOTOS_EM_DUVIDA {key} {report(key, None, built, [], 'parado: fotos em duvida')}", flush=True)
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
    form = Form(page, rules.get("empresa", ""), item.get("tipo", ""))
    page.wait_for_timeout(2500)
    form.run(built["passos"], photos)
    intake.update(key, preenchido=learning.snapshot(built["passos"]))
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
    button = page.evaluate_handle(SAVE_JS).as_element()
    if not button:
        raise LookupError("botao SALVAR nao apareceu: nada foi salvo")
    button.click()
    # Depois do clique nao repete: tentar de novo criaria um cadastro em dobro.
    try:
        page.wait_for_selector("text=/refer[eê]ncia/i", timeout=SAVE_WAIT_MS)
        found = re.search(r"refer[eê]ncia\s+([A-Z]{1,3}\d+)", page.content(), re.IGNORECASE)
        reference = found.group(1) if found else ""
        page.get_by_role("button", name=YES).locator("visible=true").first.click(timeout=10_000)
        page.wait_for_timeout(1500)
    except Exception as exc:
        warning = page.evaluate(SAVE_WARNING_JS)
        picture = REPORTS / f"kenlo-salvar-{key}.png"
        page.screenshot(path=str(picture), full_page=False)
        intake.mark(key, intake.REVIEW, f"Conferir no Kenlo: cliquei em Salvar e nao vi a confirmacao. {warning}"[:300])
        print(f"KENLO_RESULTADO=CONFERIR {key} {report(key, form, built, field_map, f'cliquei em salvar sem confirmacao: {plain_problem(exc)}. Na tela: {warning}')}", flush=True)
        questions.ask_owner(f"cliquei em Salvar no {key} e não vi a confirmação. Na tela: {warning or 'nenhum aviso'}. Veja a janela antes de fechar.", ["Entendi"])
        wait_closed(page)
        return False
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


def demonstrate(page, text: str) -> list[dict]:
    """Traz a janela para a frente, espera o dono e devolve os cliques que valem repetir."""
    from dodaios.core import agent_questions as questions

    page.evaluate(RECORD_JS)
    page.bring_to_front()
    reply = questions.ask_owner(text, ["Pronto", "Cancelar"], ANSWER_WAIT_S)
    clicks = page.evaluate("() => window.__jaClicks || []") if reply else []
    return [item for item in clicks if item["texto"] and not questions.forbidden_click(item["texto"])]


def look_again(page, read: dict) -> bool:
    """Sem imovel novo, confere com o dono antes de fechar a janela."""
    from dodaios.core import agent_questions as questions

    code = read.get("maior_codigo", 0)
    seen = f" O último código que li foi o {code}." if code else " Não consegui ler nenhum código no grupo."
    reply = questions.ask_owner(f"não encontrei imóvel novo para cadastrar.{seen} Está certo, ou devo fazer algo?", ["Está certo", questions.SHOW, "Procurar de novo"], EMPTY_WAIT_S)
    if questions.interpret(reply)["acao"] == "mostrar":
        demonstrate(page, "pode mostrar no WhatsApp: deixe a ficha do imóvel na tela e clique em Pronto.")
        return True
    return bool(reply) and not re.search(r"\b(certo|ok|sim|deixa|para|parar|nada)\b", reply.lower())


def run_all(group: str, save: bool, fallback: str) -> int:
    """Uma janela, duas abas: cadastra em sequencia ate o grupo nao ter novos."""
    from playwright.sync_api import sync_playwright

    from dodaios.core import agent_questions as questions, property_intake as intake

    intake.retry_stopped()
    whatsapp = reader()
    with sync_playwright() as playwright:
        context = browser(playwright)
        chat = context.pages[0] if context.pages else context.new_page()
        kenlo = context.new_page()
        try:
            learn_from_finished(kenlo)
        except Exception as exc:  # aprender nunca impede o cadastro
            print(f"AVISO=aprendizado: {str(exc).splitlines()[0][:160]}", flush=True)
        questions.with_owner("abrir o grupo do WhatsApp", lambda: whatsapp.open_chat(chat, group))
        handled: set[str] = set()
        count = 0
        for _try in range(EMPTY_TRIES):
            for _ in range(MAX_ROUNDS):
                chat.bring_to_front()
                last_read = questions.with_owner("ler o grupo do WhatsApp", lambda: whatsapp.scan(chat), lambda: demonstrate(chat, "deixe a ficha do imóvel na tela e clique em Pronto."))
                print("WHATSAPP_LIDO=" + json.dumps(last_read, ensure_ascii=False), flush=True)
                key = next_key()
                if not key or key in handled:
                    break
                while key and key not in handled:
                    handled.add(key)
                    current = key
                    count += questions.with_owner(f"cadastrar o {current}", lambda: fill(kenlo, current, save), lambda: demonstrate(kenlo, "pode mostrar na janela do agente e clicar em Pronto."))
                    if not save or kenlo.is_closed():
                        print(f"CADASTROS_FEITOS={count}", flush=True)
                        close(context)
                        return 0
                    key = next_key()
            if handled or not look_again(chat, last_read):
                break
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

    rules = plan.load_rules()
    done = rules.get("ja_cadastrados", {})
    for _ in range(1000):
        item = intake.next_pending(int(rules.get("codigo_inicial", 0)))
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
