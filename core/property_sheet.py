"""Le a ficha de texto de um imovel e devolve os dados separados.

So extrai o que esta escrito. Campo ausente fica vazio, para quem usar a ficha
decidir o padrao ou perguntar, nunca para inventar.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Final

_MONEY: Final[str] = r"(\d{1,3}(?:\.\d{3})+(?:,\d{2})?|\d+(?:,\d{2})?)"
_PHONE = re.compile(r"\(?\b(\d{2})\)?\s*(\d{4,5})[-‐-―\s]?(\d{4})\b")
_STREET = re.compile(r"\b(avenida|av\.?|rua|r\.|estrada|rodovia|rod\.?|travessa|alameda)\s", re.IGNORECASE)
_NUMBER = re.compile(r"^(.*?)[,\s]+(?:n[ºo°.]*\s*)?(\d{1,6})\b", re.IGNORECASE)
_BULLET = re.compile(r"^[\s•·*\-–—▪️✅]+")
_COUNTS: Final[dict[str, str]] = {
    "docas": r"docas?",
    "rampas": r"rampas?",
    "banheiros": r"banheiros?",
    "vagas": r"vagas?",
    "dormitorios": r"(?:dormitorios?|quartos?)",
    "suites": r"suites?",
    "andares": r"(?:andares|andar|pavimentos?)",
}


_FLOORS: Final[dict[str, str]] = {"Porcelanato": "porcelanato", "Cerâmica": "ceramica", "Laminado": "laminado", "Vinílico": "vinilico", "Mármore": "marmore", "Bloquete": "bloquete", "Ardósia": "ardosia", "Contrapiso": "contrapiso", "Tábua": "tabua", "Granito": "granito",
                                  "Carpete": "carpete", "Cimento queimado": "cimento queimado", "Taco de madeira": "taco", "Piso frio": "piso frio"}


def _fold(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in plain if not unicodedata.combining(c)).lower()


def _clean(line: str) -> str:
    return _BULLET.sub("", line).strip()


def _money(folded: str, words: str) -> str:
    found = re.search(rf"\b(?:{words})\b[^\d\n]{{0,20}}{_MONEY}", folded)
    if not found:
        return ""
    value = found.group(1)
    return value if "," in value else f"{value},00"


def _area(folded: str, words: str) -> str:
    found = re.search(rf"(\d[\d.,]*)\s*m(?:2|²)\s*(?:de\s+)?(?:{words})", folded)
    return found.group(1).rstrip(".,") if found else ""


def _labeled(lines: list[str], names: str) -> str:
    """Valor de uma linha 'Rotulo: valor' da ficha."""
    for line in lines:
        found = re.match(rf"(?:{names})\s*:\s*(.+)$", _fold(_clean(line)))
        if found:
            return _clean(line)[found.start(1):].strip()
    return ""


def _labeled_area(folded: str, names: str) -> str:
    found = re.search(rf"\b(?:{names})[^\d\n]{{0,16}}(\d[\d.,]*)\s*m", folded)
    return found.group(1).rstrip(".,") if found else ""


def _place(lines: list[str]) -> tuple[str, str]:
    """Bairro e cidade: rotulos, a linha do alfinete, ou a primeira com virgula."""
    labeled = _labeled(lines, "bairr?o|bairo"), _labeled(lines, "cidade")
    if labeled[1]:
        return labeled
    for line in lines:
        if "\U0001F4CD" in line:
            parts = [part.strip() for part in re.sub(r"\U0001F4CD|️", "", line).split(",") if part.strip()]
            if len(parts) >= 2:
                return parts[0], parts[1]
            return "", parts[0] if parts else ""
    # O alfinete e uma imagem no WhatsApp Web e pode nao vir no texto.
    for line in lines:
        text = _clean(line)
        parts = [part.strip() for part in text.split(",") if part.strip()]
        plain = _fold(text)
        if len(parts) == 2 and not _STREET.match(text) and not re.search(r"\d|codigo|proprietari", plain):
            return parts[0], parts[1]
    return "", ""


def _address(lines: list[str]) -> tuple[str, str]:
    for line in lines:
        text = re.sub(r"^endere[cç]o\s*:\s*", "", _clean(line), flags=re.IGNORECASE)
        if _STREET.match(text):
            found = _NUMBER.match(text)
            return (found.group(1).strip(), found.group(2)) if found else (text, "")
    return "", ""


def _owner(lines: list[str]) -> tuple[str, str]:
    for index, line in enumerate(lines):
        if not re.match(r"propriet[aá]ri[oa]\b", _clean(line), re.IGNORECASE):
            continue
        rest = re.sub(r"^propriet[aá]ri[oa]\s*:?\s*", "", _clean(line), flags=re.IGNORECASE)
        text = " ".join(part for part in [rest, *lines[index + 1:index + 3]] if part.strip())
        phone = _PHONE.search(text)
        name = text[: phone.start()] if phone else text
        number = f"({phone.group(1)}) {phone.group(2)}-{phone.group(3)}" if phone else ""
        return re.sub(r"[\s\-–—:(]+$", "", name).strip(), number
    return "", ""


def parse_sheet(text: str) -> dict[str, Any]:
    """Campos da ficha; o que nao estiver escrito volta vazio."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    folded = _fold(text)
    neighborhood, city = _place(lines)
    street, number = _address(lines)
    owner, phone = _owner(lines)
    code = re.search(r"\b(?:codigo|cod|referencia|ref)\b\s*[:#.\-]?\s*([a-z0-9-]*\d[a-z0-9-]*)", folded)
    apartment = re.search(r"\b(?:apto\.?|ap\.|apartamento\s+n[ºo°.]*)\s*(?:n[ºo°.]*\s*)?(\d{1,5})\b", folded)
    lot = re.search(r"\blote\s*:?\s*([a-z0-9-]+)", folded)
    block = re.search(r"\bquadra\s*:?\s*([a-z0-9-]+)", folded)
    built = _area(folded, "area util|util|privativ[ao]|construid[ao]|area construida") or _labeled_area(folded, "area (?:util|construida|privativa)")
    condo = _labeled(lines, "condominio")
    covered = re.search(r"\b(\d{1,3})\s+vagas?\s+cobertas?\b", folded)
    open_air = re.search(r"\b(\d{1,3})\s+vagas?\s+descobertas?\b", folded)
    counts = {}
    for field, pattern in _COUNTS.items():
        # A ficha escreve "Qnt suites: 1" ou "1 suite".
        found = re.search(rf"\b(?:qnt|qtd|quantidade)\b[ .]*(?:de\s+)?{pattern}\s*:?\s*(\d{{1,3}})\b", folded) or re.search(rf"\b(\d{{1,3}})\s+{pattern}\b", folded)
        counts[field] = found.group(1) if found else ""
    return {
        "codigo": code.group(1) if code else "",
        "condominio_nome": "" if re.search(r"\d|r\$", _fold(condo)) or re.fullmatch(r"(nao|nenhum|sem|nao tem|n/?a|-+)\.?", _fold(condo).strip()) else condo,
        "pisos": sorted({name for line in folded.splitlines() if "piso" in line or "porcelanato" in line or "laminado" in line or "vinilico" in line
                         for name, word in _FLOORS.items() if word in line}),
        "andar": (re.search(r"\b(\d{1,3})\s*[ºo°]?\s*andar\b", folded) or [None, ""])[1],
        "observacao": " ".join(line.strip("() ") for line in lines if re.fullmatch(r"\(.+\)", line.strip())),
        "vagas_cobertas": covered.group(1) if covered else "",
        "vagas_descobertas": open_air.group(1) if open_air else "",
        "bairro": neighborhood,
        "cidade": city,
        "logradouro": street,
        "numero": number,
        "apartamento": apartment.group(1) if apartment else "",
        "lote": lot.group(1) if lot else "",
        "quadra": block.group(1) if block else "",
        "area_construida": built,
        "area_terreno": _area(folded, "de terreno|terreno|area total|total") or _labeled_area(folded, "area (?:do )?terreno|area total"),
        **counts,
        "locacao": _money(folded, "locacao|aluguel"),
        "venda": _money(folded, "venda|valor de venda"),
        "iptu": _money(folded, "iptu"),
        "condominio_valor": _money(folded, "condominio"),
        "ano_construcao": (re.search(r"\b(?:ano de construcao|construid[oa] em|construcao)\D{0,12}((?:19|20)\d{2})\b", folded) or [None, ""])[1],
        "pe_direito": (re.search(r"(?:pe[\s-]*direito)[^\d\n]{0,12}(\d+(?:,\d+)?)", folded) or [None, ""])[1],
        "mobiliado": bool(re.search(r"\b(mobiliad[oa]|semi[\s-]?mobiliad[oa])\b", folded)) and "sem mobilia" not in folded,
        "proprietario": owner,
        "telefone": phone,
    }
