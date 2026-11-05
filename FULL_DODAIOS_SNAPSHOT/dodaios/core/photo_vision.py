"""Descobre o ambiente de cada foto, sempre processando dentro de casa.

Ordem de preferencia: correcao do dono, foto ja conhecida, modelo com visao do
servidor local, etiquetas do proprio macOS e, por ultimo, um palpite marcado
como duvida. A foto nunca sai para um servico externo.
"""
from __future__ import annotations

import base64
import io
import json
import re
from pathlib import Path
from typing import Any, Final

from dodaios.core import photo_order as order

VISION_TIMEOUT_S: Final[float] = 240.0
AD_TIMEOUT_S: Final[float] = 120.0
CONNECT_TIMEOUT_S: Final[float] = 5.0
SCREEN_TIMEOUT_S: Final[float] = 90.0
DETAIL_PHOTOS: Final[int] = 10
DETAIL_CONFIDENCE: Final[float] = 0.7
OUTDOOR_SKY: Final[float] = 0.2
# O modelo gasta tokens pensando antes de responder.
THINKING_TOKENS: Final[int] = 4000
LONGEST_SIDE: Final[int] = 768
_LABELS: Final[tuple[tuple[str, str], ...]] = (
    ("swimming_pool", "piscina"), ("pool", "piscina"), ("kitchen", "cozinha"), ("bathroom", "banheiro"), ("toilet", "banheiro"),
    ("sink", "banheiro"), ("bedroom", "dormitorio"), ("bed", "dormitorio"), ("living_room", "sala_estar"), ("sofa", "sala_estar"),
    ("couch", "sala_estar"), ("dining", "sala_jantar"), ("office", "escritorio"), ("desk", "escritorio"), ("garage", "garagem"),
    ("balcony", "sacada"), ("laundry", "lavanderia"), ("washer", "lavanderia"), ("barbecue", "churrasqueira"), ("grill", "churrasqueira"),
    ("gym", "academia"), ("playground", "playground"), ("garden", "jardim"), ("warehouse", "panoramica_interna"),
    ("hangar", "panoramica_interna"), ("building", "fachada"), ("house", "fachada"), ("structure", "fachada"), ("land", "panoramica"),
    ("grass", "panoramica"),
)


class ModelDown(Exception):
    """O servidor local nao respondeu."""


problems: list[str] = []


def _endpoint() -> tuple[str, str]:
    """Servidor e modelo locais do proprio DodaiOS; vazio se nao houver."""
    try:
        import tomllib

        from dodaios.core.config import resolve_config_path

        local = tomllib.loads(resolve_config_path().read_text(errors="replace"))["brain"]["providers"]["local-openai"]
        base = str(local["base_url"]).rstrip("/")
        return (base if base.endswith("/v1") else f"{base}/v1"), str(local.get("model") or "")
    except (OSError, KeyError, ValueError):
        return "", ""


def model_ready() -> bool:
    """O modelo de imagens esta ligado e responde?"""
    import httpx

    base, _ = _endpoint()
    if not base:
        return False
    try:
        with httpx.Client(timeout=httpx.Timeout(10.0, connect=CONNECT_TIMEOUT_S), trust_env=False) as client:
            return client.get(f"{base}/models").status_code == 200
    except httpx.HTTPError:
        return False


def _chat(content: Any, timeout: float, tokens: int) -> str:
    import httpx

    base, model = _endpoint()
    if not base:
        raise RuntimeError("Sem servidor local")
    body = {"model": model, "temperature": 0, "max_tokens": tokens, "messages": [{"role": "user", "content": content}]}
    with httpx.Client(timeout=httpx.Timeout(timeout, connect=CONNECT_TIMEOUT_S), trust_env=False) as client:
        # Sem o raciocinio a resposta sai mais rapido; nem todo servidor aceita a opcao.
        reply = client.post(f"{base}/chat/completions", json={**body, "reasoning_effort": "none"})
        if reply.status_code in (400, 422):
            reply = client.post(f"{base}/chat/completions", json=body)
    reply.raise_for_status()
    return str(reply.json()["choices"][0]["message"]["content"])


def _small_jpeg(path: Path) -> str:
    from PIL import Image

    with Image.open(path) as image:
        small = image.convert("RGB")
    small.thumbnail((LONGEST_SIDE, LONGEST_SIDE))
    buffer = io.BytesIO()
    small.save(buffer, "JPEG", quality=80)
    return base64.b64encode(buffer.getvalue()).decode()


def ask_vision(path: Path, kind: str) -> dict[str, Any] | None:
    """Pergunta ao modelo local; resposta invalida devolve None e fica em ``problems``."""
    rooms = order.vocabulary(kind)
    prompt = (f"Foto de um imovel do tipo {kind.replace('_', ' ')}. Responda so um JSON: "
              f'{{"ambiente": "...", "confianca": 0.0, "ampla": true}}. ambiente precisa ser exatamente um destes: {", ".join(rooms)}. '
              "ampla e true se a foto mostra o ambiente inteiro. Se nao tiver certeza, baixe a confianca. Nao invente.")
    try:
        text = _chat([{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{_small_jpeg(path)}"}}], VISION_TIMEOUT_S, THINKING_TOKENS)
    except Exception as exc:
        problems.append(f"{path.name}: modelo sem resposta ({type(exc).__name__})")
        raise ModelDown from exc
    try:
        found = json.loads(re.search(r"\{.*\}", text, re.DOTALL).group(0))
    except (AttributeError, ValueError):
        problems.append(f"{path.name}: resposta sem JSON: {text[:80]!r}")
        return None
    if found.get("ambiente") not in rooms:
        problems.append(f"{path.name}: ambiente fora da lista: {str(found.get('ambiente'))[:40]}")
        return None
    return {"ambiente": found["ambiente"], "confianca": float(found.get("confianca") or 0), "ampla": bool(found.get("ampla")), "fonte": "modelo"}


def apple_labels(path: Path) -> list[tuple[str, float]]:
    """Etiquetas do Vision do macOS; vazio fora do Mac."""
    try:
        import Vision
        from Foundation import NSURL

        request = Vision.VNClassifyImageRequest.alloc().init()
        handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(NSURL.fileURLWithPath_(str(path)), {})
        handler.performRequests_error_([request], None)
        return [(str(item.identifier()), float(item.confidence())) for item in (request.results() or []) if item.confidence() > 0.1]
    except Exception:
        return []


def from_labels(labels: list[tuple[str, float]], kind: str, sky: float) -> dict[str, Any]:
    """Traduz etiquetas gerais. E resultado fraco e por isso pede conferencia."""
    rooms = order.vocabulary(kind)
    for label, confidence in sorted(labels, key=lambda item: -item[1]):
        for word, room in _LABELS:
            # Etiquetas como "structure" aparecem em fotos internas: sem ceu, nao e fachada.
            if word in label.lower() and room in rooms and (room != "fachada" or sky > OUTDOOR_SKY):
                return {"ambiente": room, "confianca": min(confidence, 0.7), "ampla": False, "fonte": "macos"}
    if sky > OUTDOOR_SKY and rooms[0] in ("fachada", "vista_frontal"):
        return {"ambiente": rooms[0], "confianca": 0.5, "ampla": True, "fonte": "palpite"}
    inside = next((room for room in ("panoramica_interna", "salao_geral", "vista_geral", "sala_estar") if room in rooms), "demais")
    return {"ambiente": inside, "confianca": 0.3, "ampla": False, "fonte": "palpite"}


def detect_details(paths: list[Path]) -> dict[str, list[str]]:
    """Piso e itens que aparecem claramente nas fotos; vazio se o modelo nao responder."""
    if not paths:
        return {"piso": [], "itens": []}
    prompt = ("Estas sao fotos de um imovel para anuncio. Olhe com atencao o chao e os ambientes. Responda so um JSON: "
              '{"piso": [{"nome": "...", "confianca": 0.0}], "itens": [{"nome": "...", "confianca": 0.0}], "contagens": {"dormitorios": 0, "suites": 0, "vagas": 0, "banheiros": 0}}. '
              f"Nomes de piso permitidos: {', '.join(order.FLOORS)}. Nomes de itens permitidos: {', '.join(order.VISIBLE_ITEMS)}. "
              "Em contagens, conte so ambientes diferentes que aparecem nas fotos, sem repetir o mesmo ambiente; sem certeza, use 0. "
              "Veja o piso de cada ambiente: um imovel pode ter mais de um, como porcelanato na sala e vinilico nos quartos; liste todos. "
              "Liste so o que aparece claramente nas fotos. Se nao tiver certeza, baixe a confianca. Nao invente.")
    images = [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{_small_jpeg(path)}"}} for path in paths[:DETAIL_PHOTOS]]
    try:
        found = json.loads(re.search(r"\{.*\}", _chat([{"type": "text", "text": prompt}, *images], VISION_TIMEOUT_S, THINKING_TOKENS), re.DOTALL).group(0))
    except Exception as exc:
        problems.append(f"Detalhes das fotos: modelo sem resposta ({type(exc).__name__})")
        return {"piso": [], "itens": []}
    sure = lambda items, allowed: [str(item["nome"]) for item in items if isinstance(item, dict) and item.get("nome") in allowed and float(item.get("confianca", 0)) >= DETAIL_CONFIDENCE]
    counts = found.get("contagens") if isinstance(found.get("contagens"), dict) else {}
    return {"piso": sure(found.get("piso", []), order.FLOORS), "itens": sure(found.get("itens", []), order.VISIBLE_ITEMS), "contagens": counts}


def screen_help(picture: bytes, field: str, problem: str) -> dict[str, str]:
    """Olha a tela travada e diz o que tentar uma vez; vazio se nao houver saida clara."""
    prompt = (f"Esta e a tela de um sistema imobiliario. O agente nao conseguiu preencher o campo '{field}'. Problema: {problem}. "
              'Responda so um JSON: {"acao": "clicar", "texto": "texto visivel exato do botao ou aba"} se um clique resolver, '
              '{"acao": "esperar"} se a tela ainda estiver carregando, ou {"acao": "nenhuma"} se nao souber. Nunca sugira salvar, publicar, excluir ou enviar.')
    image = {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64.b64encode(picture).decode()}"}}
    try:
        found = json.loads(re.search(r"\{.*\}", _chat([{"type": "text", "text": prompt}, image], SCREEN_TIMEOUT_S, THINKING_TOKENS), re.DOTALL).group(0))
    except Exception:
        return {"acao": "nenhuma", "texto": ""}
    return {"acao": str(found.get("acao", "nenhuma")), "texto": str(found.get("texto", ""))}


def write_ad(prompt: str) -> str:
    """Texto do anuncio pelo modelo local; vazio se ele nao estiver ligado."""
    try:
        return _chat(prompt, AD_TIMEOUT_S, THINKING_TOKENS * 2)
    except Exception:
        return ""


def classify_all(paths: list[Path], kind: str, company: str) -> list[dict[str, Any]]:
    """Classifica as fotos reaproveitando o que ja foi visto nesta empresa."""
    memory = order.load_memory(company)
    result: list[dict[str, Any]] = []
    model_up = True
    for index, path in enumerate(paths):
        mark = order.fingerprint(path)
        known = memory["fotos"].get(mark["sha"], {})
        if mark["sha"] in memory["correcoes"]:
            found = {"ambiente": memory["correcoes"][mark["sha"]], "confianca": 1.0, "ampla": known.get("ampla", False), "fonte": "dono"}
        elif known.get("kind") == kind and known.get("fonte") == "modelo":
            found = {key: known[key] for key in ("ambiente", "confianca", "ampla", "fonte")}
        else:
            answer = None
            if model_up:
                try:
                    answer = ask_vision(path, kind)
                except ModelDown:
                    model_up = False
            found = answer or from_labels(apple_labels(path), kind, mark["ceu"])
            memory["fotos"][mark["sha"]] = {**found, "kind": kind}
        result.append({**mark, **found, "caminho": str(path), "indice": index})
    order.save_memory(company, memory)
    return result
