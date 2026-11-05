"""Resume os cadastros lidos do Kenlo: o que se repete por tipo e por condominio.

So le o que o agente salvou localmente. Nada aqui altera regras: o resumo vira
proposta para o dono aprovar.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Final

TYPES: Final[dict[str, str]] = {"pavilhao": "pavilh|galp", "apartamento": "apartamento", "casa": "casa|sobrado", "sala": "sala", "loja": "loja", "terreno": "terreno|lote", "predio": "predio"}
PER_TYPE: Final[int] = 100
COMMON_SHARE: Final[float] = 0.7
MIN_RECORDS: Final[int] = 3
PRIVATE: Final[re.Pattern[str]] = re.compile(r"propriet|nome(?! do condom)|tel\b|tel\.|celular|e-?mail|cpf|rg\b|cnpj|chave|senha|comiss|confidencial|coment|observa", re.IGNORECASE)


def folder() -> Path:
    from dodaios.core.paths import user_data_dir

    return user_data_dir() / "data" / "imoveis" / "leitura"


def kind_of(title: str) -> str:
    plain = "".join(c for c in unicodedata.normalize("NFKD", title) if not unicodedata.combining(c)).lower()
    tail = plain.rsplit(" - ", 1)[-1]
    return next((kind for kind, pattern in TYPES.items() if re.search(pattern, tail)), "") or re.sub(r"[^a-z0-9]+", "-", tail).strip("-")[:30]


def save(reference: str, record: dict[str, Any]) -> None:
    path = folder() / f"{re.sub(r'[^A-Za-z0-9-]', '-', reference)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = {**record, "campos": {name: value for name, value in record.get("campos", {}).items() if not PRIVATE.search(name)}}
    path.write_text(json.dumps(clean, ensure_ascii=False, indent=1), encoding="utf-8")


def add_goal(reference: str, goal: str) -> None:
    """Imovel em venda e locacao: lido uma vez, conta nas duas."""
    path = folder() / f"{re.sub(r'[^A-Za-z0-9-]', '-', reference)}.json"
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not record.get(goal):
        path.write_text(json.dumps({**record, goal: True}, ensure_ascii=False, indent=1), encoding="utf-8")


def load_all() -> list[dict[str, Any]]:
    records = []
    for path in sorted(folder().glob("*.json")):
        if path.name == "resumo.json":
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if not record.get("inativo"):
                records.append(record)
        except (OSError, ValueError):
            continue
    return records


def _common(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    values: Counter[tuple[str, str]] = Counter((name, str(value)) for record in records for name, value in record.get("campos", {}).items() if value not in ("", None))
    boxes = Counter(name for record in records for name in record.get("marcados", []))
    best: dict[str, tuple[str, int]] = {}
    for (name, value), count in values.items():
        if count > best.get(name, ("", 0))[1]:
            best[name] = (value, count)
    return {"imoveis": total, "campos": {name: value for name, (value, count) in sorted(best.items()) if count / total >= COMMON_SHARE},
            "marcados": sorted(name for name, count in boxes.items() if count / total >= COMMON_SHARE)}


def summarize() -> dict[str, Any]:
    records = load_all()
    groups = sorted({(item.get("finalidade", ""), item.get("tipo", "")) for item in records})
    types = {f"{purpose}-{kind}-{goal}": _common(items) for purpose, kind in groups for goal in ("venda", "locacao")
             if len(items := [item for item in records if item.get("tipo") == kind and item.get("finalidade", "") == purpose and item.get(goal)]) >= MIN_RECORDS}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        place = record.get("lista", {}).get("enterprise") or ""
        name = str(place.get("name", "") if isinstance(place, dict) else place).strip()
        if name and not name.lower().startswith("selecione"):
            grouped.setdefault(name, []).append(record)
    summary = {"lidos": len(records), "por_tipo": {key: value for key, value in Counter(f"{item.get('finalidade', '')}-{item.get('tipo', '')}-{goal}" for item in records for goal in ("venda", "locacao") if item.get(goal)).items()}, "tipos": types, "condominios": {name: _common(items) for name, items in grouped.items()}}
    folder().mkdir(parents=True, exist_ok=True)
    (folder() / "resumo.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    return summary
