"""Resposta direta para perguntas de clima em portugues, sem passar pelo modelo.

Consulta o Open-Meteo e responde em uma frase. Qualquer duvida ou falha devolve
``None``, e a pergunta segue o caminho normal do brain.
"""
from __future__ import annotations

import asyncio
import difflib
import re
import time
import unicodedata
from typing import Any

_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_TIMEOUT_S = 3.0
_FOLLOWUP_S = 180.0
_HOME_STATE = "Rio Grande do Sul"
_last_answer_at = 0.0
_last_asked_at = 0.0
_last_place = ""

_TOPIC_RE = re.compile(
    r"\b(temperatura|clima|previsao(?: do tempo)?|quantos graus|o tempo|tempo|"
    r"vai chover|esta chovendo|ta chovendo|chove)\b"
)
_REJECT_RE = re.compile(
    r"\b(quanto tempo|(?<!do )tempo (?:de|que|para|pra)\b|ao mesmo tempo|"
    r"mudanca|historia|por que|porque|pesquis\w*|site|noticia\w*|graus de)\b"
)
_PLACE_RE = re.compile(
    r"\b(?:em|no|na|para|pra)\s+([a-z][a-z' -]{2,40}?)"
    r"(?:\s+(?:hoje|agora|amanha|nesse momento|neste momento))?$"
)
_NOT_PLACE = {"casa", "minha casa", "minha cidade", "aqui", "ai", "la", "geral"}
_ALIASES = {"gravatem": "Gravatai"}
# Cidades proximas, para quando a voz erra uma letra ("cachorinha") e o Open-Meteo
# nao encontra nada. So entram depois que a busca normal falhou.
_REGION_CITIES = (
    "Cachoeirinha", "Gravatai", "Porto Alegre", "Canoas", "Alvorada", "Viamao",
    "Esteio", "Sapucaia do Sul", "Sao Leopoldo", "Novo Hamburgo", "Guaiba",
    "Glorinha", "Eldorado do Sul", "Canela", "Gramado", "Taquara", "Caxias do Sul",
)
_CORRECTION_RE = re.compile(r"^(?:nao|errado|na verdade)\b.*\be (?:em |no |na )?([a-z' -]{3,40})$")
_NOT_FOLLOWUP = {
    "ok", "obrigado", "obrigada", "valeu", "sim", "nao", "legal", "certo", "beleza",
    "qual", "como", "quando", "onde", "porque", "quero", "faz", "abre", "abra",
    "voce", "tu", "ele", "ela", "isso", "aquilo", "mais", "nada", "pronto", "bom",
    "tudo", "oi", "ola", "tchau",
}
_STATES = {
    "acre": "Acre", "ac": "Acre", "alagoas": "Alagoas", "al": "Alagoas",
    "amapa": "Amapá", "ap": "Amapá", "amazonas": "Amazonas", "am": "Amazonas",
    "bahia": "Bahia", "ba": "Bahia", "ceara": "Ceará", "ce": "Ceará",
    "distrito federal": "Distrito Federal", "df": "Distrito Federal",
    "espirito santo": "Espírito Santo", "es": "Espírito Santo",
    "goias": "Goiás", "go": "Goiás", "maranhao": "Maranhão", "ma": "Maranhão",
    "mato grosso do sul": "Mato Grosso do Sul", "ms": "Mato Grosso do Sul",
    "mato grosso": "Mato Grosso", "mt": "Mato Grosso",
    "minas gerais": "Minas Gerais", "mg": "Minas Gerais",
    "para": "Pará", "pa": "Pará", "paraiba": "Paraíba", "pb": "Paraíba",
    "parana": "Paraná", "pr": "Paraná", "pernambuco": "Pernambuco", "pe": "Pernambuco",
    "piaui": "Piauí", "pi": "Piauí", "rio de janeiro": "Rio de Janeiro", "rj": "Rio de Janeiro",
    "rio grande do norte": "Rio Grande do Norte", "rn": "Rio Grande do Norte",
    "rio grande do sul": "Rio Grande do Sul", "rs": "Rio Grande do Sul",
    "rondonia": "Rondônia", "ro": "Rondônia", "roraima": "Roraima", "rr": "Roraima",
    "santa catarina": "Santa Catarina", "sc": "Santa Catarina",
    "sao paulo": "São Paulo", "sp": "São Paulo", "sergipe": "Sergipe", "se": "Sergipe",
    "tocantins": "Tocantins", "to": "Tocantins",
}

_CONDITIONS = {
    0: "céu limpo", 1: "céu quase limpo", 2: "céu parcialmente nublado", 3: "céu nublado",
    45: "neblina", 48: "neblina", 51: "garoa fraca", 53: "garoa", 55: "garoa forte",
    56: "garoa congelante", 57: "garoa congelante", 61: "chuva fraca", 63: "chuva",
    65: "chuva forte", 66: "chuva congelante", 67: "chuva congelante",
    71: "neve fraca", 73: "neve", 75: "neve forte", 77: "neve",
    80: "pancadas de chuva", 81: "pancadas de chuva", 82: "pancadas fortes de chuva",
    85: "pancadas de neve", 86: "pancadas de neve", 95: "trovoada",
    96: "trovoada com granizo", 99: "trovoada com granizo",
}


def _normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text or "")
    folded = "".join(char for char in folded if not unicodedata.combining(char))
    folded = re.sub(r"[,;/]", " ", folded)
    return re.sub(r"\s+", " ", folded.lower().strip(" \t\n?!.:"))


def _split_state(place: str) -> tuple[str, str | None]:
    """Separa ``cachoeirinha rs`` em cidade e estado."""
    for name in sorted(_STATES, key=len, reverse=True):
        if place.endswith(f" {name}"):
            city = place[: -len(name)].strip()
            if city.endswith(" do") or city.endswith(" de"):
                continue
            return city, _STATES[name]
    return place, None


def _match_followup(normalized: str) -> tuple[str, bool] | None:
    """Aceita so o nome do lugar logo depois de uma pergunta de clima."""
    if time.monotonic() - max(_last_answer_at, _last_asked_at) > _FOLLOWUP_S:
        return None
    normalized = re.sub(r"\s+", " ", normalized.replace(".", " ")).strip()
    correction = _CORRECTION_RE.search(normalized)
    if correction is not None:
        place = correction.group(1).strip()
        return None if set(place.split()) & _NOT_FOLLOWUP else (place, False)
    words = normalized.split()
    if not 1 <= len(words) <= 7 or not re.fullmatch(r"[a-z' -]+", normalized):
        return None
    if words[0] in ("e", "agora", "tambem"):
        words = words[1:]
    if words and words[0] in ("em", "no", "na", "para", "pra"):
        words = words[1:]
    if words in (["amanha"], ["hoje"]) and _last_place:
        return _last_place, words == ["amanha"]
    if not words or set(words) & _NOT_FOLLOWUP:
        return None
    return " ".join(words), False


def match_weather_question(text: str) -> tuple[str, bool] | None:
    """Devolve ``(lugar, amanha)`` quando o texto e claramente sobre clima."""
    normalized = _normalize(text)
    if not normalized or len(normalized.split()) > 12 or _REJECT_RE.search(normalized):
        return None
    if not _TOPIC_RE.search(normalized):
        return _match_followup(normalized)
    match = _PLACE_RE.search(normalized)
    if match is None:
        return None
    place = match.group(1).strip()
    if place in _NOT_PLACE or _TOPIC_RE.search(place):
        return None
    return _ALIASES.get(place, place), "amanha" in normalized


def _pick(
    results: list[dict[str, Any]], city: str, state: str | None, strict: bool
) -> dict[str, Any] | None:
    exact = [item for item in results if _normalize(item.get("name") or "") == _normalize(city)]
    if strict and not exact:
        return None
    options = exact or results
    if state:
        same_state = [item for item in options if item.get("admin1") == state]
        if not same_state:
            return None
        options = same_state
    else:
        home = [item for item in options if item.get("admin1") == _HOME_STATE]
        options = home or options
    return max(options, key=lambda item: item.get("population") or 0)


async def _lookup(client: Any, place: str, strict: bool) -> dict[str, Any] | None:
    city, state = _split_state(place)
    for extra in ({"countryCode": "BR"}, {}):
        response = await client.get(
            _GEOCODE_URL,
            params={"name": city, "count": 10, "language": "pt", "format": "json", **extra},
        )
        results = (response.json() or {}).get("results") or []
        chosen = _pick(results, city, state, strict) if results else None
        if chosen is not None:
            return chosen
    close = difflib.get_close_matches(_normalize(city), [_normalize(c) for c in _REGION_CITIES], n=1, cutoff=0.8)
    if close and close[0] != _normalize(city):
        return await _lookup(client, close[0], strict)
    return None


def _number(value: Any) -> int | None:
    return None if value is None else int(round(float(value)))


def _sentence(city: dict[str, Any], forecast: dict[str, Any], tomorrow: bool) -> str | None:
    name = city.get("name") or ""
    region = city.get("admin1") or city.get("country") or ""
    where = f"{name}, {region}" if region else name
    daily = forecast.get("daily") or {}
    index = 1 if tomorrow else 0
    try:
        low = _number(daily["temperature_2m_min"][index])
        high = _number(daily["temperature_2m_max"][index])
        rain = _number(daily["precipitation_probability_max"][index])
        day_code = daily["weather_code"][index]
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    rain_text = f", com {rain}% de chance de chuva" if rain is not None else ""
    if tomorrow:
        condition = _CONDITIONS.get(day_code, "tempo variável")
        return f"Amanhã em {where}: {condition}, mínima de {low} e máxima de {high} graus{rain_text}."
    current = forecast.get("current") or {}
    now = _number(current.get("temperature_2m"))
    if now is None:
        return None
    condition = _CONDITIONS.get(current.get("weather_code"), "tempo variável")
    return (
        f"Agora em {where} faz {now} graus, com {condition}. "
        f"Hoje a mínima é {low} e a máxima {high}{rain_text}."
    )


async def answer_weather_question(text: str, client: Any | None = None) -> str | None:
    matched = match_weather_question(text)
    if matched is None:
        return None
    place, tomorrow = matched
    strict = _TOPIC_RE.search(_normalize(text)) is None
    if not strict:
        global _last_asked_at
        _last_asked_at = time.monotonic()

    async def ask(http: Any) -> str | None:
        city = await _lookup(http, place, strict)
        if city is None:
            return None
        response = await http.get(
            _FORECAST_URL,
            params={
                "latitude": city["latitude"],
                "longitude": city["longitude"],
                "current": "temperature_2m,weather_code",
                "daily": (
                    "weather_code,temperature_2m_max,temperature_2m_min,"
                    "precipitation_probability_max"
                ),
                "forecast_days": 2,
                "timezone": "auto",
            },
        )
        reply = _sentence(city, response.json() or {}, tomorrow)
        if reply is not None:
            global _last_answer_at, _last_place
            _last_answer_at = time.monotonic()
            _last_place = place
        return reply

    try:
        async with asyncio.timeout(_TIMEOUT_S):
            if client is not None:
                return await ask(client)
            import httpx

            async with httpx.AsyncClient(timeout=_TIMEOUT_S / 2) as http:
                return await ask(http)
    except Exception:  # noqa: BLE001 - em qualquer falha a pergunta segue para o brain
        return None
