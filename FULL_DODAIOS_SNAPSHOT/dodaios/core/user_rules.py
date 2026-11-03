from __future__ import annotations

import json
from pathlib import Path

STATE = Path.home() / ".dodaios"
GLOBAL = STATE / "global"
PROFILES = STATE / "profiles"
ACTIVE = STATE / "active_profile.json"
MULTIUSER = GLOBAL / "multiuser.json"
NATIVE_RULES = GLOBAL / "native_rules.json"
PUBLISHER_MARKER = GLOBAL / "publicador.json"
PUBLISHER_SCRIPT = STATE / "bridge" / "ja-publicar.py"

# Regras de fabrica: valem em todas as instalacoes, Mac e Windows.
SHIPPED_RULES = (
    "Ao receber um pedido: 1) interprete o que foi pedido; 2) verifique se ja sabe "
    "fazer, olhando skills, ferramentas e memoria; 3) se nao souber, pesquise como "
    "fazer e execute; 4) confira o resultado de verdade antes de dizer que terminou.",
    "Se algo falhar, leia o erro, descubra a causa, corrija a causa e continue ate "
    "finalizar o pedido. Tente outro caminho em vez de repetir o que falhou. Depois de "
    "tres caminhos diferentes sem sucesso, pare e diga exatamente o que bloqueou.",
    "Autonomia nao libera riscos: peca confirmacao antes de apagar dados, enviar "
    "mensagens, gastar dinheiro ou fazer algo irreversivel. Nunca grave tokens, senhas "
    "ou chaves em codigo ou no repositorio, e nunca sobrescreva configuracoes locais.",
)
PUBLISHER_RULE = (
    "Esta e a maquina publicadora. Se voce corrigiu o codigo do DodaiOS, confira que o "
    "app funciona e publique para todos com: {python} {script} --mensagem \"o que "
    "mudou\" --arquivo caminho/relativo/ao/pacote.py (repita --arquivo por arquivo). "
    "So considere publicado se a saida trouxer PUBLICADO=. Nunca use outro meio de envio."
)
RECEIVER_RULE = (
    "Esta maquina so recebe atualizacoes: nunca envie nada ao GitHub. Se corrigir o "
    "codigo do DodaiOS aqui, avise qual arquivo mudou, para ser publicado pelo Mac do Thiago."
)


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def active_profile_id() -> str:
    data = _read_json(ACTIVE, {})
    return str(data.get("profile_id") or "thiago")


def administrator_profile_id() -> str:
    data = _read_json(MULTIUSER, {})
    return str(data.get("administrator_profile") or "thiago")


def active_profile_role() -> str:
    pid = active_profile_id()
    data = _read_json(PROFILES / pid / "profile.json", {})
    return str(data.get("role") or ("administrator" if pid == administrator_profile_id() else "user"))


def native_rules() -> list[str]:
    data = _read_json(NATIVE_RULES, {})
    rows = data.get("rules", [])
    if not isinstance(rows, list):
        return []
    return [str(x).strip() for x in rows if str(x).strip()]


def profile_rules(profile_id: str | None = None) -> list[str]:
    pid = profile_id or active_profile_id()
    data = _read_json(PROFILES / pid / "rules.json", {})
    rows = data.get("rules", [])
    if not isinstance(rows, list):
        return []
    return [str(x).strip() for x in rows if str(x).strip()]


def shipped_rules() -> list[str]:
    """Regras de fabrica; so o administrador da maquina publicadora publica."""
    if PUBLISHER_MARKER.is_file() and active_profile_role() == "administrator":
        python = STATE / ".venv" / "bin" / "python"
        last = PUBLISHER_RULE.format(python=python, script=PUBLISHER_SCRIPT)
    else:
        last = RECEIVER_RULE
    return [*SHIPPED_RULES, last]


def merged_rules(profile_id: str | None = None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for rule in [*shipped_rules(), *native_rules(), *profile_rules(profile_id)]:
        rule = rule.strip()
        if rule and rule not in seen:
            seen.add(rule)
            result.append(rule)

    return result


def rules_prompt(profile_id: str | None = None) -> str:
    rules = merged_rules(profile_id)
    if not rules:
        return ""

    body = "\n".join(f"- {rule}" for rule in rules)

    return (
        "REGRAS PERMANENTES DO DODAIOS\n"
        "Estas regras fazem parte da configuração persistente do aplicativo. "
        "As regras globais têm precedência sobre preferências comuns do perfil.\n\n"
        f"{body}"
    )


def prepend_rules(prompt: str, profile_id: str | None = None) -> str:
    rules = rules_prompt(profile_id)
    prompt = prompt or ""

    if not rules:
        return prompt

    if rules in prompt:
        return prompt

    if not prompt:
        return rules

    return rules + "\n\n" + prompt
