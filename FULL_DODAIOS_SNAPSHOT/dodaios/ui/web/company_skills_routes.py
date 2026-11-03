"""Rotas do modo de aprendizado: habilidades ensinadas a cada empresa."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from dodaios.core import company_skills as store

from .companies_routes import _read_state

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


@router.post("/{skill_id}/examples", status_code=201)
def add_skill_example(company_id: str, skill_id: str, body: Example) -> dict:
    _company_name(company_id)
    return _guarded(store.add_example, company_id, skill_id, body.model_dump())


@router.post("/{skill_id}/corrections", status_code=201)
def add_skill_correction(company_id: str, skill_id: str, body: Correction) -> dict:
    _company_name(company_id)
    return _guarded(store.add_correction, company_id, skill_id, body.text)


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
