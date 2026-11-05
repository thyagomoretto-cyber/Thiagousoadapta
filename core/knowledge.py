"""Conhecimento de cada especialista: fontes da internet, com busca e citacao.

O especialista responde so com trechos das fontes salvas e cita de onde vieram.
Sem trecho, ele diz que nao encontrou. Fontes oficiais vem primeiro. Tudo fica
em ``data/company_knowledge``, separado por empresa, fora do repositorio.
"""
from __future__ import annotations

import asyncio
import itertools
import json
import math
import os
import queue
import re
import tempfile
import threading
import unicodedata
from collections import Counter
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Final
from urllib.parse import urlparse

STUDY_VERSION: Final[int] = 2  # subir faz todos os especialistas estudarem de novo
RETRY_AFTER: Final[timedelta] = timedelta(days=1)
MAX_PAGES: Final[int] = 14
MAX_RESULTS: Final[int] = 8
MIN_PAGE_CHARS: Final[int] = 800
MAX_PAGE_CHARS: Final[int] = 2_500_000
CHUNK_CHARS: Final[int] = 1_200
TOP_CHUNKS: Final[int] = 6
OWN_BOOST: Final[float] = 1.5
FETCH_TIMEOUT_S: Final[float] = 25.0
ANSWER_TIMEOUT_S: Final[float] = 180.0
ANSWER_TOKENS: Final[int] = 4000
OFFICIAL_HOSTS: Final[re.Pattern[str]] = re.compile(r"\.(gov|jus|leg|mp)\.br$|^(www\.)?planalto\.gov\.br$")
SEARCHES_AT_ONCE: Final[int] = 3
_QUERIES: Final[tuple[str, ...]] = ("{topic}", "{topic} texto oficial", "{topic} site:gov.br", "{topic} jurisprudencia", "{topic} como funciona",
                                    "{topic} passo a passo", "{topic} documentos necessarios", "{topic} prazos", "{topic} erros comuns", "{topic} duvidas frequentes")
_PLANALTO: Final[str] = "https://www.planalto.gov.br/ccivil_03/"
# A lei em vigor entra sempre: a busca pode nao trazer o texto oficial.
_LAWS: Final[tuple[tuple[str, str], ...]] = (
    (r"inquilin|locac|aluguel|desocup|vistoria|fianca", "leis/l8245.htm"),
    (r"contrato|civil|condomin|fianca|aditivo", "leis/2002/l10406compilada.htm"),
    (r"consumidor|cliente|atendimento", "leis/l8078compilado.htm"),
    (r"trabalh|clt|funcionari|\brh\b", "decreto-lei/del5452.htm"),
    (r"lgpd|dados pessoais|privacidade", "_ato2015-2018/2018/lei/l13709.htm"),
)
_STOP: Final[frozenset[str]] = frozenset("a o e as os de da do das dos em no na nos nas um uma uns umas para por com que qual quais como se ao aos ou sobre pode posso deve tem ter ser sao foi".split())
_SKIP_TAGS: Final[frozenset[str]] = frozenset({"script", "style", "noscript", "nav", "footer", "header", "aside", "form", "svg"})
_BLOCK_TAGS: Final[frozenset[str]] = frozenset({"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "section", "article", "table"})
_REVOKED_TAGS: Final[frozenset[str]] = frozenset({"strike", "s", "del"})  # texto revogado
_LOCK = threading.Lock()
_jobs: "queue.PriorityQueue[tuple[int, int, tuple[str, str, str, Callable[[dict[str, Any]], None] | None, bool]]]" = queue.PriorityQueue()
_order = itertools.count()
_waiting: dict[tuple[str, str], list[Callable[[dict[str, Any]], None]]] = {}
_pending: set[tuple[str, str]] = set()
_worker: threading.Thread | None = None


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._struck = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _REVOKED_TAGS:
            self._struck += 1
        elif tag in _SKIP_TAGS:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _REVOKED_TAGS and self._struck:
            self._struck -= 1
        elif tag == "p":
            self._struck = 0  # as paginas de leis nem sempre fecham o tachado
            self.parts.append("\n")
        elif tag in _SKIP_TAGS and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif not self._skip and not self._struck:
            self.parts.append(data)


def page_text(html: str) -> tuple[str, str]:
    parser = _Text()
    parser.feed(html)
    text = re.sub(r"[ \t\xa0]+", " ", "".join(parser.parts))
    return parser.title.strip()[:200], re.sub(r"\n\s*\n+", "\n", text).strip()[:MAX_PAGE_CHARS]


def _fold(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in plain if not unicodedata.combining(c)).lower()


def _terms(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]{2,}", _fold(text))
    return [word[:-1] if len(word) > 4 and word.endswith("s") else word for word in words if word not in _STOP]


def chunks(text: str) -> list[str]:
    """Corta nos artigos quando existem, para cada trecho citar um artigo inteiro."""
    pieces = re.split(r"\n(?=Art\.?\s*\d)", text)
    result: list[str] = []
    for piece in pieces:
        buffer = ""
        for line in piece.split("\n"):
            if buffer and len(buffer) + len(line) > CHUNK_CHARS:
                result.append(buffer.strip())
                buffer = ""
            buffer += line + "\n"
        if buffer.strip():
            result.append(buffer.strip())
    return [item for item in result if len(item) > 40]


def _folder(company_id: str, skill_id: str) -> Path:
    from dodaios.core.paths import user_data_dir

    safe = [re.sub(r"[^a-zA-Z0-9_-]", "-", part)[:80] for part in (company_id, skill_id)]
    return user_data_dir() / "data" / "company_knowledge" / safe[0] / safe[1]


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as output:
            json.dump(data, output, ensure_ascii=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def status(company_id: str, skill_id: str) -> dict[str, Any]:
    try:
        return json.loads((_folder(company_id, skill_id) / "estado.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"estado": "vazio", "fontes": [], "trechos": 0}


def _chunks_of(company_id: str, skill_id: str) -> list[dict[str, Any]]:
    try:
        return json.loads((_folder(company_id, skill_id) / "trechos.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def is_official(url: str) -> bool:
    return bool(OFFICIAL_HOSTS.search(urlparse(url).hostname or ""))


async def _search(query: str) -> list[dict[str, Any]]:
    import httpx

    from dodaios.plugins.tool.search_backends import run_search
    from dodaios.plugins.tool.search_web import _load_apifare_key

    async with httpx.AsyncClient(timeout=FETCH_TIMEOUT_S) as client:
        outcome = await run_search(query, MAX_RESULTS, client=client, apifare_key=_load_apifare_key())
    return [dict(item) for item in outcome.results]


async def _fetch(url: str) -> str:
    import httpx

    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) DodaiOS/1.0", "Accept-Language": "pt-BR,pt;q=0.9"}
    async with httpx.AsyncClient(timeout=FETCH_TIMEOUT_S, follow_redirects=True, headers=headers) as client:
        reply = await client.get(url)
    reply.raise_for_status()
    if "html" not in reply.headers.get("content-type", "html"):
        return ""
    return decode_page(reply.content, reply.headers.get("content-type", ""))


def decode_page(content: bytes, content_type: str = "") -> str:
    """As paginas do governo costumam vir em latin-1 sem avisar no cabecalho."""
    declared = re.search(r"charset=[\"']?([\w-]+)", content_type) or re.search(r"charset=[\"']?([\w-]+)", content[:3000].decode("ascii", "ignore"))
    for encoding in ([declared.group(1)] if declared else []) + ["utf-8", "cp1252"]:
        try:
            return content.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return content.decode("utf-8", "replace")


def official_pages(topic: str) -> list[str]:
    plain = _fold(topic)
    return [_PLANALTO + page for pattern, page in _LAWS if re.search(pattern, plain)]


async def research(company_id: str, skill_id: str, topic: str, on_done: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    """Pesquisa o tema, baixa as paginas e guarda os trechos com a fonte."""
    folder = _folder(company_id, skill_id)
    previous = status(company_id, skill_id)
    previous = {**previous, "estado": "pronto"} if previous.get("trechos") else {}
    _write_json(folder / "estado.json", {**previous, "estado": "pesquisando", "tema": topic, "fontes": previous.get("fontes", []), "trechos": previous.get("trechos", 0)})
    found: dict[str, dict[str, Any]] = {}
    limit = asyncio.Semaphore(SEARCHES_AT_ONCE)

    async def one_search(query: str) -> list[dict[str, Any]]:
        async with limit:
            return await _search(query)

    outcomes = await asyncio.gather(*[one_search(query.format(topic=topic)) for query in _QUERIES], return_exceptions=True)
    for url in official_pages(topic):
        found.setdefault(url, {"url": url})
    for outcome in outcomes:
        if isinstance(outcome, list):
            for item in outcome:
                url = str(item.get("url") or item.get("href") or "")
                if url.startswith("http") and not url.lower().endswith(".pdf"):
                    found.setdefault(url, item)
    ranked = sorted(found, key=lambda url: not is_official(url))[:MAX_PAGES * 2]
    sources: list[dict[str, Any]] = []
    saved: list[dict[str, Any]] = []
    for url in ranked:
        if len(sources) >= MAX_PAGES:
            break
        try:
            title, text = page_text(await _fetch(url))
        except Exception:
            continue
        if len(text) < MIN_PAGE_CHARS:
            continue
        index = len(sources)
        sources.append({"url": url, "titulo": title or found[url].get("title", url), "oficial": is_official(url), "tamanho": len(text)})
        saved += [{"fonte": index, "texto": piece} for piece in chunks(text)]
    if saved:
        sources, saved = _with_own(previous, sources, saved, _chunks_of(company_id, skill_id))
    state = {"estado": "pronto" if saved else "sem_fontes", "tema": topic, "fontes": sources, "trechos": len(saved), "versao": STUDY_VERSION,
             "quando": datetime.now(UTC).isoformat(timespec="seconds")}
    with _LOCK:
        if not saved and previous.get("trechos"):
            state = previous  # uma pesquisa que falhou nao apaga o que ele ja sabia
        else:
            _write_json(folder / "trechos.json", saved)
        _write_json(folder / "estado.json", state)
    if on_done:
        on_done(state)
    return state


def mark(company_id: str, skill_id: str, **fields: Any) -> None:
    with _LOCK:
        _write_json(_folder(company_id, skill_id) / "estado.json", {**status(company_id, skill_id), **fields})


def _with_own(previous: dict[str, Any], sources: list[dict[str, Any]], saved: list[dict[str, Any]], old: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Um novo estudo na web nao apaga o que a propria empresa ensinou."""
    own = [source for source in previous.get("fontes", []) if source.get("propria")]
    if not own:
        return sources, saved
    return [*sources, own[0]], [*saved, *({**item, "fonte": len(sources)} for item in old if item.get("propria"))]


def add_own(company_id: str, skill_id: str, title: str, pieces: list[str]) -> int:
    """Troca a fonte propria da empresa, mantendo o que veio de outras fontes."""
    with _LOCK:
        state = status(company_id, skill_id)
        sources = [source for source in state.get("fontes", []) if not source.get("propria")]
        old = _chunks_of(company_id, skill_id)
        kept = [item for item in old if not item.get("propria")]
        taught = [{**item, "fonte": len(sources)} for item in old if item.get("licao")]
        saved = kept + taught + [{"fonte": len(sources), "texto": piece, "propria": True} for piece in pieces]
        folder = _folder(company_id, skill_id)
        _write_json(folder / "trechos.json", saved)
        _write_json(folder / "estado.json", {**state, "estado": "pronto", "trechos": len(saved),
                                             "fontes": [*sources, {"url": "", "titulo": title, "oficial": False, "tamanho": sum(map(len, pieces)), "propria": True}]})
    return len(pieces)


def teach(company_id: str, skill_id: str, text: str) -> None:
    """Licao do dono: fica junto da fonte propria e sobrevive a novos estudos e leituras."""
    with _LOCK:
        state = status(company_id, skill_id)
        sources = state.get("fontes", [])
        place = next((index for index, source in enumerate(sources) if source.get("propria")), None)
        if place is None:
            place, sources = len(sources), [*sources, {"url": "", "titulo": "Ensinado pelo dono", "oficial": False, "tamanho": 0, "propria": True}]
        saved = [*_chunks_of(company_id, skill_id), {"fonte": place, "texto": text, "propria": True, "licao": True}]
        folder = _folder(company_id, skill_id)
        _write_json(folder / "trechos.json", saved)
        _write_json(folder / "estado.json", {**state, "estado": "pronto", "fontes": sources, "trechos": len(saved)})


def unteach(company_id: str, skill_id: str, text: str) -> None:
    with _LOCK:
        saved = [item for item in _chunks_of(company_id, skill_id) if not (item.get("licao") and item["texto"] == text)]
        _write_json(_folder(company_id, skill_id) / "trechos.json", saved)
        _write_json(_folder(company_id, skill_id) / "estado.json", {**status(company_id, skill_id), "trechos": len(saved)})


def needs_study(company_id: str, skill_id: str) -> bool:
    """Sem conhecimento, ou com um estudo cortado quando o app reiniciou."""
    if (company_id, skill_id) in _pending:
        return False
    state = status(company_id, skill_id)
    if state["estado"] == "sem_fontes" and state.get("quando", "") > (datetime.now(UTC) - RETRY_AFTER).isoformat(timespec="seconds"):
        return False  # nao achou nada hoje: tenta de novo so amanha
    return state["estado"] != "pronto" or state.get("versao", 1) < STUDY_VERSION


def _work() -> None:
    while True:
        _rank, _number, (company_id, skill_id, topic, on_done, only_finish) = _jobs.get()
        try:
            if only_finish:
                if on_done:
                    on_done(status(company_id, skill_id))
            else:
                asyncio.run(research(company_id, skill_id, topic, on_done))
        except Exception:
            state = status(company_id, skill_id)
            mark(company_id, skill_id, estado="pronto" if state.get("trechos") else "sem_fontes")
        finally:
            _pending.discard((company_id, skill_id))
            for follower in _waiting.pop((company_id, skill_id), []):
                try:
                    follower(status(company_id, skill_id))
                except Exception:
                    pass


def when_ready(company_id: str, skill_id: str, follower: Callable[[dict[str, Any]], None]) -> bool:
    """Avisa quando o estudo em andamento terminar; False se nao ha estudo."""
    with _LOCK:
        if (company_id, skill_id) not in _pending:
            return False
        _waiting.setdefault((company_id, skill_id), []).append(follower)
        return True


def enqueue(company_id: str, skill_id: str, topic: str, on_done: Callable[[dict[str, Any]], None] | None = None, only_finish: bool = False, urgent: bool = False) -> None:
    """Um estudo por vez, para nao pesar no computador nem nas buscas."""
    global _worker
    with _LOCK:
        if (company_id, skill_id) in _pending:
            return
        _pending.add((company_id, skill_id))
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_work, name="especialista-pesquisa", daemon=True)
            _worker.start()
    if not only_finish:
        mark(company_id, skill_id, estado="aguardando", tema=topic, fontes=status(company_id, skill_id).get("fontes", []), trechos=status(company_id, skill_id).get("trechos", 0))
    _jobs.put((0 if urgent else 1, next(_order), (company_id, skill_id, topic, on_done, only_finish)))


def search(company_id: str, skill_id: str, question: str, limit: int = TOP_CHUNKS) -> list[dict[str, Any]]:
    """Busca por relevancia. Artigo citado na pergunta vem primeiro."""
    items = _chunks_of(company_id, skill_id)
    wanted = Counter(_terms(question))
    if not items or not wanted:
        return []
    bags = [Counter(_terms(item["texto"])) for item in items]
    documents = Counter(term for bag in bags for term in bag)
    total = len(items)
    article = re.search(r"\bart(?:igo)?\.?\s*(\d+)", _fold(question))
    scored = []
    for item, bag in zip(items, bags):
        score = sum(math.log(1 + total / (1 + documents[term])) * bag[term] / (bag[term] + 1.5) for term in wanted if term in bag)
        if article and re.match(rf"art\.?\s*{article.group(1)}\b", _fold(item["texto"])):
            score += 50
        if score > 0:
            score *= OWN_BOOST if item.get("propria") else 1
            scored.append((score, {**item, "cobertura": round(sum(term in bag for term in wanted) / len(wanted), 2)}))
    scored.sort(key=lambda pair: -pair[0])
    sources = status(company_id, skill_id).get("fontes", [])
    return [{**item, "pontos": round(score, 2), "url": sources[item["fonte"]]["url"] if item["fonte"] < len(sources) else "",
             "oficial": sources[item["fonte"]]["oficial"] if item["fonte"] < len(sources) else False} for score, item in scored[:limit]]


def answer(company_id: str, skill_id: str, name: str, question: str) -> dict[str, Any]:
    """Resposta do especialista, so com o que esta nas fontes dele."""
    from dodaios.core import photo_vision as vision

    hits = search(company_id, skill_id, question)
    if not hits:
        return {"resposta": f"{name}: nao encontrei isso nas minhas fontes.", "fontes": [], "encontrou": False}
    context = "\n\n".join(f"[{index + 1}] {hit['texto']}" for index, hit in enumerate(hits))
    prompt = (f"Voce e {name}. Responda a pergunta usando somente os trechos abaixo. Cite o numero do trecho entre colchetes e o artigo, quando houver. "
              f"Se os trechos nao responderem, diga exatamente: nao encontrei isso nas minhas fontes. Nao invente.\n\nPergunta: {question}\n\nTrechos:\n{context}")
    try:
        reply = vision._chat(prompt, ANSWER_TIMEOUT_S, ANSWER_TOKENS).strip()
    except Exception:
        reply = "Modelo indisponivel agora. Trechos encontrados:\n" + "\n\n".join(hit["texto"][:500] for hit in hits[:3])
    urls = list(dict.fromkeys(hit["url"] for hit in hits if hit["url"]))
    return {"resposta": reply, "fontes": urls, "encontrou": True}
