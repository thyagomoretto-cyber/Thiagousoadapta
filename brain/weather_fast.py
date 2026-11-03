"""Resposta direta para perguntas de clima em portugues, sem passar pelo modelo.

Consulta o Open-Meteo e responde em uma frase. Qualquer duvida ou falha devolve
``None``, e a pergunta segue o caminho normal do brain.
"""
from __future__ import annotations

import asyncio
import re
import unicodedata
from typing import Any

_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_TIMEOUT_S = 3.0

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
_ALIASES = {"gravatem": "Gravatai", "gravatai rs": "Gravatai"}

_CONDITIONS = {
    0: "céu limpo", 1: "céu quase limpo", 2: "parcialmente nublado", 3: "nublado",
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
    return re.sub(r"\s+", " ", folded.lower().strip(" \t\n?!.,;:"))


def match_weather_question(text: str) -> tuple[str, bool] | None:
    """Devolve ``(lugar, amanha)`` quando o texto e claramente sobre clima."""
    normalized = _normalize(text)
    if not normalized or len(normalized.split()) > 12 or _REJECT_RE.search(normalized):
        return None
    if not _TOPIC_RE.search(normalized):
        return None
    match = _PLACE_RE.search(normalized)
    if match is None:
        return None
    place = match.group(1).strip()
    if place in _NOT_PLACE or _TOPIC_RE.search(place):
        return None
    return _ALIASES.get(place, place), "amanha" in normalized


async def _lookup(client: Any, place: str) -> dict[str, Any] | None:
    for extra in ({"countryCode": "BR"}, {}):
        response = await client.get(
            _GEOCODE_URL,
            params={"name": place, "count": 5, "language": "pt", "format": "json", **extra},
        )
        results = (response.json() or {}).get("results") or []
        if results:
            return max(results, key=lambda item: item.get("population") or 0)
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

    async def ask(http: Any) -> str | None:
        city = await _lookup(http, place)
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
        return _sentence(city, response.json() or {}, tomorrow)

    try:
        async with asyncio.timeout(_TIMEOUT_S):
            if client is not None:
                return await ask(client)
            import httpx

            async with httpx.AsyncClient(timeout=_TIMEOUT_S / 2) as http:
                return await ask(http)
    except Exception:  # noqa: BLE001 - em qualquer falha a pergunta segue para o brain
        return None
