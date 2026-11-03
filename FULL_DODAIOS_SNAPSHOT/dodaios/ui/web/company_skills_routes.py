"""Rotas do modo de aprendizado: habilidades ensinadas a cada empresa."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from dodaios.core import company_skills as store

from .companies_routes import _read_state

router = APIRouter(prefix="/api/companies/{company_id}/skills", tags=["company-skills"])

_MAX_TEXT = 8_000
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
