"""Rotas do modo de aprendizado: habilidades ensinadas a cada empresa."""
from __future__ import annotations

import json
import re
import subprocess
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from dodaios.core import company_skills as store

from dodaios.core import company_org as org
from dodaios.core import company_chat as chat
from dodaios.core import knowledge

from .companies_routes import CompanyTask, Department, Member, _read_state, _write_state, remember_fired

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


def _company(state, company_id: str):
    company = next((item for item in state.companies if item.id == company_id), None)
    if company is None:
        raise HTTPException(status_code=404, detail="Empresa nao encontrada")
    return company


def _organized(company_id: str):
    """Estado com a estrutura padrao aplicada; vale para qualquer empresa."""
    state = _read_state()
    company = _company(state, company_id)
    if org.ensure_structure(company, Department, Member):
        _write_state(state)
    return state, company


def _ensure_specialist(company_id: str, skill: dict, sector: str = "", urgent: bool = False) -> dict:
    """Toda habilidade tem um funcionario especialista; cria se faltar."""
    if skill.get("specialistId"):
        return skill
    state, company = _organized(company_id)
    member_id = f"especialista-{skill['id']}"[:120]
    if not any(member.id == member_id for member in company.members):
        home = sector or next(item.id for item in company.departments if org.fold(item.name) == org.HOME_SECTOR)
        company.members.append(Member(id=member_id, name=f"Especialista em {skill['name']}"[:120], role="Especialista da habilidade", departmentId=home))
        _write_state(state)
    manager = org.manager_of(company, next(member.departmentId for member in company.members if member.id == member_id))
    changes = {"specialistId": member_id, "managerId": manager.id if manager else ""}
    updated = store.update_skill(company_id, skill["id"], changes, "Especialista criado")
    _start_study(company_id, company, updated, urgent)
    return updated


def _start_study(company_id: str, company, skill: dict, urgent: bool = False) -> None:
    """Regra geral: todo especialista nasce estudando a propria funcao."""
    def finished(result: dict) -> None:
        if result["estado"] != "pronto":
            return
        done = org.write_from_study(company_id, store.get_skill(company_id, skill["id"]))
        knowledge.mark(company_id, skill["id"], resumo="pronto" if done else "pendente")

    knowledge.enqueue(company_id, skill["id"], org.study_topic(company, skill), finished, urgent=urgent)


PHOTO_SKILL = "Organização de fotos"
_PHOTO_STEPS = ["Receber as fotos do imóvel vindas do especialista de cadastro.", "Identificar o ambiente de cada foto.", "Separar as fotos repetidas, sem apagar o arquivo.",
                "Colocar as fotos na sequência configurada para o tipo de imóvel.", "Apontar as fotos em dúvida e aguardar a decisão do dono.", "Entregar a ordem final ao especialista de cadastro."]
_PHOTO_RULES = ["Nunca apagar fotografias sem autorização.", "Preservar os arquivos originais.", "Não alterar as características reais das fotografias.",
                "Usar a sequência da empresa, nunca a ordem do WhatsApp.", "Só mudar as regras de ordem com autorização do dono."]


def _hire_photo_specialists(state) -> None:
    """Quem cadastra imoveis ganha um especialista para cuidar das fotos."""
    for company in state.companies:
        names = [org.fold(skill["name"]) for skill in store.list_skills(company.id)]
        dealer = "imob" in org.fold(company.segment) or any("imove" in name for name in names)
        if org.fold(PHOTO_SKILL) in names or not dealer:
            continue
        skill = store.create_skill(company.id, company.name, {"name": PHOTO_SKILL, "whenToUse": "Quando um imóvel chegar com fotos para cadastrar.", "steps": _PHOTO_STEPS, "rules": _PHOTO_RULES})
        _ensure_specialist(company.id, skill)


def _study_everyone(state) -> int:
    """Quem ja existia e ainda nao sabe nada tambem vai estudar."""
    started = 0
    for company in state.companies:
        skills = store.list_skills(company.id)
        taught = {skill.get("specialistId") for skill in skills}
        for person in company.members:
            if person.kind == "especialista" and person.id not in taught:
                name = re.sub(r"^Especialista em ", "", person.name)
                try:
                    created = store.create_skill(company.id, company.name, {"name": name, "whenToUse": person.role, "category": person.departmentId})
                except ValueError:
                    continue
                manager = org.manager_of(company, person.departmentId)
                skills.append(store.update_skill(company.id, created["id"], {"specialistId": person.id, "managerId": manager.id if manager else ""}, "Especialista ja existente"))
        for skill in skills:
            if knowledge.needs_study(company.id, skill["id"]):
                _start_study(company.id, company, skill)
                started += 1
            elif knowledge.status(company.id, skill["id"]).get("resumo") != "pronto":
                _finish_summary(company.id, skill)
    return started


def _finish_summary(company_id: str, skill: dict) -> None:
    def finished(_result: dict) -> None:
        done = org.write_from_study(company_id, store.get_skill(company_id, skill["id"]))
        knowledge.mark(company_id, skill["id"], resumo="pronto" if done else "pendente")

    knowledge.enqueue(company_id, skill["id"], "", finished, only_finish=True)


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
    return {"skills": [_ensure_specialist(company_id, skill) for skill in _guarded(store.list_skills, company_id)]}


@router.post("", status_code=201)
def create_company_skill(company_id: str, body: SkillFields) -> dict:
    name = _company_name(company_id)
    return _ensure_specialist(company_id, _guarded(store.create_skill, company_id, name, body.model_dump(exclude={"note"})))


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


class CompanyTaskBody(BaseModel):
    texto: str = Field(min_length=1, max_length=_MAX_TEXT)
    membro: str = Field(default="", max_length=240)


class NewFunction(BaseModel):
    nome: str = Field(min_length=1, max_length=240)
    quando_usar: str = Field(default="", max_length=_MAX_TEXT)


class MemberEdit(BaseModel):
    nome: str = Field(min_length=1, max_length=120)
    cargo: str = Field(default="", max_length=120)


class AgentRun(BaseModel):
    salvar: bool = False


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


@voice_router.get("/imoveis/fotos/painel")
def photo_panel() -> dict:
    """O que o Especialista em Fotos esta cuidando."""
    from dodaios.core import cadastro_plan as plan, photo_order as order, property_intake as intake

    try:
        corrections = len(order.load_memory(plan.load_rules()["empresa"]).get("correcoes", {}))
    except (OSError, ValueError, KeyError):
        corrections = 0
    items = [{"chave": item["chave"], "titulo": item.get("titulo") or item["chave"], "status": item.get("status", ""), "aprovada": bool(item.get("ordem_fotos")), **item.get("analise_fotos", {})}
             for item in intake.all_items() if item.get("fotos") and item.get("analise_fotos")]
    return {"correcoes": corrections, "itens": items[-12:]}


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


@voice_router.post("/empresas/organizar")
def organize_all_companies() -> dict:
    """Aplica a regra geral a todas as empresas, antigas e novas."""
    state = _read_state()
    changed = [org.ensure_structure(company, Department, Member) for company in state.companies]
    if any(changed):
        _write_state(state)
    _hire_photo_specialists(state)
    return {"alteradas": sum(changed), "estudando": _study_everyone(_read_state())}


@voice_router.get("/empresa/{company_id}/organizacao")
def company_organization(company_id: str) -> dict:
    return org.organization(_organized(company_id)[1])


def create_researched_specialist(company_id: str, topic: str, sector: str = "", urgent: bool = False) -> dict:
    """O gerente do setor cria o especialista e ele vai estudar na internet."""
    state, company = _organized(company_id)
    sector = sector or org.sector_for(company, topic)
    manager = org.manager_of(company, sector)
    small = {"de", "do", "da", "dos", "das", "e", "em"}
    name = " ".join(word if word.isupper() or word in small else word[:1].upper() + word[1:] for word in topic.split())
    skill = next((item for item in store.list_skills(company_id) if org.fold(item["name"]) == org.fold(name)), None)
    if skill is None:
        skill = store.create_skill(company_id, company.name, {
            "name": name, "category": sector, "whenToUse": f"Duvidas e tarefas sobre {topic}.",
            "rules": ["Responder somente com as fontes estudadas e citar a origem.", "Se nao estiver nas fontes, dizer que nao encontrou."]})
    skill = _ensure_specialist(company_id, skill, sector, urgent)

    person = next(item for item in _company(_read_state(), company_id).members if item.id == skill["specialistId"])
    if knowledge.needs_study(company_id, skill["id"]):
        _start_study(company_id, company, skill, urgent)
    return {"rota": [item for item in dict.fromkeys(("Gerente Geral", manager.name if manager else "", person.name)) if item], "setor": sector,
            "membro": person.id, "habilidade": skill["id"], "criado": person.name, "agente": False, "prompt": ""}


def answer_company_request(text: str) -> str | None:
    """No chat: 'crie um especialista em ...' vale para a empresa ativa."""
    topic = org.wants_specialist(text)
    if not topic:
        return None
    state = _read_state()
    company_id = state.activeCompanyId or (state.companies[0].id if state.companies else "")
    if not company_id:
        return None
    result = create_researched_specialist(company_id, topic)
    return f"{result['rota'][-2]} criou {result['criado']}. Ele esta pesquisando na internet agora e fica disponivel quando terminar."


@voice_router.post("/empresa/{company_id}/tarefa")
def new_company_task(company_id: str, body: CompanyTaskBody) -> dict:
    """Passa a tarefa pelos gerentes; imoveis usam o agente, o resto vira missao."""
    from dodaios.core import property_agent

    topic = org.wants_specialist(body.texto)
    if topic:
        sector = next((item.departmentId for item in _organized(company_id)[1].members if item.id == body.membro), "")
        return create_researched_specialist(company_id, topic, sector)
    state, company = _organized(company_id)
    route = org.route_task(company, body.texto, body.membro)
    company.tasks.insert(0, CompanyTask(id=f"task-{uuid4().hex[:12]}", title=body.texto[:90], description=body.texto, assigneeId=route["membro"] or None, departmentId=route["setor"] or None, status="andamento"))
    _write_state(state)
    if route["agente"]:
        try:
            property_agent.start(property_agent.can_save())
            route["iniciado"] = True
        except RuntimeError as exc:
            route["aviso"] = str(exc)
    return route


class ChatMessage(BaseModel):
    texto: str = Field(min_length=1, max_length=_MAX_TEXT)


def _answer_after_study(company_id: str, question: str, created: dict) -> None:
    """Quando o novo especialista termina de estudar, a resposta entra na conversa."""
    def deliver(result: dict) -> None:
        if result["estado"] != "pronto":
            chat.add(company_id, "empresa", f"{created['criado']} procurou, mas não achou fontes sobre isso. Me ensine ou tente perguntar de outro jeito.", rota=created["rota"])
            return
        found = knowledge.answer(company_id, created["habilidade"], created["criado"], question)
        chat.add(company_id, "empresa", found["resposta"], rota=created["rota"], fontes=found["fontes"])

    if not knowledge.when_ready(company_id, created["habilidade"], deliver):
        deliver(knowledge.status(company_id, created["habilidade"]))


def _ask_company(company_id: str, company, text: str) -> dict:
    from dodaios.core import property_agent

    data = property_agent.answer_property_request(text)
    if data:
        return {"texto": data, "rota": ["Gerente Geral", "Especialista em imóveis"]}
    found = org.find_answer(company, text)
    if found:
        return {"texto": found["resposta"], "rota": found["rota"], "fontes": found["fontes"]}
    plan = org.plan_new_specialist(company, text)
    if not plan["internet"]:
        return {"texto": "Isso depende de dados internos que nenhum setor tem ainda. Me passe a informação ou ensine o setor responsável.", "rota": ["Gerente Geral"]}
    created = create_researched_specialist(company_id, plan["tema"], plan["setor"], urgent=True)
    sector = next((item.name for item in company.departments if item.id == created["setor"]), created["setor"])
    _answer_after_study(company_id, text, created)
    return {"texto": f"Ninguém sabia responder ainda. {created['criado']} está em {sector} e já vai estudar; a resposta chega aqui.", "rota": created["rota"], "pendente": created["habilidade"]}


@voice_router.get("/empresa/{company_id}/conversa")
def company_conversation(company_id: str) -> dict:
    messages = chat.history(company_id)
    open_studies = {item["pendente"] for item in messages if item.get("pendente")}
    return {"mensagens": messages, "estudando": any(knowledge.status(company_id, skill)["estado"] in ("aguardando", "pesquisando") for skill in open_studies)}


@voice_router.post("/empresa/{company_id}/conversa")
def talk_to_company(company_id: str, body: ChatMessage) -> dict:
    """O dono fala com a empresa: pergunta vira resposta e ordem vira tarefa."""
    _state, company = _organized(company_id)
    chat.add(company_id, "voce", body.texto)
    topic = org.wants_specialist(body.texto)
    if org.is_question(body.texto) and not topic:
        reply = _ask_company(company_id, company, body.texto)
        chat.add(company_id, "empresa", reply.pop("texto"), **reply)
        return {"ok": True}
    route = new_company_task(company_id, CompanyTaskBody(texto=body.texto))
    if route.get("criado"):
        chat.add(company_id, "empresa", f"{route['criado']} foi criado e já vai estudar.", rota=route["rota"], pendente=route["habilidade"])
    elif route.get("resposta"):
        chat.add(company_id, "empresa", route["resposta"], rota=route["rota"], fontes=route.get("fontes", []))
    elif route.get("agente"):
        chat.add(company_id, "empresa", route.get("aviso") or "O agente começou. Acompanhe na ficha do especialista.", rota=route["rota"])
    else:
        chat.add(company_id, "empresa", "Tarefa encaminhada. Acompanhe em Tarefas.", rota=route["rota"])
        return {"missao": route["prompt"]}
    return {"ok": True}


@voice_router.post("/empresa/{company_id}/departamento")
def add_department(company_id: str, body: NewFunction) -> dict:
    """Departamento novo ja nasce com gerente, como os outros."""
    state = _read_state()
    company = _company(state, company_id)
    slug = re.sub(r"[^a-z0-9]+", "-", org.fold(body.nome)).strip("-")[:60] or "departamento"
    if any(org.fold(item.name) == org.fold(body.nome) or item.id == slug for item in company.departments):
        raise HTTPException(status_code=409, detail="Esse departamento ja existe")
    company.departments.append(Department(id=slug, name=body.nome[:120], floor=len(company.departments) + 1, mission=body.quando_usar or f"Funcoes de {body.nome}."))
    org.ensure_structure(company, Department, Member)
    _write_state(state)
    return {"id": slug}


@voice_router.post("/empresa/{company_id}/setor/{sector}/aprender")
def teach_sector(company_id: str, sector: str, body: NewFunction) -> dict:
    """O gerente cria o especialista da funcao dentro do proprio setor."""
    _state, company = _organized(company_id)
    manager = org.manager_of(company, sector)
    if manager is None:
        raise HTTPException(status_code=404, detail="Setor nao encontrado")
    skill = _guarded(store.create_skill, company_id, company.name, {"name": body.nome, "whenToUse": body.quando_usar, "category": sector})
    return _ensure_specialist(company_id, skill, sector)


@voice_router.post("/empresa/{company_id}/setor/{sector}/montar-equipe")
def build_sector_team(company_id: str, sector: str) -> dict:
    """O gerente descobre o que o setor faz e cria os especialistas que faltam."""
    _state, company = _organized(company_id)
    if org.manager_of(company, sector) is None:
        raise HTTPException(status_code=404, detail="Setor nao encontrado")
    proposals = org.propose_team(company, sector)
    created = []
    for item in proposals:
        skill = store.create_skill(company_id, company.name, {
            "name": str(item["nome"])[:200], "whenToUse": str(item.get("quando_usar", ""))[:_MAX_TEXT], "category": sector,
            "steps": [str(step) for step in item.get("passos", [])][:_MAX_LIST], "rules": [str(rule) for rule in item.get("regras", [])][:_MAX_LIST]})
        created.append(_ensure_specialist(company_id, skill, sector)["name"])
    return {"criados": created, "basico": any(item.get("base") for item in proposals)}


@voice_router.post("/empresa/{company_id}/habilidade/{skill_id}/estudar")
def study_again(company_id: str, skill_id: str) -> dict:
    """Atualiza o conhecimento: procura de novo as fontes, sem perder as atuais."""
    _state, company = _organized(company_id)
    _start_study(company_id, company, _guarded(store.get_skill, company_id, skill_id))
    return {"ok": True}


@voice_router.patch("/empresa/{company_id}/funcionario/{member_id}")
def edit_member(company_id: str, member_id: str, body: MemberEdit) -> dict:
    state = _read_state()
    person = next((item for item in _company(state, company_id).members if item.id == member_id), None)
    if person is None:
        raise HTTPException(status_code=404, detail="Funcionario nao encontrado")
    person.name = body.nome
    person.role = body.cargo or person.role
    _write_state(state)
    return {"ok": True}


@voice_router.delete("/empresa/{company_id}/funcionario/{member_id}")
def dismiss_member(company_id: str, member_id: str) -> dict:
    """Demitir apaga o funcionario e as habilidades dele. Gerentes ficam."""
    state = _read_state()
    company = _company(state, company_id)
    person = next((item for item in company.members if item.id == member_id), None)
    if person is None:
        raise HTTPException(status_code=404, detail="Funcionario nao encontrado")
    if person.kind == "gerente":
        raise HTTPException(status_code=422, detail="Todo setor precisa de um gerente")
    removed = [skill["id"] for skill in store.list_skills(company_id) if skill.get("specialistId") == member_id]
    for skill_id in removed:
        store.delete_skill(company_id, skill_id)
    company.members = [item for item in company.members if item.id != member_id]
    remember_fired(member_id)
    _write_state(state)
    return {"habilidades_apagadas": len(removed)}


@voice_router.get("/imoveis/agente")
def property_agent_panel() -> dict:
    from dodaios.core import property_agent

    return property_agent.panel()


@voice_router.post("/imoveis/agente")
def run_property_agent(body: AgentRun) -> dict:
    from dodaios.core import property_agent

    try:
        property_agent.start(body.salvar)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return property_agent.panel()


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
