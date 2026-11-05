"""O dono ensina a empresa pela conversa; nada vale antes de ele confirmar.

Regra de campo muda o preenchimento do agente. O resto fica como orientacao:
o especialista consulta e o agente usa quando travar.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import unicodedata
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

PENDING_MINUTES: Final[int] = 30
MODEL_TIMEOUT_S: Final[float] = 45.0
MODEL_TOKENS: Final[int] = 500
MAX_FIELDS: Final[int] = 220
MIN_MATCH_WORDS: Final[int] = 2
FILLED_HOW: Final[tuple[str, ...]] = ("texto", "lista", "dinheiro", "opcao")
_OFF: Final[re.Pattern[str]] = re.compile(r"(nao|desmarcar|desmarcado|sem|nunca|false)\b")
_ON: Final[re.Pattern[str]] = re.compile(r"(sim|marcar|marcado|sempre|true)\b")
_ACTION: Final[str] = r"(deve|deves|tem que|precisa|faca|faz|fazer|use|usar|coloque|coloca|colocar|marque|marca|marcar|preencha|preenche|deixe|deixa|pergunte|pergunta|ignore|ignora|clique|clica|sempre|nunca)"
_TEACH: Final[re.Pattern[str]] = re.compile(
    rf"\b(sempre que|toda vez que|da proxima vez|de agora em diante|a partir de agora|aprenda|aprende|anote|guarde isso|grave isso)\b"
    rf"|\bquando\b.*\b{_ACTION}\b|\b(sempre|nunca)\s+{_ACTION}\b")
_LIST: Final[re.Pattern[str]] = re.compile(r"\b(o que|quais)\b.*\b(voce|voces|vc|ja|empresa)\b.*\b(aprendeu|aprenderam)\b|\b(quais|liste|lista|mostre|mostra)\b.*\b(licoes|ensinamentos)\b")
_FORGET: Final[re.Pattern[str]] = re.compile(r"\b(?:esqueca|esquece|apague|apaga|remova|remove)\b.*\b(?:licao|regra|ensinamento)\s*(\d+)")
_NO: Final[re.Pattern[str]] = re.compile(r"(nao|cancela|cancele|deixa|errado)\b")
_LOCK = threading.RLock()


def _fold(text: Any) -> str:
    plain = unicodedata.normalize("NFKD", str(text or ""))
    return " ".join("".join(c for c in plain if not unicodedata.combining(c)).lower().replace("*", "").replace(":", "").split())


def folder() -> Path:
    from dodaios.core.paths import user_data_dir

    return user_data_dir() / "data" / "company_lessons"


def _path(company_id: str) -> Path:
    return folder() / f"{re.sub(r'[^a-zA-Z0-9_-]', '-', company_id)[:80]}.json"


def _read(company_id: str) -> dict[str, Any]:
    try:
        return json.loads(_path(company_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"pendente": None, "licoes": []}


def _write(company_id: str, data: dict[str, Any]) -> None:
    path = _path(company_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=1)
        os.replace(temporary, path)
    except OSError:
        Path(temporary).unlink(missing_ok=True)
        raise


def is_lesson(text: str) -> bool:
    return "?" not in text and bool(_TEACH.search(_fold(text)))


def wants_list(text: str) -> bool:
    return bool(_LIST.search(_fold(text)))


def wants_forget(text: str) -> int | None:
    found = _FORGET.search(_fold(text))
    return int(found.group(1)) if found else None


def is_refusal(text: str) -> bool:
    return bool(_NO.match(_fold(text)))


def known_fields(rules: dict[str, Any], summary: dict[str, Any]) -> list[str]:
    """Nomes de campos que o cadastro conhece: regras e cadastros lidos."""
    names = {name.strip("*: ") for name in rules.get("fixos", {})}
    for item in summary.get("tipos", {}).values():
        names |= {name.strip("*: ") for name in [*item.get("campos", {}), *item.get("marcados", [])]}
    return sorted(names)[:MAX_FIELDS]


def understand(text: str, fields: list[str], kinds: list[str], chat: Any) -> dict[str, Any]:
    """Separa situacao e acao. Sem modelo, a licao fica como o dono escreveu."""
    plain = {"quando": "", "fazer": text.strip(), "campo": "", "valor": "", "tipos": [], "modelo": False}
    prompt = ("Organize este ensinamento do dono de uma imobiliaria. Use somente o que ele disse, sem inventar. Responda so um JSON com: "
              '"quando" (a situacao), "fazer" (o que fazer), "campo" (nome exato da lista abaixo, ou vazio se nao for preencher um campo), '
              '"valor" (valor exato do campo, ou vazio), "tipos" (lista com tipos de imovel entre os permitidos, ou vazia se valer para todos), '
              '"so_tipo" (true somente se a regra vale sempre ou so depende do tipo de imovel; false se depender de qualquer outra condicao).\n'
              f"Tipos permitidos: {', '.join(kinds)}\nCampos: {'; '.join(fields)}\nEnsinamento: {text}")
    try:
        found = json.loads(re.search(r"\{.*\}", chat(prompt, MODEL_TIMEOUT_S, MODEL_TOKENS), re.DOTALL).group(0))
    except Exception:
        return plain
    by_name = {_fold(name): name for name in fields}
    field = by_name.get(_fold(found.get("campo")), "")
    value = str(found.get("valor") or "").strip()
    usable = bool(field and value and found.get("so_tipo"))
    return {"quando": str(found.get("quando") or "").strip(), "fazer": str(found.get("fazer") or "").strip() or text.strip(),
            "campo": field if usable else "", "valor": value if usable else "",
            "tipos": [kind for kind in found.get("tipos") or [] if kind in kinds], "modelo": True}


def describe(lesson: dict[str, Any]) -> str:
    start = f"Quando {lesson['quando'].rstrip('.')}: " if lesson.get("quando") else ""
    scope = f" Vale para: {', '.join(lesson['tipos'])}." if lesson.get("tipos") else ""
    field = f" Preenchimento: {lesson['campo']} = {lesson['valor']}." if lesson.get("campo") else ""
    return f"{start}{lesson['fazer'].rstrip('.')}.{scope}{field}"


def propose(company_id: str, lesson: dict[str, Any], route: dict[str, Any]) -> dict[str, Any]:
    pending = {**lesson, **route, "pedido": datetime.now(UTC).isoformat(timespec="seconds")}
    with _LOCK:
        _write(company_id, {**_read(company_id), "pendente": pending})
    return pending


def pending(company_id: str) -> dict[str, Any] | None:
    item = _read(company_id).get("pendente")
    if not item:
        return None
    fresh = datetime.now(UTC) - datetime.fromisoformat(item["pedido"]) < timedelta(minutes=PENDING_MINUTES)
    return item if fresh else None


def discard(company_id: str) -> None:
    with _LOCK:
        _write(company_id, {**_read(company_id), "pendente": None})


def confirm(company_id: str) -> dict[str, Any] | None:
    with _LOCK:
        data = _read(company_id)
        item = data.get("pendente")
        if not item:
            return None
        lesson = {**item, "quando_ensinou": datetime.now(UTC).isoformat(timespec="seconds")}
        lesson.pop("pedido", None)
        _write(company_id, {"pendente": None, "licoes": [*data.get("licoes", []), lesson]})
    return lesson


def all_lessons(company_id: str) -> list[dict[str, Any]]:
    return _read(company_id).get("licoes", [])


def forget(company_id: str, number: int) -> dict[str, Any] | None:
    with _LOCK:
        data = _read(company_id)
        items = data.get("licoes", [])
        if not 1 <= number <= len(items):
            return None
        removed = items[number - 1]
        _write(company_id, {**data, "licoes": items[:number - 1] + items[number:]})
    return removed


def company_of(prefix: str) -> str:
    """Id completo da empresa a partir do nome curto das regras do cadastro."""
    from dodaios.core.paths import user_data_dir

    found = sorted(path.name for path in (user_data_dir() / "data" / "company_knowledge").glob(f"{prefix}*"))
    return found[0] if found else prefix


def add_confirmed(company_id: str, lesson: dict[str, Any]) -> None:
    """Licao que o dono acabou de aprovar na janela do agente."""
    with _LOCK:
        data = _read(company_id)
        _write(company_id, {**data, "licoes": [*data.get("licoes", []), {**lesson, "quando_ensinou": datetime.now(UTC).isoformat(timespec="seconds")}]})


def for_agent(company: str) -> list[dict[str, Any]]:
    """Licoes da empresa do agente; as de outra empresa nunca entram."""
    found: list[dict[str, Any]] = []
    for path in sorted(folder().glob(f"{re.sub(r'[^a-zA-Z0-9_-]', '-', company)}*.json")):
        try:
            found += json.loads(path.read_text(encoding="utf-8")).get("licoes", [])
        except (OSError, ValueError):
            continue
    return found


def _applies(lesson: dict[str, Any], kind: str) -> bool:
    return not lesson.get("tipos") or kind in lesson["tipos"]


def _set_field(steps: list[dict[str, Any]], lesson: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    """Item de marcar entra ou sai do plano; campo comum troca de valor."""
    name, value = _fold(lesson["campo"]), lesson["valor"]
    same = [step for step in steps if _fold(step["campo"]) == name]
    done = f"Regra do dono aplicada: {lesson['campo']} = {value}."
    if _OFF.match(_fold(value)) and any(step["como"] == "marcar" for step in same):
        return [step for step in steps if not (step in same and step["como"] == "marcar")], done
    if any(step["como"] in FILLED_HOW for step in same):
        return [{**step, "valor": value} if step in same and step["como"] in FILLED_HOW else step for step in steps], done
    if same and _ON.match(_fold(value)):
        return steps, done
    if not same and _ON.match(_fold(value)):
        return [*steps, {"secao": "Detalhes", "campo": lesson["campo"], "como": "marcar", "valor": True, "opcional": True}], done
    return steps, f"Regra do dono sem campo neste cadastro: {lesson['campo']}. Confira."


def apply(items: list[dict[str, Any]], kind: str, steps: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Regra de campo entra no plano; orientacao vai para o relatorio."""
    notes: list[str] = []
    final = list(steps)
    for lesson in items:
        if not _applies(lesson, kind):
            continue
        if not lesson.get("campo"):
            notes.append(f"Ensinamento do dono: {describe(lesson)}")
            continue
        final, note = _set_field(final, lesson)
        notes.append(note)
    return final, notes


def guidance(items: list[dict[str, Any]], kind: str, field: str, problem: str) -> str:
    """Quando o agente trava, procura o que o dono ja ensinou sobre isso."""
    wanted = set(re.findall(r"[a-z0-9]{4,}", _fold(f"{field} {problem}")))
    matches = []
    for lesson in items:
        words = set(re.findall(r"[a-z0-9]{4,}", _fold(f"{lesson.get('quando')} {lesson['fazer']}")))
        if _applies(lesson, kind) and len(wanted & words) >= MIN_MATCH_WORDS:
            matches.append(describe(lesson))
    return " ".join(matches)
