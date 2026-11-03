"""Habilidades aprendidas por empresa, portaveis entre Mac e Windows.

Cada habilidade e um arquivo JSON proprio em ``data/company_skills/<empresa>/``.
Guarda conhecimento, nunca caminhos, portas ou credenciais da maquina. Toda
alteracao sobe a versao e registra o valor anterior, entao ensinar de novo nunca
apaga o que ja foi aprendido.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
import unicodedata
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from urllib.parse import quote

_LOCK = threading.Lock()
_MAX_HISTORY: Final[int] = 200
_MAX_PROMPT_CHARS: Final[int] = 2_500
_MIN_MATCH_SCORE: Final[int] = 3
_SYNC_INTERVAL_S: Final[float] = 30.0
_last_sync = 0.0
_NAME_WEIGHT: Final[int] = 3
_LIST_FIELDS: Final[tuple[str, ...]] = ("steps", "rules", "conditions", "exceptions", "validation")
_TEXT_FIELDS: Final[tuple[str, ...]] = (
    "name", "category", "whenToUse", "procedure", "managerId", "specialistId", "platform",
)
_STOPWORDS: Final[frozenset[str]] = frozenset(
    "para pela pelo como quero fazer faca essa esse esta este uma umas uns com sem "
    "dos das nos nas que por favor agora".split()
)


class SkillNotFound(LookupError):
    """A habilidade pedida nao existe nesta empresa."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _root() -> Path:
    from dodaios.core.paths import user_data_dir

    return user_data_dir() / "data" / "company_skills"


def _company_dir(company_id: str) -> Path:
    name = quote(company_id, safe="")
    if not name or name in (".", ".."):
        raise ValueError("empresa invalida")
    return _root() / name


def _path(company_id: str, skill_id: str) -> Path:
    if not re.fullmatch(r"[a-z0-9-]{1,80}", skill_id):
        raise SkillNotFound(skill_id)
    return _company_dir(company_id) / f"{skill_id}.json"


def _fold(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in plain if not unicodedata.combining(c)).lower()


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", _fold(name)).strip("-")[:60]
    return f"{slug or 'habilidade'}-{uuid.uuid4().hex[:6]}"


def _shared_root() -> Path:
    """A pasta que o Syncthing mantem igual entre Mac e Windows."""
    return Path.home() / ".dodaios-sync" / "company_skills"


def sync_skills(*, force: bool = False) -> int:
    """Copia entre as maquinas a versao mais nova de cada habilidade.

    Fica sem efeito onde a pasta compartilhada nao existe. Duas edicoes da mesma
    versao em maquinas diferentes guardam a outra como ``.conflito``, para que
    nada ensinado se perca. Devolve quantos arquivos foram copiados.
    """
    global _last_sync
    shared = _shared_root()
    if not shared.parent.is_dir() or (not force and time.monotonic() - _last_sync < _SYNC_INTERVAL_S):
        return 0
    _last_sync = time.monotonic()
    local = _root()
    copied = 0
    with _LOCK:
        names = {p.relative_to(local) for p in local.glob("*/*.json")} if local.is_dir() else set()
        names |= {p.relative_to(shared) for p in shared.glob("*/*.json")} if shared.is_dir() else set()
        for name in names:
            mine, theirs = local / name, shared / name
            try:
                ours = _read(mine) if mine.is_file() else None
                other = _read(theirs) if theirs.is_file() else None
            except ValueError:
                continue
            if ours == other:
                continue
            if ours is None or other is None:
                source, target = (theirs, mine) if ours is None else (mine, theirs)
            else:
                rank_ours = (ours.get("version", 0), ours.get("updatedAt", ""))
                rank_other = (other.get("version", 0), other.get("updatedAt", ""))
                source, target = (mine, theirs) if rank_ours >= rank_other else (theirs, mine)
                if ours.get("version") == other.get("version"):
                    loser = _read(target)
                    keep = target.with_suffix(f".conflito-{loser.get('updatedAt', 'x')[:19].replace(':', '')}")
                    keep.write_text(json.dumps(loser, ensure_ascii=False, indent=2), encoding="utf-8")
            _write(target, _read(source))
            copied += 1
    return copied


def _member_names(company_id: str) -> dict[str, str]:
    from dodaios.core.paths import user_data_dir

    try:
        state = json.loads((user_data_dir() / "data" / "companies.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    for company in state.get("companies", []):
        if company.get("id") == company_id:
            return {m.get("id"): m.get("name", "") for m in company.get("members", [])}
    return {}


def _route_line(skill: dict[str, Any]) -> str:
    """A cadeia de responsaveis, para a tarefa nao ficar presa a uma pessoa."""
    names = _member_names(skill.get("companyId", ""))
    chain = [f"empresa {skill.get('company')}"]
    if "gerente-geral" in names:
        chain.append(names["gerente-geral"])
    chain += [names[key] for key in (skill.get("managerId"), skill.get("specialistId")) if names.get(key)]
    return "Encaminhamento: " + " -> ".join(dict.fromkeys(chain))


def _write(path: Path, skill: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as output:
            json.dump(skill, output, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _read(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SkillNotFound(path.stem) from exc


def _record(skill: dict[str, Any], change: str, previous: dict[str, Any]) -> None:
    skill["version"] += 1
    skill["updatedAt"] = _now()
    skill["history"].append(
        {"version": skill["version"], "at": skill["updatedAt"], "change": change, "previous": previous}
    )
    del skill["history"][: -_MAX_HISTORY]


def _clean_list(values: Any) -> list[str]:
    return [str(value).strip() for value in values or () if str(value).strip()]


def archive_company(company_id: str, company: dict[str, Any]) -> str:
    """Guarda a empresa e as habilidades antes de apagar; devolve o nome da copia."""
    folder = _root().parent / "company_backups"
    name = f"{quote(company_id, safe='')}-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.json"
    _write(folder / name, {"company": company, "skills": list_skills(company_id)})
    return name


def list_skills(company_id: str) -> list[dict[str, Any]]:
    sync_skills()
    folder = _company_dir(company_id)
    if not folder.is_dir():
        return []
    skills = [_read(path) for path in sorted(folder.glob("*.json"))]
    return sorted(skills, key=lambda item: item.get("updatedAt", ""), reverse=True)


def get_skill(company_id: str, skill_id: str) -> dict[str, Any]:
    return _read(_path(company_id, skill_id))


def create_skill(company_id: str, company_name: str, data: dict[str, Any]) -> dict[str, Any]:
    name = str(data.get("name") or "").strip()
    if not name:
        raise ValueError("a habilidade precisa de um nome")
    now = _now()
    skill: dict[str, Any] = {
        "id": _slug(name),
        "companyId": company_id,
        "company": company_name,
        "category": "",
        "whenToUse": "",
        "procedure": "",
        "managerId": "",
        "specialistId": "",
        "platform": "todas",
        "steps": [],
        "rules": [],
        "conditions": [],
        "exceptions": [],
        "validation": [],
        "examples": [],
        "corrections": [],
        "version": 1,
        "createdAt": now,
        "updatedAt": now,
        "history": [{"version": 1, "at": now, "change": "Habilidade criada", "previous": {}}],
    }
    skill.update({key: str(data[key]).strip() for key in _TEXT_FIELDS if data.get(key) is not None})
    skill.update({key: _clean_list(data[key]) for key in _LIST_FIELDS if data.get(key) is not None})
    with _LOCK:
        _write(_path(company_id, skill["id"]), skill)
    return skill


def update_skill(company_id: str, skill_id: str, changes: dict[str, Any], note: str = "") -> dict[str, Any]:
    with _LOCK:
        path = _path(company_id, skill_id)
        skill = _read(path)
        previous: dict[str, Any] = {}
        for key in (*_TEXT_FIELDS, *_LIST_FIELDS):
            if changes.get(key) is None:
                continue
            value = _clean_list(changes[key]) if key in _LIST_FIELDS else str(changes[key]).strip()
            if value != skill.get(key):
                previous[key] = skill.get(key)
                skill[key] = value
        if not skill.get("name"):
            raise ValueError("a habilidade precisa de um nome")
        if previous:
            _record(skill, note.strip() or "Procedimento atualizado", previous)
            _write(path, skill)
        return skill


def delete_skill(company_id: str, skill_id: str) -> None:
    """Apaga a habilidade de vez, aqui e na pasta compartilhada, sem copia."""
    with _LOCK:
        path = _path(company_id, skill_id)
        if not path.is_file():
            raise SkillNotFound(skill_id)
        for folder in (path.parent, _shared_root() / path.parent.name):
            for item in folder.glob(f"{skill_id}.*"):
                item.unlink()


def add_example(company_id: str, skill_id: str, example: dict[str, Any]) -> dict[str, Any]:
    situation = str(example.get("situation") or "").strip()
    if not situation:
        raise ValueError("descreva a situacao do exemplo")
    with _LOCK:
        path = _path(company_id, skill_id)
        skill = _read(path)
        skill["examples"].append(
            {
                "situation": situation,
                "outcome": str(example.get("outcome") or "").strip(),
                "kind": str(example.get("kind") or "normal").strip(),
                "at": _now(),
            }
        )
        _record(skill, f"Exemplo {len(skill['examples'])} adicionado", {})
        _write(path, skill)
        return skill


def add_correction(company_id: str, skill_id: str, text: str) -> dict[str, Any]:
    clean = (text or "").strip()
    if not clean:
        raise ValueError("descreva a correcao")
    with _LOCK:
        path = _path(company_id, skill_id)
        skill = _read(path)
        skill["corrections"].append({"text": clean, "at": _now()})
        _record(skill, "Correcao registrada", {})
        _write(path, skill)
        return skill


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]{3,}", _fold(text)) if w not in _STOPWORDS}


def matching_skills(text: str, limit: int = 2) -> list[dict[str, Any]]:
    """As habilidades de qualquer empresa que combinam com o pedido."""
    sync_skills()
    root = _root()
    if not root.is_dir():
        return []
    wanted = _words(text)
    scored: list[tuple[int, str, dict[str, Any]]] = []
    for path in root.glob("*/*.json"):
        try:
            skill = _read(path)
        except (OSError, ValueError, SkillNotFound):
            continue
        name_hits = len(wanted & _words(skill.get("name", "")))
        score = name_hits * _NAME_WEIGHT + len(wanted & _words(skill.get("whenToUse", "")))
        if wanted & _words(skill.get("company", "")):
            score += 1
        if score >= _MIN_MATCH_SCORE:
            scored.append((score, skill.get("updatedAt", ""), skill))
    scored.sort(key=lambda item: item[:2], reverse=True)
    return [item[2] for item in scored[:limit]]


def skill_prompt(skills: list[dict[str, Any]]) -> str:
    """O texto que o assistente recebe; correcoes vem antes por terem prioridade."""
    blocks = []
    for skill in skills:
        lines = [f"Habilidade \"{skill.get('name')}\" da empresa {skill.get('company')} (v{skill.get('version')})."]
        lines.append(_route_line(skill))
        if skill.get("whenToUse"):
            lines.append(f"Quando usar: {skill['whenToUse']}")
        lines += [f"Correcao do dono (prioridade): {c['text']}" for c in skill.get("corrections", [])[-8:]]
        if skill.get("procedure"):
            lines.append(f"Procedimento: {skill['procedure']}")
        lines += [f"{n}. {step}" for n, step in enumerate(skill.get("steps", []), 1)]
        lines += [f"Decisao conforme o caso: {item}" for item in skill.get("conditions", [])]
        lines += [f"Regra: {rule}" for rule in skill.get("rules", [])]
        lines += [f"Excecao: {item}" for item in skill.get("exceptions", [])]
        lines += [
            f"Exemplo ({e.get('kind', 'normal')}): {e['situation']} -> {e.get('outcome', '')}"
            for e in skill.get("examples", [])[-4:]
        ]
        lines += [f"Validar: {item}" for item in skill.get("validation", [])]
        blocks.append("\n".join(lines)[:_MAX_PROMPT_CHARS])
    if not blocks:
        return ""
    head = (
        "HABILIDADES APRENDIDAS. Antes de executar, identifique qual caso se aplica "
        "e qual decisao ele exige; se nao der para saber, pergunte. Siga o procedimento "
        "ensinado, prefira localizar elementos por texto e estrutura da tela e valide "
        "o resultado no final."
    )
    return head + "\n\n" + "\n\n".join(blocks)


def prepend_skills(prompt: str, text: str) -> str:
    """Acrescenta ao prompt as habilidades do pedido. Nunca derruba o turno."""
    try:
        block = skill_prompt(matching_skills(text))
    except (OSError, ValueError):
        return prompt
    return f"{block}\n\n{prompt}" if block and prompt else (block or prompt)
