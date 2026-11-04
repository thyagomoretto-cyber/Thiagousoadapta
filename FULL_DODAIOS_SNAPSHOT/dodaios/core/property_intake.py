"""Fila de imoveis recebidos: classifica, evita repeticao e guarda o andamento.

A classificacao usa regras fixas, porque repetir o mesmo resultado importa mais
do que adivinhar. Tudo que nao fica claro no texto vira duvida, e o imovel vai
para revisao em vez de ser cadastrado errado.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

_LOCK = threading.Lock()
PENDING: Final[str] = "pendente"
DONE: Final[str] = "cadastrado"
REVIEW: Final[str] = "revisar"
_STATUSES: Final[frozenset[str]] = frozenset({PENDING, DONE, REVIEW})

_TYPES: Final[tuple[tuple[str, str, str], ...]] = (
    ("apartamento", "residencial", r"\b(apartamento|apto|ap\.|cobertura|kitnet|studio)\b"),
    ("casa", "residencial", r"\b(casa|sobrado)\b"),
    ("sala", "comercial", r"\b(sala|conjunto comercial)\b"),
    ("loja", "comercial", r"\b(loja|ponto comercial)\b"),
    ("predio", "comercial", r"\bpredio\b"),
    ("pavilhao", "comercial", r"\b(pavilhao|galpao|deposito)\b"),
    ("terreno", "comercial", r"\b(terreno|lote|area de terras)\b"),
)
# Fichas sem o nome do tipo: estes detalhes so aparecem em pavilhoes.
_PAVILION_HINT = re.compile(r"\b(docas?|rampas? de acesso|pe[\s-]direito)\b")
_NOT_CONDOMINIUM = re.compile(r"\b(sem condominio|nao e condominio|nao tem condominio|fora de condominio|isento de condominio|rua aberta)\b")
_CONDOMINIUM = re.compile(r"\b(condominio|cond\.|residencial fechado|portaria 24)\b")
_CODE = re.compile(r"\b(?:codigo|cod|referencia|ref)\b\s*[:#.\-]?\s*([a-z0-9-]*\d[a-z0-9-]*)\b")


def _fold(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in plain if not unicodedata.combining(c)).lower()


def _types_in(text: str) -> list[tuple[str, str]]:
    found = [(match.start(), kind, purpose) for kind, purpose, pattern in _TYPES for match in [re.search(pattern, text)] if match]
    return [(kind, purpose) for _start, kind, purpose in sorted(found)]


def classify(text: str) -> dict[str, Any]:
    """Tipo, finalidade e condominio; o que nao estiver claro vai em ``duvidas``."""
    folded = _fold(text)
    lines = [line for line in folded.splitlines() if line.strip()]
    doubts: list[str] = []
    in_title = _types_in(lines[0]) if lines else []
    labeled = re.search(r"^\s*tipo\s*:\s*(.+)$", folded, re.MULTILINE)
    candidates = (_types_in(labeled.group(1)) if labeled else []) or in_title or _types_in(folded)
    kinds = {kind for kind, _purpose in candidates}
    kind, purpose = "", ""
    if len(kinds) == 1:
        kind, purpose = candidates[0]
    elif candidates:
        doubts.append(f"Mais de um tipo no texto: {', '.join(sorted(kinds))}")
    elif _PAVILION_HINT.search(folded):
        kind, purpose = "pavilhao", "comercial"
    else:
        doubts.append("Tipo do imovel nao identificado")
    if re.search(r"\bcomercial\b", lines[0] if lines else "") and kind in ("casa", "apartamento"):
        purpose = "comercial"
    if re.search(r"\bresidencial\b", lines[0] if lines else "") and kind == "terreno":
        purpose = "residencial"
    stated = re.search(r"^\s*finalidade\s*:\s*(residencial|comercial)", folded, re.MULTILINE)
    if stated and kind:
        purpose = stated.group(1)
    # Se a ficha nao fala em condominio, o imovel nao esta em um.
    condominium = bool(_CONDOMINIUM.search(folded)) and not _NOT_CONDOMINIUM.search(folded)
    return {"tipo": kind, "finalidade": purpose, "condominio": condominium, "duvidas": doubts}


def property_key(text: str) -> str:
    """Identidade do imovel: o codigo escrito, ou a impressao do texto."""
    folded = _fold(text)
    code = _CODE.search(folded)
    if code:
        return f"codigo-{code.group(1)}"
    words = re.sub(r"[^a-z0-9]+", " ", folded).split()
    return "texto-" + hashlib.sha256(" ".join(words).encode()).hexdigest()[:16]


def _root() -> Path:
    from dodaios.core.paths import user_data_dir

    return user_data_dir() / "data" / "imoveis"


def _ledger_path() -> Path:
    return _root() / "registro.json"


def _load() -> dict[str, Any]:
    try:
        return json.loads(_ledger_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(ledger: dict[str, Any]) -> None:
    path = _ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as output:
            json.dump(ledger, output, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def photo_folder(key: str) -> Path:
    return _root() / "fotos" / re.sub(r"[^a-z0-9-]", "-", key)


def get(key: str) -> dict[str, Any] | None:
    with _LOCK:
        return _load().get(key)


def update(key: str, **fields: Any) -> dict[str, Any]:
    """Guarda dados extras do imovel, como a ordem final das fotos."""
    with _LOCK:
        ledger = _load()
        ledger[key].update(fields)
        _save(ledger)
        return ledger[key]


def has_photos(key: str) -> bool:
    item = _load().get(key)
    return bool(item and item.get("fotos"))


def receive(text: str, photos: list[str] | None = None) -> tuple[str, bool]:
    """Registra um imovel recebido; devolve a chave e se ele e novo."""
    key = property_key(text)
    with _LOCK:
        ledger = _load()
        known = ledger.get(key)
        if known:
            merged = sorted({*known.get("fotos", []), *(photos or [])})
            if merged != known.get("fotos", []):
                known["fotos"] = merged
                # Fotos que chegaram depois do texto liberam o imovel parado.
                if known["status"] == REVIEW and not known.get("duvidas"):
                    known["status"] = PENDING
                _save(ledger)
            return key, False
        info = classify(text)
        ledger[key] = {
            "chave": key,
            "texto": text.strip(),
            "fotos": sorted(photos or []),
            **info,
            "status": REVIEW if info["duvidas"] else PENDING,
            "recebido": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        _save(ledger)
    return key, True


def _queue_order(item: dict[str, Any]) -> tuple[int, str]:
    """Sempre em sequencia: codigo 2 antes do 3; sem codigo, por ultimo."""
    code = re.fullmatch(r"codigo-(\d+)", item["chave"])
    return int(code.group(1)) if code else 10**9, item["recebido"]


def all_items() -> list[dict[str, Any]]:
    with _LOCK:
        return sorted(_load().values(), key=_queue_order)


def next_pending() -> dict[str, Any] | None:
    with _LOCK:
        pending = [item for item in _load().values() if item["status"] == PENDING]
    return min(pending, key=_queue_order) if pending else None


def mark(key: str, status: str, note: str = "") -> dict[str, Any]:
    if status not in _STATUSES:
        raise ValueError("situacao invalida")
    with _LOCK:
        ledger = _load()
        if key not in ledger:
            raise KeyError(key)
        ledger[key].update(status=status, nota=note.strip(), atualizado=datetime.now(UTC).isoformat(timespec="seconds"))
        _save(ledger)
        return ledger[key]


def resolve(key: str, answers: dict[str, Any]) -> dict[str, Any]:
    """Aplica a resposta do dono a um imovel em revisao e devolve-o a fila."""
    with _LOCK:
        ledger = _load()
        item = ledger[key]
        for field in ("tipo", "finalidade", "condominio"):
            if answers.get(field) not in (None, ""):
                item[field] = answers[field]
        if not item["tipo"] or not item["finalidade"] or item["condominio"] is None:
            raise ValueError("faltam dados do imovel")
        item.update(status=PENDING, duvidas=[])
        _save(ledger)
        return item


def summary() -> dict[str, Any]:
    with _LOCK:
        items = list(_load().values())
    counts = {status: sum(item["status"] == status for item in items) for status in _STATUSES}
    return {"contagem": counts, "revisar": [item for item in items if item["status"] == REVIEW]}
