"""Persistent multi-company workspace for JARVIS Business OS.

The business model is deliberately independent from the active Brain.  It is
user content, not configuration, and therefore lives in ``user_data_dir`` just
like Contacts and Socials.  The frontend can switch providers/models without
changing the company hierarchy or losing its operational context.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

router = APIRouter(prefix="/api/companies", tags=["companies"])
_LOCK = threading.Lock()

_MAX_COMPANIES = 100
_MAX_DEPARTMENTS = 100
_MAX_MEMBERS = 500
_MAX_TASKS = 2_000
_MAX_PROJECTS = 1_000
_MAX_LIST_ITEMS = 2_000
_MAX_TEXT = 8_000
_MAX_NAME = 240


AgentStatus = Literal["livre", "trabalhando", "aguardando", "erro"]
MemberKind = Literal["gerente", "especialista", "funcionario"]
Autonomy = Literal["assistido", "semi-autonomo", "autonomo"]
TaskStatus = Literal["pendente", "andamento", "aguardando", "concluida", "erro"]
ProjectStatus = Literal["planejado", "andamento", "aguardando", "concluido"]


class Department(BaseModel):
    id: str
    name: str
    floor: int = Field(ge=1, le=200)
    mission: str = ""


class Member(BaseModel):
    id: str
    name: str
    role: str
    departmentId: str
    kind: MemberKind = "especialista"
    status: AgentStatus = "livre"
    model: str = "JARVIS"
    autonomy: Autonomy = "semi-autonomo"
    currentTask: str | None = None
    missionId: str | None = None


class CompanyTask(BaseModel):
    id: str
    title: str
    description: str = ""
    assigneeId: str | None = None
    departmentId: str | None = None
    status: TaskStatus = "pendente"
    missionId: str | None = None
    createdAt: str | None = None
    updatedAt: str | None = None


class Project(BaseModel):
    id: str
    name: str
    status: ProjectStatus = "planejado"
    owner: str = ""


class Company(BaseModel):
    id: str
    name: str
    segment: str = "Empresa"
    description: str = ""
    departments: list[Department] = Field(default_factory=list, max_length=_MAX_DEPARTMENTS)
    members: list[Member] = Field(default_factory=list, max_length=_MAX_MEMBERS)
    tasks: list[CompanyTask] = Field(default_factory=list, max_length=_MAX_TASKS)
    projects: list[Project] = Field(default_factory=list, max_length=_MAX_PROJECTS)
    clients: list[str] = Field(default_factory=list, max_length=_MAX_LIST_ITEMS)
    files: list[str] = Field(default_factory=list, max_length=_MAX_LIST_ITEMS)
    automations: list[str] = Field(default_factory=list, max_length=_MAX_LIST_ITEMS)
    memory: list[str] = Field(default_factory=list, max_length=_MAX_LIST_ITEMS)

    @field_validator("id", "name", "segment")
    @classmethod
    def _short_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value cannot be empty")
        if len(value) > _MAX_NAME:
            raise ValueError(f"value is too long (max {_MAX_NAME})")
        return value

    @field_validator("description")
    @classmethod
    def _description(cls, value: str) -> str:
        if len(value) > _MAX_TEXT:
            raise ValueError(f"description is too long (max {_MAX_TEXT})")
        return value

    @field_validator("clients", "files", "automations", "memory")
    @classmethod
    def _bounded_strings(cls, values: list[str]) -> list[str]:
        clean: list[str] = []
        for raw in values:
            value = str(raw).strip()
            if not value:
                continue
            if len(value) > _MAX_TEXT:
                raise ValueError(f"list item is too long (max {_MAX_TEXT})")
            clean.append(value)
        return clean


class CompaniesState(BaseModel):
    companies: list[Company] = Field(default_factory=list, max_length=_MAX_COMPANIES)
    activeCompanyId: str | None = None
    version: int = 2


class CompanyCreate(BaseModel):
    name: str
    segment: str = "Empresa"
    description: str = "Novo workspace empresarial."


class CompanyPatch(BaseModel):
    name: str | None = None
    segment: str | None = None
    description: str | None = None


def _data_file() -> Path:
    from dodaios.core.paths import user_data_dir

    return user_data_dir() / "data" / "companies.json"


def _default_state() -> CompaniesState:
    return CompaniesState(
        activeCompanyId="moretto-imoveis",
        companies=[
            Company(
                id="moretto-imoveis",
                name="Moretto Imóveis",
                segment="Imobiliária",
                description="Locações, carteira de imóveis, atendimento, contratos, repasses, seguros e operação comercial.",
                departments=[
                    Department(id="diretoria", name="Diretoria", floor=4, mission="Prioridades, decisões e coordenação geral."),
                    Department(id="locacoes", name="Locações", floor=3, mission="Contratos, desocupações, seguros, boletos e vistorias."),
                    Department(id="financeiro", name="Financeiro", floor=2, mission="Recebimentos, repasses, cobrança e conciliação."),
                    Department(id="comercial", name="Comercial", floor=1, mission="Captação, clientes, imóveis e negociações."),
                ],
                members=[
                    Member(id="gerente-geral", name="Gerente Geral", role="Gerente Geral", departmentId="diretoria", kind="gerente", autonomy="autonomo"),
                    Member(id="contratos", name="Especialista em Contratos", role="Contratos e aditivos", departmentId="locacoes"),
                    Member(id="seguros", name="Especialista em Seguros", role="Incêndio e fiança", departmentId="locacoes"),
                    Member(id="financeiro-agent", name="Analista Financeiro", role="Cobrança e repasses", departmentId="financeiro", kind="funcionario", autonomy="assistido"),
                ],
                projects=[Project(id="carteira", name="Operação da carteira de locações", status="andamento", owner="Gerente Geral")],
                automations=["Triagem de solicitações de locação", "Acompanhamento de tarefas dos departamentos"],
                memory=["Contexto, regras e decisões desta empresa ficam separados das demais empresas."],
            ),
            Company(
                id="obras",
                name="Obras",
                segment="Construção e reformas",
                description="Orçamentos, execução, medições, SINAPI, documentos e acompanhamento de obras.",
                departments=[
                    Department(id="diretoria", name="Diretoria", floor=3, mission="Planejamento, decisões e contratos."),
                    Department(id="engenharia", name="Engenharia / Orçamentos", floor=2, mission="SINAPI, composições, projetos e quantitativos."),
                    Department(id="operacao", name="Operação de Obras", floor=1, mission="Execução, equipes, compras, diário e medição."),
                ],
                members=[
                    Member(id="gerente-obras", name="Gerente de Obras", role="Coordenação geral", departmentId="diretoria", kind="gerente", autonomy="autonomo"),
                    Member(id="sinapi", name="Especialista SINAPI", role="Custos e composições", departmentId="engenharia"),
                ],
            ),
            Company(
                id="energia-solar",
                name="Energia Solar",
                segment="Energia fotovoltaica",
                description="Clientes, dimensionamento, propostas, instalações e pós-venda de sistemas fotovoltaicos.",
                departments=[
                    Department(id="diretoria", name="Diretoria", floor=3, mission="Metas e coordenação."),
                    Department(id="projetos", name="Projetos", floor=2, mission="Dimensionamento e documentação técnica."),
                    Department(id="comercial", name="Comercial", floor=1, mission="Propostas, leads e fechamento."),
                ],
                members=[Member(id="gerente-solar", name="Gerente Solar", role="Coordenação geral", departmentId="diretoria", kind="gerente", autonomy="autonomo")],
            ),
            Company(
                id="arquitetura",
                name="Arquitetura",
                segment="Arquitetura e projetos",
                description="Clientes, plantas, detalhamentos, renderizações, documentos técnicos e gestão de projetos.",
                departments=[
                    Department(id="diretoria", name="Diretoria", floor=3, mission="Coordenação criativa e prioridades."),
                    Department(id="projetos", name="Projetos", floor=2, mission="Plantas, detalhamentos e compatibilização."),
                    Department(id="visualizacao", name="Visualização", floor=1, mission="Renderizações e apresentações."),
                ],
                members=[
                    Member(id="gerente-arq", name="Gerente de Projetos", role="Coordenação", departmentId="diretoria", kind="gerente", autonomy="autonomo"),
                    Member(id="cad", name="Especialista CAD", role="Plantas e detalhamento", departmentId="projetos"),
                ],
            ),
        ],
    )


def _read_state() -> CompaniesState:
    path = _data_file()
    if not path.exists():
        return _default_state()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return CompaniesState.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=f"Companies data could not be read: {exc}") from exc


def _write_state(state: CompaniesState) -> None:
    path = _data_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state.model_dump(mode="json"), ensure_ascii=False, indent=2)
    fd, tmp_name = tempfile.mkstemp(prefix="companies-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        except OSError:
            pass


def _slug(name: str) -> str:
    import re
    import unicodedata

    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-") or "empresa"
    return f"{text}-{uuid.uuid4().hex[:8]}"


@router.get("")
def get_companies() -> dict:
    with _LOCK:
        return _read_state().model_dump(mode="json")


@router.put("")
def replace_companies(body: CompaniesState) -> dict:
    ids = [company.id for company in body.companies]
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=422, detail="Company ids must be unique")
    if body.activeCompanyId and body.activeCompanyId not in set(ids):
        body.activeCompanyId = ids[0] if ids else None
    with _LOCK:
        _write_state(body)
    return {"ok": True, **body.model_dump(mode="json")}


@router.post("", status_code=201)
def create_company(body: CompanyCreate) -> dict:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Company name cannot be empty")
    with _LOCK:
        state = _read_state()
        if len(state.companies) >= _MAX_COMPANIES:
            raise HTTPException(status_code=409, detail="Company limit reached")
        company = Company(
            id=_slug(name),
            name=name[:_MAX_NAME],
            segment=(body.segment.strip() or "Empresa")[:_MAX_NAME],
            description=body.description[:_MAX_TEXT],
            departments=[Department(id=f"diretoria-{uuid.uuid4().hex[:8]}", name="Diretoria", floor=1, mission="Coordenação geral.")],
        )
        state.companies.append(company)
        state.activeCompanyId = company.id
        _write_state(state)
    return company.model_dump(mode="json")


@router.patch("/{company_id}")
def patch_company(company_id: str, body: CompanyPatch) -> dict:
    with _LOCK:
        state = _read_state()
        company = next((item for item in state.companies if item.id == company_id), None)
        if company is None:
            raise HTTPException(status_code=404, detail="Company not found")
        patch = body.model_dump(exclude_unset=True)
        for key, value in patch.items():
            if value is not None:
                setattr(company, key, value.strip() if isinstance(value, str) else value)
        _write_state(state)
    return company.model_dump(mode="json")


@router.delete("/{company_id}")
def delete_company(company_id: str) -> dict:
    with _LOCK:
        state = _read_state()
        before = len(state.companies)
        state.companies = [item for item in state.companies if item.id != company_id]
        removed = len(state.companies) != before
        if state.activeCompanyId == company_id:
            state.activeCompanyId = state.companies[0].id if state.companies else None
        if removed:
            _write_state(state)
    return {"ok": True, "removed": removed, "activeCompanyId": state.activeCompanyId}
