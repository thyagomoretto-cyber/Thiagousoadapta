"""Resume os cadastros lidos do Kenlo: o que se repete por tipo e por condominio.

So le o que o agente salvou localmente. Nada aqui altera regras: o resumo vira
proposta para o dono aprovar.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from difflib import SequenceMatcher
from datetime import datetime
from pathlib import Path
from typing import Any, Final

TYPES: Final[dict[str, str]] = {"pavilhao": "pavilh|galp", "apartamento": "apartamento", "casa": "casa|sobrado", "sala": "sala", "loja": "loja", "terreno": "terreno|lote", "predio": "predio"}
PER_TYPE: Final[int] = 100
COMMON_SHARE: Final[float] = 0.7
MIN_RECORDS: Final[int] = 3
MIN_SIMILAR: Final[int] = 3
MATCH_AVERAGE: Final[float] = 0.82
MATCH_WORD: Final[float] = 0.6
WEB_CONFIDENCE: Final[float] = 0.8
STANDARD_SHARE: Final[float] = 0.7
COUNT_FIELDS: Final[dict[str, str]] = {"banheiros": "bathrooms", "dormitorios": "beds", "vagas": "garages"}
NAME_NOISE: Final[re.Pattern[str]] = re.compile(r"\b(condominio|residencial|residence|club|edificio|edif|ed|cond|torre|bloco|predio|de|do|da|dos|das|e|\d+)\b\.?")
STREET_NOISE: Final[re.Pattern[str]] = re.compile(r"\b(rua|r|avenida|av|travessa|tv|estrada|alameda|al|rodovia|rs|br|de|do|da|dos|das)\b\.?")
SPECIALIST_SKILL: Final[str] = "cadastrar-imovel-no-kenlo"
BASE_TITLE: Final[str] = "Cadastros lidos do Kenlo"
KNOWLEDGE_HIDDEN: Final[re.Pattern[str]] = re.compile(r"corretor|cadastro por|propriet|endere|logradouro|n[uú]mero$|complemento|cep|t[ií]tulo|descri|site|portais|tipofoto|data de|filial|ano de|valor|bairro|taxa de|buscar por|adicionar|classifica|cidade|estado|^(sim|n[aã]o|venda|loca[cç][aã]o|foto de capa|somente .*|venda/loca[cç][aã]o)$", re.IGNORECASE)
SIMILAR_SHARE: Final[float] = 0.6
SUGGESTED_FIELDS: Final[tuple[str, ...]] = ("Padrão", "Padrão da localização", "Posição solar/Face", "Topografia")
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


def _common(records: list[dict[str, Any]], share: float = COMMON_SHARE) -> dict[str, Any]:
    total = len(records)
    values: Counter[tuple[str, str]] = Counter((name, str(value)) for record in records for name, value in record.get("campos", {}).items() if value not in ("", None))
    boxes = Counter(name for record in records for name in record.get("marcados", []))
    best: dict[str, tuple[str, int]] = {}
    for (name, value), count in values.items():
        if count > best.get(name, ("", 0))[1]:
            best[name] = (value, count)
    return {"imoveis": total, "campos": {name: value for name, (value, count) in sorted(best.items()) if count / total >= share},
            "marcados": sorted(name for name, count in boxes.items() if count / total >= share)}


def _plain(text: Any) -> str:
    folded = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(c for c in folded if not unicodedata.combining(c)).lower().strip()


def _place_of(record: dict[str, Any]) -> str:
    place = record.get("lista", {}).get("enterprise") or ""
    return _plain(place.get("name", "") if isinstance(place, dict) else place)


def _same_condominium(name: str, record: dict[str, Any]) -> bool:
    place = _place_of(record)
    return bool(name and place) and (name in place or place in name)


def condominium_fee(condominium: str, bedrooms: Any) -> dict[str, Any]:
    """Valor de condominio mais comum entre os imoveis lidos, com os mesmos dormitorios."""
    wanted = _plain(condominium)
    beds = re.sub(r"\D", "", str(bedrooms or ""))
    close = [item for item in load_all() if _same_condominium(wanted, item) and float(item.get("lista", {}).get("condo_price") or 0) > 1]
    same_beds = [item for item in close if beds and str(item.get("lista", {}).get("beds")) == beds]
    if not same_beds:
        return {"valor": "", "imoveis": 0}
    prices = Counter(float(item["lista"]["condo_price"]) for item in same_beds)
    price, _count = prices.most_common(1)[0]
    return {"valor": f"{price:,.2f}".replace(",", "#").replace(".", ",").replace("#", "."), "imoveis": len(same_beds)}


def suggest(kind: str, purpose: str, neighborhood: str, condominium: str, items: tuple[str, ...]) -> dict[str, Any]:
    """Consulta imoveis parecidos: primeiro o mesmo condominio, depois o mesmo bairro."""
    records = load_all()
    wanted = _plain(condominium)
    close = [item for item in records if _same_condominium(wanted, item)]
    source = f"condomínio {condominium}"
    if len(close) < MIN_SIMILAR:
        area = _plain(neighborhood)
        close = [item for item in records if item.get("tipo") == kind and _plain(item.get("finalidade")) == _plain(purpose) and area and _plain(item.get("lista", {}).get("location_neighborhood")) == area]
        source = f"bairro {neighborhood}"
    if len(close) < MIN_SIMILAR:
        return {"campos": {}, "marcados": [], "fonte": ""}
    common = _common(close, SIMILAR_SHARE)
    fields = {f"{name}:": common["campos"][name] for name in SUGGESTED_FIELDS if common["campos"].get(name) not in (None, "", "Não informado")}
    boxes = [name for name in common["marcados"] if name in items] if wanted and source.startswith("condom") else []
    return {"campos": fields, "marcados": boxes, "fonte": f"{len(close)} imóveis do {source}"}


def _words(text: Any, noise: re.Pattern[str]) -> list[str]:
    return re.findall(r"[a-z0-9]+", noise.sub(" ", _plain(text)))


def _alike(wanted: Any, candidate: Any, noise: re.Pattern[str]) -> bool:
    """Compara palavra por palavra: Passeo Citta acha Club Residencial Paseo Citta / Torre 1."""
    words, others = _words(wanted, noise), _words(candidate, noise)
    if not words or not others:
        return False
    scores = [max(SequenceMatcher(None, word, other).ratio() for other in others) for word in words]
    return min(scores) >= MATCH_WORD and sum(scores) / len(scores) >= MATCH_AVERAGE


def clean_condominium(text: str) -> str:
    """A ficha pode dizer "Sim, Paseo Citta" no campo do condominio."""
    return re.sub(r"^\s*(sim|possui|tem)\b[\s,:.-]*", "", text or "", flags=re.IGNORECASE).strip()


def _address(record: dict[str, Any]) -> dict[str, str]:
    fields = record.get("campos", {})
    place = record.get("lista", {}).get("enterprise") or ""
    name = str(place.get("name", "") if isinstance(place, dict) else place).strip()
    return {"condominio": name if re.search(r"[A-Za-z]", name) else "", "rua": str(fields.get("Endereço") or "").strip(), "numero": str(fields.get("Número") or "").strip(),
            "bairro": str(fields.get("Bairro") or "").strip(), "cidade": str(fields.get("Cidade") or record.get("lista", {}).get("location_city") or "").strip(),
            "cep": re.sub(r"\D", "", str(fields.get("CEP") or "")), "andares": str(fields.get("Nº de andares") or "").strip()}


def _usual(items: list[dict[str, str]], name: str) -> str:
    return next((value for value, _count in Counter(item[name] for item in items if item[name]).most_common(1)), "")


def find_place(street: str, number: str, city: str, condominium: str) -> dict[str, Any]:
    """Procura nos imoveis lidos, aceitando erro de escrita, como o endereco foi cadastrado."""
    places = [_address(record) for record in load_all()]
    named = [item for item in places if condominium and item["condominio"] and _alike(condominium, item["condominio"], NAME_NOISE)]
    road = [item for item in places if street and item["rua"] and _alike(street, item["rua"], STREET_NOISE) and (not city or _plain(city) == _plain(item["cidade"]))]
    same_door = [item for item in road if number and item["numero"] == number]
    found = [item for item in named if item in road] or named or same_door or road
    if not found:
        return {}
    building = named or same_door
    with_name = [item for item in building if item["condominio"]]
    name = _usual(with_name, "condominio").split("/")[0].strip()
    floors = Counter(item["andares"] for item in with_name if item["andares"]).most_common(1)
    steady = bool(floors and floors[0][1] >= STANDARD_SHARE * len(with_name))
    return {"condominio": name, "rua": _usual(found, "rua"), "numero": _usual(found, "numero") if named else "", "bairro": _usual(found, "bairro"), "cidade": _usual(found, "cidade"),
            "cep": _usual(found, "cep"), "andares": floors[0][0] if steady else "", "imoveis": len(found)}


def usual_count(kind: str, condominium: str, street: str, number: str, city: str, field: str) -> dict[str, Any]:
    """Quantidade mais comum em imoveis do mesmo tipo no mesmo predio ou condominio."""
    key = COUNT_FIELDS.get(field)
    empty = {"valor": "", "iguais": 0, "imoveis": 0}
    if not key:
        return empty
    values = []
    for record in load_all():
        place = _address(record)
        inside = bool(condominium and place["condominio"]) and _alike(condominium, place["condominio"], NAME_NOISE)
        door = bool(number) and place["numero"] == number and _alike(street, place["rua"], STREET_NOISE) and (not city or _plain(city) == _plain(place["cidade"]))
        if record.get("tipo") == kind and (inside or door) and record.get("lista", {}).get(key):
            values.append(str(record["lista"][key]))
    if not values:
        return empty
    value, same = Counter(values).most_common(1)[0]
    return {"valor": value, "iguais": same, "imoveis": len(values)} if same >= STANDARD_SHARE * len(values) else empty


def web_place(street: str, number: str, city: str, chat: Any, search: Any) -> str:
    """Ultimo recurso: procura so o endereco na internet, sem nenhum dado do proprietario."""
    try:
        results = search(f'condomínio edifício "{street}" {number} {city}')
        reply = chat("Estes sao resultados de busca sobre um endereco. Responda so um JSON "
                     f'{{"condominio": "", "confianca": 0.0}} com o nome do condominio ou edificio em {street}, {number}, {city}. '
                     f"Use somente os resultados. Sem certeza, deixe vazio.\n{json.dumps(results, ensure_ascii=False)[:5000]}", 60.0, 300)
        found = json.loads(re.search(r"\{.*\}", reply, re.DOTALL).group(0))
    except Exception:
        return ""
    return str(found.get("condominio") or "").strip() if float(found.get("confianca") or 0) >= WEB_CONFIDENCE else ""


def _money(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "#").replace(".", ",").replace("#", ".")


def _middle(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def _prices(records: list[dict[str, Any]], field: str, label: str) -> str:
    values = [float(item.get("lista", {}).get(field) or 0) for item in records]
    values = [value for value in values if value > 1]
    return f"{label}: de {_money(min(values))} a {_money(max(values))}, valor do meio {_money(_middle(values))} ({len(values)} imóveis)." if values else ""


def _boxes(common: dict[str, Any]) -> str:
    return ", ".join(box for box in common["marcados"] if not KNOWLEDGE_HIDDEN.search(box)) or "nenhum em comum"


def knowledge_chunks(records: list[dict[str, Any]], today: str) -> list[str]:
    """Texto que o especialista consulta: resumos, sem proprietarios nem cadastros individuais."""
    pieces = []
    groups: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        groups.setdefault(f"{record.get('tipo', '')} {record.get('finalidade', '')}", []).append(record)
    for name, items in sorted(groups.items()):
        common = _common(items, 0.6)
        fields = "; ".join(f"{key}: {value}" for key, value in common["campos"].items() if not KNOWLEDGE_HIDDEN.search(key))
        lines = [f"Cadastros de {name}: {len(items)} imóveis lidos em {today}.", _prices(items, "sale_price", "Venda"), _prices(items, "rent_price", "Locação"),
                 f"Campos mais usados: {fields}.", f"Itens mais marcados: {_boxes(common)}."]
        pieces.append(" ".join(line for line in lines if line))
    condos: dict[str, list[dict[str, Any]]] = {}
    places: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        info = record.get("lista", {})
        place = info.get("enterprise") or ""
        name = str(place.get("name", "") if isinstance(place, dict) else place).strip()
        if re.search(r"\w", name):
            condos.setdefault(name, []).append(record)
        area = str(info.get("location_neighborhood") or "").strip()
        if area:
            places.setdefault(f"{record.get('tipo', '')} no bairro {area}, {info.get('location_city') or ''}", []).append(record)
    for name, items in sorted(condos.items()):
        info = items[0].get("lista", {})
        beds: dict[str, list[float]] = {}
        for item in items:
            price = float(item.get("lista", {}).get("condo_price") or 0)
            if price > 1:
                beds.setdefault(str(item.get("lista", {}).get("beds") or "?"), []).append(price)
        fees = "; ".join(f"{bed} dormitórios: condomínio mais comum {_money(Counter(values).most_common(1)[0][0])} ({len(values)} imóveis)" for bed, values in sorted(beds.items()))
        common = _common(items, 0.6)
        rooms = Counter((str(item.get("tipo")), str(item.get("lista", {}).get("bathrooms"))) for item in items if item.get("lista", {}).get("bathrooms"))
        baths = "; ".join(f"{kind}: {amount} banheiro(s) em {total} imóveis" for (kind, amount), total in sorted(rooms.items()))
        lines = [f"Condomínio {name}, bairro {info.get('location_neighborhood') or ''}, {info.get('location_city') or ''}: {len(items)} imóveis lidos em {today}.",
                 fees, baths, _prices(items, "municipal_property_tax", "IPTU"), f"Itens comuns: {_boxes(common)}."]
        pieces.append(" ".join(line for line in lines if line))
    for name, items in sorted(places.items()):
        lines = [f"Imóveis {name}: {len(items)} lidos em {today}.", _prices(items, "sale_price", "Venda"), _prices(items, "rent_price", "Locação"), _prices(items, "municipal_property_tax", "IPTU")]
        pieces.append(" ".join(line for line in lines if line))
    return pieces


def teach_specialist(today: str = "") -> int:
    """Coloca a base lida na memoria do especialista de cadastro no Kenlo."""
    from dodaios.core import knowledge
    from dodaios.core.paths import user_data_dir

    pieces = knowledge_chunks(load_all(), today or datetime.now().strftime("%d/%m/%Y"))
    total = 0
    for target in (user_data_dir() / "data" / "company_knowledge").glob(f"*/{SPECIALIST_SKILL}*"):
        total += knowledge.add_own(target.parent.name, target.name, BASE_TITLE, pieces)
    return total


def summarize() -> dict[str, Any]:
    records = load_all()
    # Padroes de cadastro vem dos ativos; os demais servem de consulta.
    active = [item for item in records if _plain(item.get("lista", {}).get("status") or "ativo") == "ativo"]
    groups = sorted({(item.get("finalidade", ""), item.get("tipo", "")) for item in active})
    types = {f"{purpose}-{kind}-{goal}": _common(items) for purpose, kind in groups for goal in ("venda", "locacao")
             if len(items := [item for item in active if item.get("tipo") == kind and item.get("finalidade", "") == purpose and item.get(goal)]) >= MIN_RECORDS}
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
