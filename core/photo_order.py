"""Coloca as fotos de um imovel na sequencia de anuncio da empresa.

A ordem vem so destas tabelas e nunca da ordem do WhatsApp. Nada e apagado:
foto repetida apenas fica fora da sequencia, com o arquivo original intacto.
Correcoes do dono ficam por empresa e valem para as proximas vezes.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any, Final

_LOCK = threading.Lock()
DOUBT_BELOW: Final[float] = 0.6
SAME_PHOTO_BITS: Final[int] = 2
SAME_ROOM: Final[float] = 0.82

_CONDO_SHARED: Final[tuple[str, ...]] = (
    "condominio_salao_festas", "condominio_gourmet", "condominio_piscina", "condominio_academia", "condominio_playground",
    "condominio_quadras", "condominio_convivencia",
)
SEQUENCES: Final[dict[str, tuple[str, ...]]] = {
    "casa": (
        "fachada", "sala_estar", "sala_jantar", "cozinha", "patio", "dormitorio_principal", "closet", "banheiro_suite",
        "dormitorio_2", "banheiro_2", "dormitorio_3", "banheiro_3", "dormitorio_demais", "escritorio", "banheiro_social",
        "lavabo", "lavanderia", "espaco_gourmet", "churrasqueira", "piscina", "jardim", "garagem", "demais",
    ),
    "apartamento": (
        "sala_estar", "sala_jantar", "sacada", "vista_sacada", "cozinha", "dormitorio_principal", "closet", "banheiro_suite",
        "dormitorio_2", "dormitorio_3", "dormitorio_demais", "escritorio", "banheiro_social", "lavabo", "lavanderia",
        "churrasqueira", "terraco", "vagas", "deposito", "demais",
        "condominio_fachada", "condominio_hall", "condominio_portaria", *_CONDO_SHARED, "condominio_jardins",
        "condominio_garagens", "condominio_demais",
    ),
    "casa_condominio": (
        "fachada", "sala_estar", "sala_jantar", "cozinha", "patio", "dormitorio_principal", "closet", "banheiro_suite",
        "dormitorio_2", "banheiro_2", "dormitorio_3", "banheiro_3", "dormitorio_demais", "escritorio", "banheiro_social",
        "lavabo", "lavanderia", "espaco_gourmet", "churrasqueira", "piscina", "jardim", "garagem", "demais",
        "condominio_entrada", "condominio_portaria", "condominio_ruas", *_CONDO_SHARED, "condominio_demais",
    ),
    "sala_comercial": (
        "vista_geral", "ambiente_principal", "recepcao", "salas_internas", "sala_reuniao", "escritorio", "copa", "banheiros",
        "deposito", "sacada", "vista_janela", "vagas", "demais",
        "edificio_fachada", "edificio_entrada", "edificio_recepcao", "edificio_hall", "edificio_elevadores",
        "edificio_corredores", "edificio_areas_comuns", "edificio_estacionamento",
    ),
    "loja": (
        "fachada", "vitrine", "entrada", "salao_geral", "angulos_salao", "atendimento", "balcoes", "mezanino",
        "area_administrativa", "estoque", "deposito", "copa", "banheiros", "area_servico", "acessos", "estacionamento", "demais",
    ),
    "pavilhao": (
        "fachada", "area_externa", "entrada", "panoramica_interna", "angulos_internos", "armazenamento", "producao", "pe_direito",
        "docas", "rampas", "portoes", "circulacao_caminhoes", "manobras", "area_administrativa", "escritorios", "sala_reuniao",
        "refeitorio", "vestiarios", "banheiros", "deposito", "estacionamento", "areas_externas", "demais",
    ),
    "terreno": (
        "vista_frontal", "panoramica", "lateral_esquerda", "lateral_direita", "fundos", "vista_interna", "topografia", "acessos",
        "frente_rua", "ruas_proximas", "aereas", "dimensoes", "infraestrutura", "demais",
    ),
}
# O minimo para o anuncio ficar completo: faltando, avisa antes de publicar.
ESSENTIALS: Final[dict[str, dict[str, tuple[str, ...]]]] = {
    "casa": {"fachada": ("fachada",), "sala": ("sala_estar", "sala_jantar"), "cozinha": ("cozinha",), "dormitorio": ("dormitorio_principal", "dormitorio_2"), "banheiro": ("banheiro_suite", "banheiro_social", "banheiro_2")},
    "apartamento": {"sala": ("sala_estar", "sala_jantar"), "cozinha": ("cozinha",), "dormitorio": ("dormitorio_principal", "dormitorio_2"), "banheiro": ("banheiro_suite", "banheiro_social"), "fachada do predio": ("condominio_fachada",)},
    "casa_condominio": {"fachada": ("fachada",), "sala": ("sala_estar", "sala_jantar"), "cozinha": ("cozinha",), "dormitorio": ("dormitorio_principal", "dormitorio_2"), "banheiro": ("banheiro_suite", "banheiro_social", "banheiro_2")},
    "sala_comercial": {"vista geral": ("vista_geral", "ambiente_principal"), "fachada do predio": ("edificio_fachada",)},
    "loja": {"fachada": ("fachada",), "salao": ("salao_geral", "angulos_salao")},
    "pavilhao": {"fachada": ("fachada",), "interna do galpao": ("panoramica_interna", "angulos_internos"), "salas ou escritorio, se houver": ("area_administrativa", "escritorios", "sala_reuniao"), "banheiro, se houver": ("banheiros",)},
}
_NUMBERED: Final[dict[str, tuple[str, ...]]] = {
    "dormitorio": ("dormitorio_principal", "dormitorio_2", "dormitorio_3", "dormitorio_demais"),
}


def sequence_kind(kind: str, condominium: bool | None) -> str:
    """Traduz o tipo da fila para a tabela de fotos."""
    if kind == "casa":
        return "casa_condominio" if condominium else "casa"
    names = {"sala": "sala_comercial", "predio": "sala_comercial", "galpao": "pavilhao"}
    return names.get(kind, kind if kind in SEQUENCES else "loja")


def vocabulary(kind: str) -> list[str]:
    """Ambientes que o classificador pode responder para este tipo."""
    names: list[str] = []
    for name in SEQUENCES[kind]:
        generic = re.sub(r"_(principal|2|3|demais)$", "", name) if name.startswith("dormitorio") else name
        generic = "banheiro" if re.fullmatch(r"banheiro_(suite|2|3|social)", name) else generic
        if generic not in names:
            names.append(generic)
    return names


def _hamming(left: str, right: str) -> int:
    return bin(int(left, 16) ^ int(right, 16)).count("1")


def _cosine(left: list[float], right: list[float]) -> float:
    top = sum(a * b for a, b in zip(left, right))
    bottom = (sum(a * a for a in left) * sum(b * b for b in right)) ** 0.5
    return top / bottom if bottom else 0.0


def split_repeated(photos: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Separa as repetidas, mantendo a de melhor nota."""
    kept: list[dict[str, Any]] = []
    repeated: list[dict[str, Any]] = []
    for photo in sorted(photos, key=lambda item: -item.get("nota", 0)):
        same = any(photo["sha"] == other["sha"] or _hamming(photo["dhash"], other["dhash"]) <= SAME_PHOTO_BITS for other in kept)
        (repeated if same else kept).append(photo)
    return sorted(kept, key=lambda item: item["indice"]), repeated


def _rooms(photos: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Agrupa fotos parecidas do mesmo tipo de comodo, supondo o mesmo comodo."""
    groups: list[list[dict[str, Any]]] = []
    for photo in photos:
        for group in groups:
            if _cosine(photo["hist"], group[0]["hist"]) >= SAME_ROOM:
                group.append(photo)
                break
        else:
            groups.append([photo])
    return sorted(groups, key=lambda group: (-len(group), group[0]["indice"]))


def assign_rooms(kind: str, photos: list[dict[str, Any]], suites: int) -> list[str]:
    """Numera dormitorios e banheiros. A numeracao e provisoria e vira aviso."""
    notes: list[str] = []
    sequence = SEQUENCES[kind]
    bedrooms = _rooms([photo for photo in photos if photo["ambiente"] == "dormitorio"])
    for index, group in enumerate(bedrooms):
        name = _NUMBERED["dormitorio"][min(index, 3)]
        for photo in group:
            photo["ambiente"] = name
    baths = _rooms([photo for photo in photos if photo["ambiente"] == "banheiro"])
    private = [name for name in ("banheiro_suite", "banheiro_2", "banheiro_3") if name in sequence][:max(suites, 0)]
    for index, group in enumerate(baths):
        name = private[index] if index < len(private) else "banheiro_social"
        if name not in sequence:
            name = "demais"
        for photo in group:
            photo["ambiente"] = name
    if len(bedrooms) > 1 or (baths and private):
        notes.append("Confira qual dormitorio e banheiro e de cada suite.")
    return notes


def arrange(kind: str, photos: list[dict[str, Any]], suites: int = 0) -> dict[str, Any]:
    """Monta a sequencia final, as repetidas e as duvidas que importam."""
    sequence = SEQUENCES[kind]
    position = {name: index for index, name in enumerate(sequence)}
    kept, repeated = split_repeated([dict(photo) for photo in photos])
    notes = assign_rooms(kind, kept, suites)
    for photo in kept:
        if photo["ambiente"] not in position:
            photo["ambiente"] = "demais"
    kept.sort(key=lambda photo: (position[photo["ambiente"]], not photo.get("ampla"), -photo.get("nota", 0), photo["indice"]))
    doubts = [f"Conferir {Path(photo['caminho']).name}: {photo['ambiente'].replace('_', ' ')}" for photo in kept
              if photo.get("confianca", 1) < DOUBT_BELOW and photo.get("fonte") != "dono"]
    if kept and kept[0]["ambiente"] not in sequence[:3]:
        doubts.insert(0, f"Nao achei a foto principal ({sequence[0].replace('_', ' ')}).")
    rooms = {photo["ambiente"] for photo in kept}
    missing = [name for name, options in ESSENTIALS.get(kind, {}).items() if not rooms.intersection(options)]
    return {"ordem": kept, "repetidas": repeated, "avisos": notes, "duvidas": doubts, "capa": kept[0]["caminho"] if kept else "", "faltando": missing}


def fingerprint(path: Path) -> dict[str, Any]:
    """Impressao da foto: identidade, semelhanca e qualidade."""
    from PIL import Image, ImageFilter, ImageStat

    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    with Image.open(path) as image:
        color = image.convert("RGB")
    gray = color.convert("L").resize((9, 8))
    pixels = list(gray.getdata())
    bits = 0
    for row in range(8):
        for column in range(8):
            bits = (bits << 1) | (pixels[row * 9 + column] > pixels[row * 9 + column + 1])
    small = color.resize((32, 32))
    hist = [0.0] * 64
    for red, green, blue in small.getdata():
        hist[(red >> 6) * 16 + (green >> 6) * 4 + (blue >> 6)] += 1.0
    sample = color.convert("L").resize((480, 320))
    sharp = ImageStat.Stat(sample.filter(ImageFilter.FIND_EDGES)).stddev[0]
    light = ImageStat.Stat(sample).mean[0]
    exposure = 1 - abs(light - 128) / 128
    top = color.crop((0, 0, color.width, color.height // 4)).resize((32, 8))
    sky = sum(blue > red + 18 and blue > 110 for red, _green, blue in top.getdata()) / 256
    return {"sha": sha, "dhash": f"{bits:016x}", "hist": hist, "nota": round(min(sharp, 40) / 40 * 0.6 + exposure * 0.4, 3), "ceu": round(sky, 3)}


def _company_file(company: str) -> Path:
    from dodaios.core.paths import user_data_dir

    safe = re.sub(r"[^a-z0-9-]", "-", (company or "padrao").lower())
    return user_data_dir() / "data" / "imoveis" / "empresas" / safe / "fotos.json"


def load_memory(company: str) -> dict[str, Any]:
    try:
        return json.loads(_company_file(company).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"fotos": {}, "correcoes": {}}


def save_memory(company: str, memory: dict[str, Any]) -> None:
    path = _company_file(company)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as output:
            json.dump(memory, output, ensure_ascii=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def correct(company: str, sha: str, room: str) -> None:
    """Guarda a correcao do dono; ela vence qualquer classificacao futura."""
    with _LOCK:
        memory = load_memory(company)
        memory["correcoes"][sha] = room
        save_memory(company, memory)
