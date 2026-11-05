#!/usr/bin/env python3
"""Le cadastros prontos do Kenlo para aprender, sem alterar nada.

Depois do login, usa a busca do Kenlo para pegar a lista de cada finalidade, em
venda e em locacao, e abre so a leitura de cada cadastro. Nao clica em Salvar,
nao preenche nada e nao exclui nada: as unicas acoes sao filtros e buscas.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
HERE = Path(__file__).resolve().parent
REPORTS = Path(os.environ.get("JA_KENLO_RELATORIOS") or Path.home() / "Downloads")
BASE_URL = os.environ.get("JA_KENLO_BASE") or "https://imob.valuegaia.com.br"
HOME_URL = os.environ.get("JA_KENLO_INICIO") or f"{BASE_URL}/admin/default.aspx"
LIST_URL = f"{BASE_URL}/admin/default.aspx#/search-properties"
EDIT_PATH = "/admin/modules/imoveis_beta/imovel-alterar.aspx"
LISTINGS = os.environ.get("JA_KENLO_LISTAGEM") or "listings.ingaia.com.br/listings"
LIST_FRAME = "modules-react"
PURPOSES = ("Residencial", "Comercial", "Industrial", "Rural", "Temporada", "Corporativa")
GOALS = ("venda", "locacao")
BOXES = {"venda": "for_sale", "locacao": "for_rent"}
ACTIVE = "ativo"
STREAK_LIMIT = 3
LIST_WAIT_S = int(os.environ.get("JA_KENLO_ESPERA_BUSCA") or 90)
LIST_RETRY_S = 25
RESPONSE_TIMEOUT_MS = 30_000
READ_PAUSE_MS = int(os.environ.get("JA_KENLO_PAUSA") or 400)
MAX_PAGES = 200
WATCH_LIMIT = 300
DIAGNOSIS = Path.home() / ".dodaios-data/data/imoveis/diagnostico"
KEEP = ("property_abbreviation_reference", "usage", "usage_type", "status", "beds", "bathrooms", "garages", "location_neighborhood", "location_city", "enterprise", "sale_price", "rent_price", "condo_price",
        "municipal_property_tax", "area_useful", "area_built", "number_of_photos", "exclusivity", "published_on_site", "tags")
CONTROLS_JS = r"""
() => [...document.querySelectorAll('button, a, input, select, label, [role=button], [role=combobox]')]
  .filter((node) => node.getClientRects().length)
  .map((node) => `${node.tagName.toLowerCase()}:${(node.innerText || node.placeholder || node.type || '').trim().slice(0, 30)}`)
  .filter((text, index, all) => all.indexOf(text) === index)
  .slice(0, 70)
"""
READ_JS = r"""
async (address) => {
  const answer = await fetch(address, { credentials: 'include' });
  const form = new DOMParser().parseFromString(await answer.text(), 'text/html');
  const words = (node) => {
    const copy = node.cloneNode(true);
    copy.querySelectorAll('select, input, textarea').forEach((item) => item.remove());
    return copy.textContent;
  };
  const name = (node) => {
    const label = node.labels && node.labels[0] ? words(node.labels[0]) : '';
    if (label.trim()) return label;
    let box = node.parentElement;
    for (let up = 0; box && up < 4; up += 1, box = box.parentElement) {
      const found = box.querySelector('label');
      if (found && !found.contains(node) && words(found).trim()) return words(found);
    }
    return node.getAttribute('aria-label') || node.name || '';
  };
  const clean = (text) => (text || '').replace(/[*:]/g, '').replace(/\s+/g, ' ').trim().slice(0, 80);
  const campos = {};
  for (const node of form.querySelectorAll('input, select, textarea')) {
    if (['hidden', 'password', 'file', 'checkbox', 'radio'].includes(node.type)) continue;
    const key = clean(name(node));
    const value = node.tagName === 'SELECT' ? (node.selectedOptions[0] ? node.selectedOptions[0].text : '') : node.value;
    if (key && value && !campos[key]) campos[key] = value.trim().slice(0, 1500);
  }
  const marcados = [...form.querySelectorAll('input[type=checkbox]:checked, input[type=radio]:checked')].map((node) => clean(name(node) || (node.parentElement && node.parentElement.textContent))).filter(Boolean);
  return { situacao: answer.status, destino: answer.url.split('?')[0], total: form.querySelectorAll('input, select, textarea').length, campos, marcados: [...new Set(marcados)] };
}
"""


def cadastro():
    spec = importlib.util.spec_from_file_location("ja_kenlo_cadastro", HERE / "ja-kenlo-cadastro.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def trace(page, step: str) -> None:
    """Rastro de cada passo para o diagnostico; sem conteudo da pagina."""
    try:
        size = page.evaluate("() => `${innerWidth}x${innerHeight}`")
    except Exception:
        size = "?"
    print(f"LEITURA_PASSO={time.strftime('%H:%M:%S')} {step} | {page.url.split('?')[0]} | {size}", flush=True)


def keep_picture(page, step: str) -> None:
    """Foto da tela no erro: fica so neste Mac, ate o limite de 12."""
    try:
        DIAGNOSIS.mkdir(parents=True, exist_ok=True)
        for old in sorted(DIAGNOSIS.glob("*.png"))[:-11]:
            old.unlink()
        page.screenshot(path=str(DIAGNOSIS / f"{time.strftime('%H%M%S')}-{re.sub(r'[^a-z0-9]+', '-', step.lower())[:40]}.png"))
    except Exception as exc:
        print(f"AVISO=sem foto da tela: {str(exc).splitlines()[0][:120]}", flush=True)


def list_controls(page) -> None:
    """Mostra so nomes de botoes e campos, para achar o que mudou na tela."""
    for index, frame in enumerate(page.frames):
        try:
            names = frame.evaluate(CONTROLS_JS)
        except Exception:
            continue
        if names:
            print(f"LEITURA_CONTROLES=quadro {index} {frame.url.split('?')[0][:80]} {json.dumps(names, ensure_ascii=False)[:1500]}", flush=True)


def watch_page(page) -> None:
    seen = {"total": 0}

    def note(kind: str, text: str) -> None:
        if seen["total"] < WATCH_LIMIT:
            seen["total"] += 1
            print(f"LEITURA_SITE={time.strftime('%H:%M:%S')} {kind} {text[:180]}", flush=True)

    page.on("response", lambda response: response.status >= 500 and "matomo" not in response.url and note(str(response.status), response.url.split("?")[0]))
    page.on("crash", lambda _: note("travou", "a aba caiu"))


def list_frame(page):
    """A busca do Kenlo fica num quadro interno."""
    return next((frame for frame in page.frames if LIST_FRAME in frame.url), None)


def search_button(page):
    frame = list_frame(page)
    if not frame:
        return None
    button = frame.locator("button.btn-advanced-search").locator("visible=true")
    return button.first if button.count() else None


def go_by_menu(page, tools) -> None:
    """Como no guia: entra pela pagina inicial e usa o menu Imoveis > Imoveis."""
    trace(page, "abrindo a pagina inicial")
    tools.wait_login(page, HOME_URL)
    trace(page, "pagina inicial aberta")
    menu = page.get_by_text(re.compile(r"^\s*im[oó]veis\s*$", re.IGNORECASE)).locator("visible=true")
    menu.first.wait_for(state="visible", timeout=RESPONSE_TIMEOUT_MS)
    opener = menu.first.bounding_box()
    menu.first.click()
    page.wait_for_timeout(700)
    below = [(box["y"], index) for index, item in enumerate(menu.all()) if (box := item.bounding_box()) and box["y"] > opener["y"] + 5]
    if not below:
        raise LookupError("o menu Imóveis não abriu")
    menu.nth(min(below)[1]).click()  # o item logo abaixo do menu, nao o titulo do painel
    trace(page, "cliquei em Imoveis no menu")


def go_to_search(page, tools) -> None:
    try:
        go_by_menu(page, tools)
    except Exception as exc:
        trace(page, "menu falhou")
        keep_picture(page, "menu")
        print(f"AVISO=menu nao funcionou ({str(exc).splitlines()[0][:120]}); indo pelo endereco", flush=True)
        tools.wait_login(page, LIST_URL)


def open_list(page, tools, shown: bool = False) -> None:
    """O Kenlo pode demorar: insiste antes de perguntar."""
    if not shown:
        go_to_search(page, tools)
    limit = time.monotonic() + LIST_WAIT_S
    again = time.monotonic() + LIST_RETRY_S
    while True:
        if search_button(page):
            trace(page, "busca aberta")
            return
        now = time.monotonic()
        if now > limit:
            trace(page, "busca nao apareceu")
            keep_picture(page, "busca")
            list_controls(page)
            raise LookupError(f"a busca de imóveis não apareceu; o Kenlo ficou em {page.url.split('?')[0]}")
        if tools.LOGIN_HOST in page.url or (now > again and not shown):
            again = now + LIST_RETRY_S
            go_to_search(page, tools)
        page.wait_for_timeout(1000)


def set_purpose(frame, purpose: str) -> None:
    box = frame.locator(".Select").filter(has=frame.locator("input[name=usage_id]")).first
    chosen = box.locator(".Select-value-label")
    if chosen.count() and chosen.first.inner_text().strip() == purpose:
        return
    box.locator(".Select-control").click()
    frame.locator(".Select-option").filter(has_text=re.compile(rf"^\s*{purpose}\s*$")).first.click()


def set_goal(frame, goal: str) -> None:
    for name, box in BOXES.items():
        if frame.locator(f"#{box}").is_checked() != (name == goal):
            frame.locator(f"label[for={box}].ingaia-checkbox").click()


def is_list_answer(response) -> bool:
    return LISTINGS in response.url and "page_num" in response.url


def fetch_list(page, purpose: str, goal: str) -> tuple[int, list[dict]]:
    """Busca e pede mais resultados ate acabar; o Kenlo devolve tudo pronto."""
    frame = list_frame(page)
    set_purpose(frame, purpose)
    set_goal(frame, goal)
    with page.expect_response(is_list_answer, timeout=RESPONSE_TIMEOUT_MS) as waited:
        search_button(page).click()
    answer = waited.value.json()
    total, hits = int(answer.get("total", 0)), list(answer.get("hits", []))
    trace(page, f"busca {purpose} {goal}: {total} imoveis")
    for _ in range(MAX_PAGES):
        more = frame.get_by_role("button", name=re.compile(r"mais resultados", re.IGNORECASE))
        if len(hits) >= total or not more.count():
            break
        with page.expect_response(is_list_answer, timeout=RESPONSE_TIMEOUT_MS) as waited:
            more.first.click()
        batch = waited.value.json().get("hits", [])
        if not batch:
            break
        hits += batch
    return total, hits


def choose(hits: list[dict], per_type: int, study) -> tuple[list[dict], dict]:
    """So os ativos, ate o limite de cada tipo; a Moretto vem primeiro."""
    active = [item for item in hits if str(item.get("status", "")).strip().lower() == ACTIVE]
    groups: dict[str, list[dict]] = {}
    for item in active:
        groups.setdefault(study.kind_of(f"- {item.get('usage_type', '')}"), []).append(item)
    chosen: list[dict] = []
    counts: dict[str, int] = {}
    for kind, items in sorted(groups.items()):
        ranked = sorted(items, key=lambda item: "moretto" not in " ".join(str(broker.get("broker_name", "")) for broker in item.get("brokers") or []).lower())[:per_type]
        counts[kind] = len(ranked)
        chosen += [{**item, "tipo": kind} for item in ranked]
    return chosen, {"ativos": len(active), "encontrados": counts}


def reference_of(item: dict) -> str:
    """A referencia da tela e o comeco do codigo que a busca devolve."""
    code = str(item.get("property_abbreviation_reference") or item.get("property_reference") or "")
    return code.split("-")[0] or str(item["id"])


def ordered_photos(item: dict) -> list[dict]:
    photos = sorted(item.get("photos") or [], key=lambda photo: photo.get("order") or 0)
    return [{"url": photo.get("big") or photo.get("serving") or photo.get("small"), "ordem": photo.get("order"), "capa": bool(photo.get("photo_highlight")), "legenda": photo.get("photo_legend") or ""} for photo in photos]


def read_one(page, item: dict) -> dict:
    data = page.evaluate(READ_JS, f"{BASE_URL}{EDIT_PATH}?id={item['id']}")
    if data["situacao"] != 200 or data["total"] < 20:
        raise LookupError(f"o cadastro não abriu (situação {data['situacao']}, {data['total']} campos)")
    return data


def read_batch(page, chosen: list[dict], purpose: str, goal: str, failed: list[str], questions, study) -> bool:
    streak = 0
    done = {path.stem for path in study.folder().glob("*.json")}
    for number, item in enumerate(chosen, 1):
        reference = reference_of(item)
        if reference in done:
            study.add_goal(reference, goal)
            continue
        try:
            data = read_one(page, item)
            streak = 0
            study.save(reference, {"ref": reference, "tipo": item["tipo"], "finalidade": purpose, goal: True, "campos": data["campos"], "marcados": data["marcados"], "fotos": ordered_photos(item),
                                   "lista": {key: item.get(key) for key in KEEP}, "lido_em": datetime.now().isoformat(timespec="seconds")})
            print(f"LEITURA_IMOVEL={purpose}/{goal} {number}/{len(chosen)} {reference} {item['tipo']} campos={len(data['campos'])} marcados={len(data['marcados'])} fotos={len(item.get('photos') or [])}", flush=True)
        except Exception as exc:
            failed.append(reference)
            streak += 1
            trace(page, f"falha em {reference}")
            print(f"LEITURA_FALHOU={reference} {questions.plain_error(exc)} | {str(exc).strip()[:300]}", flush=True)
            if streak >= STREAK_LIMIT:
                keep_picture(page, reference)
                reply = questions.ask_owner(f"não consegui ler {streak} imóveis seguidos: {questions.plain_error(exc)}. Continuo?", ["Continuar", "Parar"])
                if not reply or questions.interpret(reply)["acao"] == "parar":
                    return False
                streak = 0
        page.wait_for_timeout(READ_PAUSE_MS)
    return True


def run(per_type: int) -> int:
    from playwright.sync_api import sync_playwright

    from dodaios.core import agent_questions as questions, kenlo_study as study

    tools = cadastro()
    shape: list[dict] = []
    failed: list[str] = []
    with sync_playwright() as playwright:
        context = tools.browser(playwright)
        listing = context.pages[0] if context.pages else context.new_page()
        listing.bring_to_front()
        watch_page(listing)
        opened_by_owner = [False]

        def show_list() -> None:
            tools.demonstrate(listing, "abra a busca de imóveis nesta janela e clique em Pronto.")
            opened_by_owner[0] = True

        questions.with_owner("abrir a busca de imóveis", lambda: open_list(listing, tools, opened_by_owner[0]), show_list)
        going = True
        for purpose in PURPOSES:
            for goal in GOALS:
                if not going:
                    break

                def fail_list() -> None:
                    keep_picture(listing, f"lista-{purpose}-{goal}")
                    list_controls(listing)

                def get_list() -> tuple[int, list[dict]]:
                    try:
                        return fetch_list(listing, purpose, goal)
                    except Exception:
                        fail_list()
                        raise

                total, hits = questions.with_owner(f"buscar {purpose} em {goal}", get_list, lambda: tools.demonstrate(listing, f"deixe a busca aberta nesta janela e clique em Pronto. Depois tento {purpose} em {goal} de novo."))
                chosen, found = choose(hits, per_type, study)
                shape.append({"finalidade": purpose, "objetivo": goal, "total": total, **found})
                print("LEITURA_LISTA=" + json.dumps(shape[-1], ensure_ascii=False), flush=True)
                going = read_batch(listing, chosen, purpose, goal, failed, questions, study)
        summary = study.summarize()
        context.close()
    lines = [f"Leitura do Kenlo em {time.strftime('%d/%m/%Y %H:%M')}", f"Lista: {json.dumps(shape, ensure_ascii=False)}", f"Por tipo: {summary['por_tipo']}", f"Falhas: {failed}", ""]
    for kind, data in summary["tipos"].items():
        lines += [f"== {kind} ({data['imoveis']} imóveis)", f"Campos comuns: {data['campos']}", f"Marcados comuns: {data['marcados']}", ""]
    lines += [f"Condomínios: {len(summary['condominios'])}"]
    report = REPORTS / f"leitura-kenlo-{time.strftime('%Y%m%d-%H%M')}.txt"
    report.write_text("\n".join(lines), encoding="utf-8")
    print("LEITURA_RESULTADO=" + json.dumps({"lidos": summary["lidos"], "por_tipo": summary["por_tipo"], "falhas": len(failed), "relatorio": report.name}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--por-tipo", type=int, default=100)
    sys.exit(run(parser.parse_args().por_tipo))
