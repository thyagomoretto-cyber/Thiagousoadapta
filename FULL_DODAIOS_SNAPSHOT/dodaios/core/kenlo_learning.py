"""Aprende com o cadastro final do dono: compara o que o agente preencheu com o Kenlo.

So os campos que vem das regras viram proposta. Preco, area e dados do imovel
mudam a cada cadastro e nunca viram regra. Nada muda sem o dono aprovar.
"""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Final

COMPARED_HOW: Final[tuple[str, ...]] = ("texto", "lista", "dinheiro")
MAX_TRIES: Final[int] = 3
SEEN_TO_ASK: Final[int] = 2


def _fold(text: Any) -> str:
    plain = unicodedata.normalize("NFKD", str(text or ""))
    return " ".join("".join(c for c in plain if not unicodedata.combining(c)).lower().replace("*", "").replace(":", "").split())


def _same(left: Any, right: Any) -> bool:
    first, second = _fold(left), _fold(right)
    if first == second:
        return True
    try:
        return float(first.replace(".", "").replace(",", ".")) == float(second.replace(".", "").replace(",", "."))
    except ValueError:
        return False


def snapshot(steps: list[dict[str, Any]]) -> dict[str, str]:
    """O que o agente preencheu, para comparar depois."""
    return {_fold(step["campo"]): str(step["valor"]) for step in steps if step["como"] in COMPARED_HOW and step["valor"] not in ("", None)}


def boxes(steps: list[dict[str, Any]]) -> list[str]:
    """Caixas que o agente marcou, para ver depois o que o dono mudou."""
    return [step["campo"] for step in steps if step["como"] in ("marcar", "mobilia")]


def box_changes(filled: list[str], final: list[str], known: tuple[str, ...]) -> list[tuple[str, str]]:
    """Itens que o dono tirou ou colocou; so os que o agente decide sozinho."""
    mine, kept, allowed = set(filled), set(final), set(known)
    return sorted((name, "tirou") for name in (mine - kept) & allowed) + sorted((name, "colocou") for name in (kept - mine) & allowed)


def tally(seen: dict[str, int], kind: str, changes: list[tuple[str, str]]) -> tuple[dict[str, int], list[tuple[str, str]]]:
    """Conta as correcoes; a mesma correcao repetida vira pergunta ao dono."""
    counts = dict(seen)
    ready = []
    for name, action in changes:
        key = f"{kind}|{name}|{action}"
        counts[key] = counts.get(key, 0) + 1
        if counts[key] == SEEN_TO_ASK:
            ready.append((name, action))
    return counts, ready


def differences(filled: dict[str, str], rules: dict[str, Any], final: dict[str, Any]) -> list[dict[str, str]]:
    """Campos de regra que o dono mudou depois do preenchimento."""
    labels = {_fold(name): name for name in rules.get("fixos", {})}
    current = {_fold(name): value for name, value in final.items()}
    changes = []
    for name, value in filled.items():
        if name in labels and name in current and not _same(value, current[name]):
            changes.append({"campo": labels[name], "agente": value, "kenlo": str(current[name])})
    return changes


def remember(rules: dict[str, Any], kind: str, field: str, value: str) -> dict[str, Any]:
    """Regra aprovada pelo dono para aquele tipo de imovel."""
    return {**rules, "por_tipo": {**rules.get("por_tipo", {}), kind: {**rules.get("por_tipo", {}).get(kind, {}), field: value}}}


def rules_for(rules: dict[str, Any], kind: str, suggested: dict[str, str] | None = None) -> dict[str, Any]:
    """Regras gerais, sugestoes de imoveis parecidos e, acima de tudo, o que o dono aprovou."""
    return {**rules, "fixos": {**rules.get("fixos", {}), **(suggested or {}), **rules.get("por_tipo", {}).get(kind, {})}}


def waiting(items: list[dict[str, Any]], first_code: int, code_of: Any) -> list[dict[str, Any]]:
    """Imoveis ja finalizados que ainda nao foram comparados."""
    found = []
    for item in items:
        code = code_of(item["chave"])
        finished = item.get("status") == "cadastrado" or (code is not None and code < first_code)
        if finished and item.get("preenchido") and not item.get("comparado") and int(item.get("tentativas", 0)) < MAX_TRIES:
            found.append(item)
    return found


def answer_is_yes(reply: str) -> bool:
    plain = _fold(reply)
    return bool(reply) and bool(re.match(r"(sim|sempre|pode|isso|faca|faz)\b", plain))


def dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)
