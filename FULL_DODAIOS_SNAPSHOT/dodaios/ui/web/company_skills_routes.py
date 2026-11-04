"""Rotas do modo de aprendizado: habilidades ensinadas a cada empresa."""
from __future__ import annotations

import json
import subprocess

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from dodaios.core import company_skills as store

from .companies_routes import _read_state

KENLO_WAIT_S = 1800

router = APIRouter(prefix="/api/companies/{company_id}/skills", tags=["company-skills"])

voice_router = APIRouter(prefix="/api/company-voice", tags=["company-skills"])

_MAX_TEXT = 8_000
#: Dois minutos de PCM de 16 bits a 16 kHz.
_MAX_AUDIO_BYTES = 1_920_000
_stt = None
_MAX_LIST = 200


class SkillFields(BaseModel):
    name: str | None = Field(default=None, max_length=240)
    category: str | None = Field(default=None, max_length=240)
    whenToUse: str | None = Field(default=None, max_length=_MAX_TEXT)
    procedure: str | None = Field(default=None, max_length=_MAX_TEXT)
    managerId: str | None = Field(default=None, max_length=240)
    specialistId: str | None = Field(default=None, max_length=240)
    platform: str | None = Field(default=None, max_length=40)
    steps: list[str] | None = Field(default=None, max_length=_MAX_LIST)
    rules: list[str] | None = Field(default=None, max_length=_MAX_LIST)
    conditions: list[str] | None = Field(default=None, max_length=_MAX_LIST)
    exceptions: list[str] | None = Field(default=None, max_length=_MAX_LIST)
    validation: list[str] | None = Field(default=None, max_length=_MAX_LIST)
    note: str = Field(default="", max_length=240)


class Example(BaseModel):
    situation: str = Field(max_length=_MAX_TEXT)
    outcome: str = Field(default="", max_length=_MAX_TEXT)
    kind: str = Field(default="normal", max_length=80)


class Correction(BaseModel):
    text: str = Field(max_length=_MAX_TEXT)


def _company_name(company_id: str) -> str:
    for company in _read_state().companies:
        if company.id == company_id:
            return company.name
    raise HTTPException(status_code=404, detail="Empresa nao encontrada")


def _guarded(call, *args):
    try:
        return call(*args)
    except store.SkillNotFound as exc:
        raise HTTPException(status_code=404, detail="Habilidade nao encontrada") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("")
def list_company_skills(company_id: str) -> dict:
    _company_name(company_id)
    return {"skills": _guarded(store.list_skills, company_id)}


@router.post("", status_code=201)
def create_company_skill(company_id: str, body: SkillFields) -> dict:
    name = _company_name(company_id)
    return _guarded(store.create_skill, company_id, name, body.model_dump(exclude={"note"}))


@router.post("/archive", status_code=201)
def archive_company_skills(company_id: str) -> dict:
    """Copia a empresa e as habilidades. O painel exige isso antes de apagar."""
    for company in _read_state().companies:
        if company.id == company_id:
            return {"backup": _guarded(store.archive_company, company_id, company.model_dump())}
    raise HTTPException(status_code=404, detail="Empresa nao encontrada")


@router.get("/{skill_id}")
def get_company_skill(company_id: str, skill_id: str) -> dict:
    _company_name(company_id)
    return _guarded(store.get_skill, company_id, skill_id)


@router.patch("/{skill_id}")
def patch_company_skill(company_id: str, skill_id: str, body: SkillFields) -> dict:
    _company_name(company_id)
    return _guarded(store.update_skill, company_id, skill_id, body.model_dump(exclude={"note"}), body.note)


@router.delete("/{skill_id}")
def delete_company_skill(company_id: str, skill_id: str) -> dict:
    _company_name(company_id)
    _guarded(store.delete_skill, company_id, skill_id)
    return {"ok": True}


@router.post("/{skill_id}/examples", status_code=201)
def add_skill_example(company_id: str, skill_id: str, body: Example) -> dict:
    _company_name(company_id)
    return _guarded(store.add_example, company_id, skill_id, body.model_dump())


@router.post("/{skill_id}/corrections", status_code=201)
def add_skill_correction(company_id: str, skill_id: str, body: Correction) -> dict:
    _company_name(company_id)
    return _guarded(store.add_correction, company_id, skill_id, body.text)


class LiveStep(BaseModel):
    text: str = Field(max_length=_MAX_TEXT)
    pendingLink: str = Field(default="", max_length=240)


@voice_router.post("/act")
def act_on_step(body: LiveStep) -> dict:
    """Executa na hora os passos que nao precisam do modelo."""
    from dodaios.core.live_actions import act

    try:
        return act(body.text, body.pendingLink)
    except (OSError, subprocess.SubprocessError) as exc:
        raise HTTPException(status_code=500, detail=f"Nao consegui abrir: {exc}") from exc


class TeachStart(BaseModel):
    companyId: str = Field(max_length=240)
    skillId: str = Field(max_length=240)


@voice_router.post("/ensino/iniciar")
def start_live_teaching(body: TeachStart) -> dict:
    """Comeca a ouvir e executar no servidor, ate finalizar o aprendizado."""
    from dodaios.core.live_teach import SESSION

    _guarded(store.get_skill, body.companyId, body.skillId)
    SESSION.start(body.companyId, body.skillId)
    return {"ok": True}


class TeachSpeech(BaseModel):
    text: str = Field(max_length=_MAX_TEXT)


@voice_router.post("/ensino/falar")
def speak_in_teaching(body: TeachSpeech) -> dict:
    from dodaios.core.live_teach import SESSION

    SESSION.speak(body.text)
    return {"ok": True}


@voice_router.post("/ensino/parar")
def stop_live_teaching() -> dict:
    from dodaios.core.live_teach import SESSION

    SESSION.stop()
    return {"ok": True}


@voice_router.get("/ensino/estado")
def live_teaching_state(desde: int = 0, assistente: int = 0) -> dict:
    from dodaios.core.live_teach import SESSION

    return SESSION.snapshot(desde, assistente)


@voice_router.get("/ensino/microfone")
def live_microphone_level() -> dict:
    """Mede um segundo de audio; serve para conferir a permissao do microfone."""
    from dodaios.core.live_teach import microphone_level

    try:
        return {"ok": True, "nivel": round(microphone_level(), 4)}
    except Exception as exc:  # noqa: BLE001 — o motivo vai para o instalador
        return {"ok": False, "detail": str(exc)[:200]}


@voice_router.get("/permissoes")
def screen_permissions() -> dict:
    from dodaios.core.screen_control import permissions

    return permissions()


@voice_router.post("/transcribe")
async def transcribe_teaching(request: Request) -> dict:
    """Transcreve uma fala do ensino com o mesmo motor de voz do app."""
    global _stt
    audio = await request.body()
    if not audio or len(audio) > _MAX_AUDIO_BYTES or len(audio) % 2:
        raise HTTPException(status_code=422, detail="Audio invalido")
    if _stt is None:
        from dodaios.core.config import load_config
        from dodaios.plugins.stt import build_stt_from_config

        _stt = build_stt_from_config(load_config().stt)
    result = await _stt.transcribe_pcm(audio, sample_rate=16_000)
    return {"text": (getattr(result, "text", "") or "").strip()}


class PropertyMark(BaseModel):
    status: str = Field(max_length=20)
    note: str = Field(default="", max_length=_MAX_TEXT)


class PropertyAnswers(BaseModel):
    tipo: str = Field(default="", max_length=40)
    finalidade: str = Field(default="", max_length=40)
    condominio: bool | None = None


class GroupRead(BaseModel):
    grupo: str = Field(min_length=1, max_length=240)


class PhotoOrder(BaseModel):
    ordem: list[str]
    ambientes: dict[str, str] = Field(default_factory=dict)


class KenloRun(BaseModel):
    key: str = Field(min_length=1, max_length=120)
    salvar: bool = False


@voice_router.post("/imoveis/ler")
async def read_whatsapp_group(body: GroupRead) -> dict:
    """Le o grupo do WhatsApp no Chrome separado e devolve o resumo."""
    import asyncio
    import sys
    from pathlib import Path

    script = Path.home() / ".dodaios" / "bridge" / "ja-whatsapp-imoveis.py"
    process = await asyncio.create_subprocess_exec(
        sys.executable, str(script), "--grupo", body.grupo,
        cwd=str(script.parents[1]),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout=1800)
    except TimeoutError as exc:
        process.kill()
        raise HTTPException(status_code=504, detail="A leitura demorou demais") from exc
    text = output.decode("utf-8", "replace")
    for line in reversed(text.splitlines()):
        if line.startswith("WHATSAPP_LIDO="):
            return json.loads(line.split("=", 1)[1])
        if line.startswith("WHATSAPP_SEM_LOGIN"):
            raise HTTPException(status_code=409, detail="Entre no WhatsApp com o QR Code primeiro")
    raise HTTPException(status_code=500, detail="Falha ao ler o grupo: " + text[-300:])


@voice_router.get("/imoveis")
def properties_summary() -> dict:
    from dodaios.core import property_intake as intake

    return {**intake.summary(), "proximo": intake.next_pending()}


def _ordered_photos(item: dict) -> dict:
    """Sequencia das fotos: a escolhida pelo dono ou a calculada agora."""
    from pathlib import Path

    from dodaios.core import cadastro_plan as plan, photo_order as order, photo_vision as vision
    from dodaios.core.property_sheet import parse_sheet

    kind = order.sequence_kind(item["tipo"], item["condominio"])
    paths = [Path(path) for path in item.get("fotos", []) if Path(path).exists()]
    photos = vision.classify_all(paths, kind, plan.load_rules()["empresa"])
    result = order.arrange(kind, photos, int(parse_sheet(item["texto"])["suites"] or 0))
    chosen = item.get("ordem_fotos") or []
    if chosen:
        rank = {path: index for index, path in enumerate(chosen)}
        result["ordem"].sort(key=lambda photo: rank.get(photo["caminho"], len(rank)))
    fields = ("ambiente", "confianca", "fonte")
    return {"ordem": [{"nome": Path(photo["caminho"]).name, **{name: photo[name] for name in fields}} for photo in result["ordem"]],
            "repetidas": [Path(photo["caminho"]).name for photo in result["repetidas"]],
            "avisos": result["avisos"] + result["duvidas"], "ambientes": list(order.SEQUENCES[kind])}


@voice_router.get("/imoveis/{key}/fotos")
def property_photos(key: str) -> dict:
    from dodaios.core import property_intake as intake

    item = intake.get(key)
    if not item:
        raise HTTPException(status_code=404, detail="Imovel nao encontrado")
    return {"imovel": item, **_ordered_photos(item)}


@voice_router.get("/imoveis/{key}/foto/{name}")
def property_photo(key: str, name: str):
    from pathlib import Path

    from fastapi.responses import FileResponse

    from dodaios.core import property_intake as intake

    item = intake.get(key)
    match = next((path for path in (item or {}).get("fotos", []) if Path(path).name == name), None)
    if not match or not Path(match).exists():
        raise HTTPException(status_code=404, detail="Foto nao encontrada")
    return FileResponse(match)


@voice_router.post("/imoveis/{key}/fotos")
def save_photo_order(key: str, body: PhotoOrder) -> dict:
    """Guarda a ordem final e aprende os ambientes corrigidos pelo dono."""
    from pathlib import Path

    from dodaios.core import cadastro_plan as plan, photo_order as order, property_intake as intake

    item = intake.get(key)
    if not item:
        raise HTTPException(status_code=404, detail="Imovel nao encontrado")
    by_name = {Path(path).name: path for path in item.get("fotos", [])}
    if any(name not in by_name for name in [*body.ordem, *body.ambientes]):
        raise HTTPException(status_code=422, detail="Foto desconhecida")
    company = plan.load_rules()["empresa"]
    for name, room in body.ambientes.items():
        order.correct(company, order.fingerprint(Path(by_name[name]))["sha"], room)
    intake.update(key, ordem_fotos=[by_name[name] for name in body.ordem])
    return {"ok": True}


@voice_router.post("/imoveis/kenlo")
async def register_on_kenlo(body: KenloRun) -> dict:
    """Abre o agente e responde assim que ele informa o resultado."""
    import asyncio
    import sys
    import tempfile
    from pathlib import Path

    script = Path.home() / ".dodaios" / "bridge" / "ja-kenlo-cadastro.py"
    log = Path(tempfile.mkstemp(prefix="ja-kenlo-", suffix=".log")[1])
    command = [sys.executable, str(script), "--imovel", body.key, *(["--salvar"] if body.salvar else [])]
    with log.open("wb") as output:
        process = await asyncio.create_subprocess_exec(*command, cwd=str(script.parents[1]), stdout=output, stderr=asyncio.subprocess.STDOUT)
    for _ in range(KENLO_WAIT_S):
        text = log.read_text("utf-8", "replace")
        found = next((line for line in text.splitlines() if line.startswith("KENLO_RESULTADO=")), "")
        if found:
            return {"resultado": found.split("=", 1)[1]}
        if process.returncode is not None:
            raise HTTPException(status_code=500, detail=text[-400:] or "O agente parou sem resultado")
        await asyncio.sleep(1)
    raise HTTPException(status_code=504, detail="O cadastro demorou demais")


@voice_router.post("/imoveis/{key}/situacao")
def mark_property(key: str, body: PropertyMark) -> dict:
    from dodaios.core import property_intake as intake

    try:
        return intake.mark(key, body.status, body.note)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Imovel nao encontrado") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@voice_router.post("/imoveis/{key}/resposta")
def answer_property(key: str, body: PropertyAnswers) -> dict:
    from dodaios.core import property_intake as intake

    try:
        return intake.resolve(key, body.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Imovel nao encontrado") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
