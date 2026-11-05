"""Organiza a empresa em setores e leva cada tarefa ao especialista certo.

Caminho de uma tarefa: Gerente Geral, gerente do setor, especialista. Primeiro
tenta pelas habilidades ensinadas; o modelo so decide quando nada combina.
Todo setor pode consultar os especialistas do Juridico.
"""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Final

from dodaios.core import company_skills as store, knowledge

GENERAL_MANAGER: Final[str] = "gerente-geral"
LEGAL: Final[str] = "juridico"
HOME_SECTOR: Final[str] = "administrativo"
_MODEL_TIMEOUT_S: Final[float] = 180.0
_MODEL_TOKENS: Final[int] = 4000
MAX_NEW_SPECIALISTS: Final[int] = 5
_STOP_WORDS: Final[frozenset[str]] = frozenset("a o as os de da do das dos e em no na nos nas um uma para por com que quando chegar novo nova novos novas fazer faca tarefa".split())
STANDARD_SECTORS: Final[tuple[tuple[str, str, str], ...]] = (
    ("diretoria", "Diretoria", "Prioridades, decisões e coordenação geral."),
    (LEGAL, "Jurídico", "Contratos, documentos, riscos e dúvidas legais de todos os setores."),
    ("financeiro", "Financeiro", "Recebimentos, pagamentos, cobrança e conciliação."),
    (HOME_SECTOR, "Administrativo", "Cadastros, documentos, rotinas internas e organização."),
    ("comercial", "Comercial", "Clientes, vendas, atendimento e negociações."),
)
_MOVES: Final[dict[str, str]] = {"imove": HOME_SECTOR}


def fold(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in plain if not unicodedata.combining(c)).lower()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", fold(text)).strip("-")[:60]


def _words(text: str) -> set[str]:
    return {word.rstrip("s") for word in re.findall(r"[a-z0-9]{3,}", fold(text)) if word not in _STOP_WORDS}


def ensure_structure(company: Any, department: Any, member: Any) -> bool:
    """Regra de todas as empresas: setores padrao, Gerente Geral e um gerente por setor.

    Setores proprios da empresa continuam como estao. Devolve se mudou algo.
    """
    changed = False
    known = {fold(item.name) for item in company.departments} | {item.id for item in company.departments}
    for sector, name, mission in STANDARD_SECTORS:
        if sector not in known and fold(name) not in known:
            company.departments.append(department(id=sector, name=name, floor=len(company.departments) + 1, mission=mission))
            changed = True
    top = next((item for item in company.departments if fold(item.name) == "diretoria"), None)
    if top and not any(item.id == GENERAL_MANAGER or fold(item.role) == "gerente geral" for item in company.members):
        company.members.append(member(id=GENERAL_MANAGER, name="Gerente Geral", role="Gerente Geral", departmentId=top.id, kind="gerente", autonomy="autonomo"))
        changed = True
    managers = {item.departmentId for item in company.members if item.kind == "gerente"}
    for item in company.departments:
        if item.id not in managers:
            company.members.append(member(id=f"gerente-{item.id}"[:120], name=f"Gerente {item.name}"[:120], role="Gerente do setor", departmentId=item.id, kind="gerente", autonomy="autonomo"))
            changed = True
    ids = {fold(item.name): item.id for item in company.departments}
    for skill in store.list_skills(company.id):
        target = next((ids.get(sector, "") for word, sector in _MOVES.items() if word in fold(skill["name"])), "")
        person = next((item for item in company.members if item.id == skill.get("specialistId")), None)
        if person and target and person.departmentId != target and person.kind != "gerente":
            person.departmentId = target
            changed = True
    return changed


def _study(company_id: str, skill_id: str) -> dict[str, Any]:
    state = knowledge.status(company_id, skill_id)
    return {"estado": state["estado"], "fontes": len(state["fontes"]), "oficiais": sum(item["oficial"] for item in state["fontes"]), "trechos": state["trechos"],
            "tema": state.get("tema", ""), "quando": state.get("quando", ""), "lista": [{"titulo": item["titulo"], "url": item["url"], "oficial": item["oficial"]} for item in state["fontes"]][:20]}


def study_topic(company: Any, skill: dict[str, Any]) -> str:
    """O tema que o especialista pesquisa; lei vai pelo nome, o resto com o ramo."""
    name = skill["name"]
    if re.search(r"\b(lei|leis|codigo|decreto|norma|lgpd|clt)\b", fold(name)) or not company.segment:
        return name
    return f"{name} {company.segment}"


def needs_summary(skill: dict[str, Any]) -> bool:
    steps = skill.get("steps", [])
    return not steps or steps[0].startswith("Entender o pedido")


def write_from_study(company_id: str, skill: dict[str, Any]) -> bool:
    """Transforma o que ele estudou em passos e regras. Nunca troca o que foi ensinado."""
    from dodaios.core import photo_vision as vision

    if not needs_summary(skill):
        return True
    hits = knowledge.search(company_id, skill["id"], f"{skill['name']} procedimento passo a passo prazos documentos obrigatorio regras", 12)
    if not hits:
        return True
    context = "\n\n".join(item["texto"] for item in hits)[:12000]
    prompt = (f"Voce e um especialista em {skill['name']}. Usando somente os trechos abaixo, escreva como executar essa funcao. Responda so um JSON: "
              '{"quando_usar": "...", "passos": ["..."], "regras": ["..."]}. Ate 12 passos e 15 regras, com prazos e artigos quando existirem. Nao invente.\n\nTrechos:\n' + context)
    try:
        found = json.loads(re.search(r"\{.*\}", vision._chat(prompt, _MODEL_TIMEOUT_S, _MODEL_TOKENS), re.DOTALL).group(0))
        steps = [str(item) for item in found["passos"] if item][:12]
    except Exception:
        return False
    if not steps:
        return False
    rules = list(dict.fromkeys([*skill.get("rules", []), *[str(item) for item in found.get("regras", []) if item]]))[:17]
    store.update_skill(company_id, skill["id"], {"steps": steps, "rules": rules, "whenToUse": str(found.get("quando_usar") or skill.get("whenToUse", ""))}, "Aprendeu estudando as fontes")
    return True


def manager_of(company: Any, sector: str) -> Any | None:
    return next((item for item in company.members if item.departmentId == sector and item.kind == "gerente"), None)


_CREATE = re.compile(r"\b(?:crie|criar|cria|contrate|contratar|contrata|quero|tenha|precisamos de|preciso de)\s+(?:um |uma |o |a )?(?:novo |nova )?especialista\s+(?:em|de|sobre|na|no|da|do)\s+(.+)$", re.IGNORECASE)
_LEGAL_WORDS = re.compile(r"\b(lei|leis|legal|juridic\w*|direito|contrato\w*|codigo civil|inquilinato|lgpd|tributari\w*)\b")
MIN_COVERAGE: Final[float] = 0.4


def wants_specialist(text: str) -> str:
    """O tema pedido em frases como 'crie um especialista em lei do inquilinato'."""
    found = _CREATE.search(text.strip().rstrip(".!"))
    return found.group(1).strip()[:160] if found else ""


_QUESTION_WORDS: Final[frozenset[str]] = frozenset("qual quais quanto quantos quantas como quando onde quem porque que oque pode posso existe sera devo preciso saber para com uma dos das nos nas sobre tem ter".split())
_QUESTION: Final[re.Pattern[str]] = re.compile(r"^(qual|quais|quanto|quantos|quantas|como|quando|onde|quem|por que|porque|o que|oque|pode|posso|existe|sera|devo|preciso saber)\b")


def is_question(text: str) -> bool:
    plain = fold(text).strip()
    return plain.endswith("?") or bool(_QUESTION.match(plain))


def find_answer(company: Any, question: str) -> dict[str, Any] | None:
    """O Gerente Geral procura em todos os setores quem sabe responder."""
    found = consult(company, question)
    if not found or "nao encontrei" in fold(found["resposta"])[:200]:
        return None
    manager = manager_of(company, found["setor"])
    return {**found, "rota": list(dict.fromkeys(item for item in ("Gerente Geral", manager.name if manager else "", found["especialista"]) if item))}


def plan_new_specialist(company: Any, question: str) -> dict[str, Any]:
    """Decide o assunto e o setor de quem vai aprender a responder."""
    from dodaios.core import photo_vision as vision

    sectors = "; ".join(f"{item.id}: {item.mission}" for item in company.departments if fold(item.name) != "diretoria")
    prompt = (f"Empresa do ramo {company.segment}. Pergunta do dono: {question}\nSetores: {sectors}\n"
              'Responda so um JSON {"especialidade": "assunto curto da funcao", "setor": "id", "internet": true}. '
              "internet e false quando a resposta depende de dados internos da empresa, que nao estao na internet.")
    try:
        found = json.loads(re.search(r"\{.*\}", vision._chat(prompt, 60, _MODEL_TOKENS), re.DOTALL).group(0))
        if str(found.get("especialidade", "")).strip():
            ids = {item.id for item in company.departments}
            return {"tema": str(found["especialidade"]).strip()[:120], "setor": found["setor"] if found.get("setor") in ids else sector_for(company, question), "internet": found.get("internet") is not False}
    except Exception:
        pass
    words = [word for word in re.findall(r"[\wÀ-ÿ]+", question) if fold(word) not in _QUESTION_WORDS and len(word) > 2]
    return {"tema": " ".join(words[:5]) or question[:60], "setor": sector_for(company, question), "internet": True}


def sector_for(company: Any, text: str) -> str:
    if _LEGAL_WORDS.search(fold(text)):
        return _sector_id(company, LEGAL)
    return _ask_sector(company, f"Especialista em {text}")


def consult(company: Any, question: str, exclude_sector: str = "") -> dict[str, Any] | None:
    """Pergunta ao especialista da empresa que tem a melhor fonte para a duvida."""
    best = None
    for skill in store.list_skills(company.id):
        person = next((item for item in company.members if item.id == skill.get("specialistId")), None)
        if not person or person.departmentId == exclude_sector:
            continue
        hits = knowledge.search(company.id, skill["id"], question, 1)
        if hits and hits[0]["cobertura"] >= MIN_COVERAGE and (best is None or hits[0]["pontos"] > best[0]):
            best = (hits[0]["pontos"], skill, person)
    if best is None:
        return None
    result = knowledge.answer(company.id, best[1]["id"], best[2].name, question)
    return {**result, "especialista": best[2].name, "setor": best[2].departmentId}


def organization(company: Any) -> dict[str, Any]:
    skills = store.list_skills(company.id)
    def card(person: Any) -> dict[str, Any]:
        mine = [{"id": skill["id"], "nome": skill["name"], "quando": skill.get("whenToUse", ""), "passos": len(skill.get("steps", [])), "regras": len(skill.get("rules", [])),
                 "listaPassos": skill.get("steps", []), "listaRegras": skill.get("rules", []), "conhecimento": _study(company.id, skill["id"])}
                for skill in skills if skill.get("specialistId") == person.id]
        studying = next((item for item in mine if item["conhecimento"]["estado"] == "pesquisando"), None)
        waiting = next((item for item in mine if item["conhecimento"]["estado"] == "aguardando"), None)
        doing = person.currentTask or (f"Estudando {studying['nome']}" if studying else "Na fila para estudar" if waiting else "")
        return {"id": person.id, "nome": person.name, "cargo": person.role, "tipo": person.kind, "status": "trabalhando" if studying else person.status, "agora": doing,
                "tarefas": [{"titulo": task.title, "status": task.status} for task in company.tasks if task.assigneeId == person.id][:8], "habilidades": mine}

    def team(people: list[Any]) -> list[dict[str, Any]]:
        return [card(person) for person in sorted(people, key=lambda entry: entry.kind != "gerente")]

    sectors = [{"id": item.id, "nome": item.name, "missao": item.mission, "time": team([person for person in company.members if person.departmentId == item.id])} for item in company.departments]
    known = {item.id for item in company.departments}
    loose = [person for person in company.members if person.departmentId not in known]
    if loose:
        sectors.append({"id": "", "nome": "Sem departamento", "missao": "Pessoas ainda sem departamento.", "time": team(loose)})
    return {"empresa": company.name, "setores": sectors}


def _best_skill(company: Any, text: str, member_id: str = "") -> dict[str, Any] | None:
    wanted = _words(text)
    best, score = None, 0.0
    for skill in store.list_skills(company.id):
        if member_id and skill.get("specialistId") != member_id:
            continue
        name = _words(skill["name"])
        hits = len(wanted & name) * 3 + len(wanted & _words(f"{skill.get('whenToUse', '')} {skill.get('category', '')}"))
        if hits > score:
            best, score = skill, hits
    if member_id:
        return best or next((skill for skill in store.list_skills(company.id) if skill.get("specialistId") == member_id), None)
    return best if score >= 3 else None


def _ask_sector(company: Any, text: str) -> str:
    """So chega aqui quando nenhuma habilidade combina."""
    from dodaios.core import photo_vision as vision

    options = "; ".join(f"{item.id}: {item.mission}" for item in company.departments if fold(item.name) != "diretoria")
    prompt = f'Tarefa: {text}\nSetores: {options}\nResponda so um JSON {{"setor": "id"}} com o setor responsavel.'
    try:
        found = json.loads(re.search(r"\{.*?\}", vision._chat(prompt, 60, _MODEL_TOKENS), re.DOTALL).group(0)).get("setor")
    except Exception:
        found = ""
    ids = {item.id for item in company.departments}
    return found if found in ids else _sector_id(company, HOME_SECTOR) or next(iter(ids), "")


def _sector_id(company: Any, name: str) -> str:
    return next((item.id for item in company.departments if fold(item.name) == name or item.id == name), "")


def _legal_note(company: Any, sector: str) -> str:
    legal = _sector_id(company, LEGAL)
    if sector == legal:
        return ""
    ids = {item.id for item in company.members if item.departmentId == legal}
    names = [skill["name"] for skill in store.list_skills(company.id) if skill.get("specialistId") in ids]
    return f"\nEm duvida legal, consulte o Juridico antes de agir.{' Especialidades: ' + ', '.join(names) + '.' if names else ''}"


def lesson_route(company: Any, text: str) -> dict[str, Any]:
    """Quem deve aprender: o especialista da tarefa, passando pelo gerente do setor."""
    skill = _best_skill(company, text)
    if not skill and re.search(r"imove|kenlo|cadastr|codigo|\bfoto", fold(text)):
        skill = next((item for item in store.list_skills(company.id) if "kenlo" in fold(item["name"])), None)
    person = next((item for item in company.members if skill and item.id == skill.get("specialistId")), None)
    sector = person.departmentId if person else _ask_sector(company, text)
    manager = manager_of(company, sector)
    person = person or manager
    chain = list(dict.fromkeys(item for item in ("Gerente Geral", manager.name if manager else "", person.name if person else "") if item))
    return {"rota": chain, "setor": sector, "membro": person.id if person else "", "responsavel": person.name if person else "Gerente Geral",
            "habilidade": (skill or {}).get("id", ""), "agente": bool(skill and re.search(r"imove|kenlo", fold(skill["name"])))}


def route_task(company: Any, text: str, member_id: str = "") -> dict[str, Any]:
    """Decide quem faz a tarefa e monta o pedido para ele."""
    skill = _best_skill(company, text, member_id)
    person = next((item for item in company.members if item.id == (member_id or (skill or {}).get("specialistId"))), None)
    sector = person.departmentId if person else _ask_sector(company, text)
    manager = manager_of(company, sector)
    person = person or manager
    chain = [item for item in ("Gerente Geral", manager.name if manager else "", person.name if person else "") if item]
    chain = list(dict.fromkeys(chain))
    context = store.skill_prompt([skill]) if skill else ""
    studied = bool(skill and person and knowledge.status(company.id, skill["id"])["trechos"])
    prompt = (f"Empresa: {company.name}. Voce e {person.name if person else 'o responsavel'}, {person.role if person else ''}.\n"
              f"{context}\nTarefa pedida pelo dono: {text}{_legal_note(company, sector)}")
    route = {"rota": chain, "setor": sector, "membro": person.id if person else "", "habilidade": (skill or {}).get("id", ""),
             "agente": bool(skill and re.search(r"imove", fold(skill["name"]))), "prompt": prompt}
    if studied:
        route.update(knowledge.answer(company.id, skill["id"], person.name, text))
        return route
    # Duvida que outro setor sabe responder: pergunta a ele antes de agir.
    consulted = consult(company, text, sector)
    if consulted and consulted["encontrou"]:
        route["consulta"] = {key: consulted[key] for key in ("especialista", "resposta", "fontes")}
        route["prompt"] += f"\n\nConsulta a {consulted['especialista']}:\n{consulted['resposta']}\nFontes: {', '.join(consulted['fontes'])}"
    return route


_STARTER_RULES: Final[list[str]] = ["Perguntar ao gerente quando faltar informação.", "Não enviar nada a clientes sem autorização."]
_STARTER_TEAMS: Final[dict[str, tuple[tuple[str, str], ...]]] = {
    "diretoria": (("Acompanhamento de prioridades", "Quando for preciso saber o que está atrasado ou o que vem primeiro"), ("Relatório da empresa", "Quando pedirem um resumo do andamento dos setores")),
    "juridico": (("Revisão de contratos", "Quando chegar um contrato ou aditivo para conferir"), ("Conferência de documentos", "Quando for preciso conferir documentos de clientes ou imoveis")),
    "financeiro": (("Contas a receber e cobrança", "Quando houver valor a receber ou atrasado"), ("Contas a pagar", "Quando chegar uma conta ou repasse a pagar"), ("Conciliação bancária", "Quando for preciso conferir pagamentos com o extrato")),
    "administrativo": (("Organização de documentos", "Quando chegarem documentos para guardar ou encontrar"), ("Atualização de cadastros", "Quando um dado de cliente ou imovel mudar")),
    "comercial": (("Atendimento de clientes", "Quando um cliente pedir informação ou atendimento"), ("Acompanhamento de negociações", "Quando houver proposta ou negociação em andamento")),
    "locacoes": (("Contratos de locação", "Quando houver locação nova ou renovação"), ("Vistorias", "Quando for preciso marcar ou registrar uma vistoria"), ("Desocupações", "Quando um inquilino avisar que vai sair")),
}


def _starter_team(sector: Any) -> list[dict[str, Any]]:
    """Funcoes basicas do setor, para o gerente nao depender do modelo."""
    functions = _STARTER_TEAMS.get(fold(sector.name).strip(), ())
    return [{"nome": name, "quando_usar": when, "regras": _STARTER_RULES, "passos": [f"Entender o pedido: {name}.", "Conferir as informações recebidas.", "Executar e informar o resultado ao gerente."], "base": True}
            for name, when in functions]


def _ask_model(prompt: str, sector: Any) -> list[dict[str, Any]]:
    from dodaios.core import photo_vision as vision

    try:
        text = vision._chat(prompt, _MODEL_TIMEOUT_S, _MODEL_TOKENS)
        return json.loads(re.search(r"\[.*\]", text, re.DOTALL).group(0))
    except Exception:
        return _starter_team(sector)


def propose_team(company: Any, sector_id: str) -> list[dict[str, Any]]:
    """O gerente pergunta ao modelo o que o setor faz; sem ele, usa as funcoes basicas."""
    sector = next(item for item in company.departments if item.id == sector_id)
    current = [skill["name"] for skill in store.list_skills(company.id)]
    advice = consult(company, f"{sector.name} {sector.mission}", sector_id)
    note = f"\nOrientacao de {advice['especialista']}: {advice['resposta']}\n" if advice and advice["encontrou"] else ""
    prompt = (f"Voce e gerente do setor {sector.name} de {company.name}, ramo {company.segment}. Missao do setor: {sector.mission}\n"
              f"Ja existem estes especialistas: {', '.join(current) or 'nenhum'}.{note}\n"
              f"Liste ate {MAX_NEW_SPECIALISTS} funcoes reais que faltam neste setor. Responda so um JSON: "
              '[{"nome": "...", "quando_usar": "...", "passos": ["..."], "regras": ["..."]}]. Nao invente sistemas, numeros ou leis.')
    found = _ask_model(prompt, sector)
    known = {fold(name) for name in current} | {fold(person.name.removeprefix("Especialista em ")) for person in company.members}
    return [item for item in found if isinstance(item, dict) and item.get("nome") and fold(item["nome"]) not in known][:MAX_NEW_SPECIALISTS]
