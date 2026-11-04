"""Transforma a ficha de um imovel na lista de campos do cadastro.

O formato do formulario fica aqui; os valores fixos de cada empresa ficam num
arquivo local em ``data/imoveis/regras-cadastro.json``, fora do repositorio.
Quem executa e o agente em ``bridge/ja-kenlo-cadastro.py``.
"""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Any, Final

NEW_PROPERTY_URL: Final[str] = "https://imob.valuegaia.com.br/admin/default.aspx#/modules/imoveis_beta/imovel-novo.aspx?acao=incluir"
KIND_LABELS: Final[dict[str, tuple[str, str]]] = {
    "pavilhao": ("Comercial", "Pavilhão"), "apartamento": ("Residencial", "Apartamento"), "casa": ("Residencial", "Casa"),
    "sala": ("Comercial", "Sala"), "loja": ("Comercial", "Loja"), "predio": ("Comercial", "Prédio"), "terreno": ("Comercial", "Terreno"),
}
AD_REQUEST: Final[str] = ("Gere um texto para utilizarmos como anuncio no meu site deste imovel, nao coloque endereco, valor e proprietario. "
                          "Neste caso e {kind} para {purpose}. Use somente os dados abaixo, sem inventar nada e sem marcacao.")


def rules_path():
    from dodaios.core.paths import user_data_dir

    return user_data_dir() / "data" / "imoveis" / "regras-cadastro.json"


def load_rules() -> dict[str, Any]:
    return json.loads(rules_path().read_text(encoding="utf-8"))


def _step(section: str, field: str, how: str, value: Any = "") -> dict[str, Any]:
    return {"secao": section, "campo": field, "como": how, "valor": value}


def _fixed(rules: dict[str, Any], section: str, *fields: tuple[str, str]) -> list[dict[str, Any]]:
    values = rules["fixos"]
    return [_step(section, field, how, values[field]) for field, how in fields if field in values]


def _complement(item: dict[str, Any], sheet: dict[str, Any], rules: dict[str, Any]) -> str:
    if item.get("tipo") == "apartamento" and sheet["apartamento"]:
        return sheet["apartamento"]
    if item.get("condominio") and (sheet["lote"] or sheet["quadra"]):
        return " ".join(part for part in (f"Lote {sheet['lote']}" if sheet["lote"] else "", f"Quadra {sheet['quadra']}" if sheet["quadra"] else "") if part)
    return rules["fixos"].get("Complemento:", "")


def build_plan(item: dict[str, Any], sheet: dict[str, Any], rules: dict[str, Any], ad_text: str, today: date | None = None) -> dict[str, Any]:
    """Campos em ordem de tela e a lista do que o dono precisa conferir."""
    today = today or date.today()
    fixed = rules["fixos"]
    minimum = fixed["valor_minimo"]
    check: list[str] = []
    missing = [name for name, value in (("logradouro", sheet["logradouro"]), ("numero", sheet["numero"]), ("cidade", sheet["cidade"]),
                                        ("proprietario", sheet["proprietario"]), ("telefone", sheet["telefone"]),
                                        ("area", sheet["area_construida"] or sheet["area_terreno"]),
                                        ("valor", sheet["locacao"] or sheet["venda"])) if not value]
    purpose, kind_label = KIND_LABELS.get(item.get("tipo", ""), ("", ""))
    if item.get("finalidade") == "residencial":
        purpose = "Residencial"
    if not kind_label:
        missing.append("tipo")
    steps = [
        _step("Proprietário", "*Tel. Residencial:", "telefone", sheet["telefone"]),
        _step("Proprietário", "*Nome do proprietário:", "nome", sheet["proprietario"]),
        *_fixed(rules, "Proprietário", ("*Mídia de origem:", "lista")),
        _step("Estrutura", "*Finalidade:", "lista", purpose),
        _step("Estrutura", "*Tipo:", "lista", kind_label),
        _step("Localização do imóvel", "Cidade:", "lista", sheet["cidade"]),
        _step("Localização do imóvel", "Logradouro:", "logradouro", {"rua": sheet["logradouro"], "bairro": sheet["bairro"]}),
        _step("Localização do imóvel", "Número", "texto", sheet["numero"]),
        _step("Localização do imóvel", "Complemento:", "texto", _complement(item, sheet, rules)),
    ]
    section = "Características"
    if sheet["venda"]:
        steps += [_step(section, "Venda", "marcar", True), _step(section, "*Valor de venda:", "dinheiro", sheet["venda"])]
        check.append("Venda ainda nao foi ensinada no video: confira os campos de venda.")
    if sheet["locacao"]:
        steps += [_step(section, "Locação", "marcar", True), _step(section, "*Valor de locação:", "dinheiro", sheet["locacao"])]
        steps += _fixed(rules, section, ("Tipo de Locação:", "lista"), ("*Taxa de Administração (%):", "texto"))
    steps += [_step(section, "Valor do condomínio:", "dinheiro", sheet["condominio_valor"] or minimum)]
    steps += _fixed(rules, section, ("Condição de pagamento IPTU / ITR:", "lista"))
    steps += [_step(section, "Valor IPTU / ITR:", "dinheiro", sheet["iptu"] or minimum)]
    if sheet["locacao"]:
        steps += [_step(section, "Valor do Seguro Fiança", "dinheiro", minimum), _step(section, "Valor do seguro incêndio:", "dinheiro", minimum)]
    steps += _fixed(rules, section, ("Padrão:", "lista"), ("Padrão da localização:", "lista"), ("Situação do imóvel:", "lista"))
    year = sheet["ano_construcao"] or str(today.year)
    steps += [_step(section, "Ano de construção:", "texto", year), _step(section, "Ano de reforma:", "texto", year)]
    steps += _fixed(rules, section, ("Usou FGTS nos últimos 3 anos?", "lista"), ("Aceita financiamento:", "lista"), ("Zoneamento:", "texto"))
    steps += [_step(section, "Valor de venda avaliado pela imobiliária:", "dinheiro", minimum),
              _step(section, "Valor de locação avaliado pela imobiliária:", "dinheiro", minimum),
              _step(section, "Data da avaliação:", "texto", today.strftime("%d/%m/%Y"))]
    if sheet["locacao"]:
        steps += [_step(section, name, "marcar", True) for name in rules["garantias"]]
    section = "Detalhes"
    built = sheet["area_construida"] or sheet["area_terreno"]
    land = sheet["area_terreno"] or built
    steps += [_step(section, "*Área do terreno:", "texto", land), _step(section, "*Área construída:", "texto", built)]
    steps += _fixed(rules, section, ("Isolamento:", "lista"), ("Modo Isolamento:", "lista"), ("Posição solar/Face:", "lista"), ("Topografia:", "lista"))
    check.append(f"Topografia marcada como {fixed.get('Topografia:', '')}: confira pelas fotos.")
    steps += [_step(section, name, "marcar", True) for name in rules["infraestrutura"]]
    if item.get("tipo") == "pavilhao":
        height = sheet["pe_direito"] or fixed.get("pe_direito_pavilhao", "")
        if not sheet["pe_direito"]:
            check.append(f"Pe-direito estimado em {height} m: ajuste se souber a medida.")
        steps += [_step(section, "Altura do pé direito", "texto", height), _step(section, "Pavimentação", "marcar", True)]
        steps += _fixed(rules, section, ("Tipo de pavimentação", "lista"))
    if sheet["docas"]:
        check.append(f"A ficha cita {sheet['docas']} docas e a opcao Doca ficou desmarcada: marque se este imovel tiver.")
    if sheet["mobiliado"]:
        steps.append(_step(section, "Mobiliado", "marcar", True))
    steps.append(_step(section, "Nº de andares", "texto", sheet["andares"] or fixed.get("andares_padrao", "1")))
    if sheet["vagas"]:
        steps += [_step(section, "Vagas cobertas", "texto", "0"), _step(section, "Vagas descobertas", "texto", sheet["vagas"])]
        steps += _fixed(rules, section, ("Tipo de vaga", "lista"), ("Característica da vaga", "lista"))
    if sheet["banheiros"]:
        steps.append(_step(section, "Nº de banheiros", "texto", sheet["banheiros"]))
    steps += [_step(section, name, "marcar", True) for name in rules["piso"]]
    steps.append(_step("Fotos", "Fotos", "fotos"))
    section = "Publicação na web"
    steps += _fixed(rules, section, ("Anunciar:", "lista"), ("Comunicar proprietário:", "lista"), ("Imóvel em destaque:", "lista"), ("Imóvel em super destaque:", "lista"))
    steps += [_step(section, "gerar sugestão", "clicar")]
    steps += _fixed(rules, section, ("Usar título no meu site?", "opcao"))
    steps += [_step(section, "Todos", "marcar", True), _step(section, "Descrição do Site (diferenciais e detalhes do imóvel):", "texto_longo", ad_text)]
    steps += _fixed(rules, "Placas e faixas", ("Placa no local:", "lista"))
    section = "Comissões e condições"
    steps += _fixed(rules, section, ("*Tipo de Comissão:", "lista"), ("*Corretor:", "lista"))
    steps += [_step(section, "ADICIONAR", "clicar")]
    empty = [step["campo"] for step in steps if step["valor"] == "" and step["como"] not in ("clicar", "fotos")]
    return {"passos": [step for step in steps if step["campo"] not in empty], "faltando": missing + empty, "conferir": check}


def ad_prompt(item: dict[str, Any], sheet: dict[str, Any]) -> str:
    """Mesmo pedido do dono, levando so os dados que podem ir no anuncio."""
    kind = {"pavilhao": "um pavilhao", "casa": "uma casa", "apartamento": "um apartamento", "sala": "uma sala comercial",
            "loja": "uma loja", "terreno": "um terreno", "predio": "um predio"}.get(item.get("tipo", ""), "um imovel")
    purpose = "locacao" if sheet["locacao"] and not sheet["venda"] else "venda" if sheet["venda"] and not sheet["locacao"] else "venda e locacao"
    facts = {"Bairro": sheet["bairro"], "Cidade": sheet["cidade"], "Area": f"{sheet['area_construida']} m2" if sheet["area_construida"] else "",
             "Docas": sheet["docas"], "Rampas": sheet["rampas"], "Banheiros": sheet["banheiros"], "Vagas": sheet["vagas"],
             "Dormitorios": sheet["dormitorios"], "Suites": sheet["suites"]}
    return AD_REQUEST.format(kind=kind, purpose=purpose) + "\n" + "\n".join(f"{name}: {value}" for name, value in facts.items() if value)


def clean_ad(text: str, sheet: dict[str, Any]) -> str:
    """Tira marcacao; devolve vazio se vazou dado que nao pode aparecer."""
    plain = re.sub(r"\*+|^#+\s*", "", text or "", flags=re.MULTILINE).strip()
    banned = [sheet["logradouro"], sheet["proprietario"], sheet["telefone"], sheet["locacao"], sheet["venda"], sheet["iptu"]]
    folded = plain.lower()
    leaked = any(value and value.lower() in folded for value in banned) or "r$" in folded
    return "" if leaked or len(plain) < 80 else plain


def template_ad(item: dict[str, Any], sheet: dict[str, Any], company: str) -> str:
    """Anuncio feito so com os dados da ficha, quando o modelo nao responde."""
    name = {"pavilhao": "Pavilhão", "casa": "Casa", "apartamento": "Apartamento", "sala": "Sala comercial", "loja": "Loja",
            "terreno": "Terreno", "predio": "Prédio"}.get(item.get("tipo", ""), "Imóvel")
    place = ", ".join(part for part in (sheet["bairro"], sheet["cidade"]) if part)
    lines = [f"{name} para {'locação' if sheet['locacao'] else 'venda'}{f' em {place}' if place else ''}."]
    facts = [f"{sheet['area_construida']} m² de área útil" if sheet["area_construida"] else "", f"{sheet['dormitorios']} dormitórios" if sheet["dormitorios"] else "",
             f"{sheet['suites']} suítes" if sheet["suites"] else "", f"{sheet['docas']} docas" if sheet["docas"] else "",
             f"{sheet['rampas']} rampas de acesso" if sheet["rampas"] else "", f"{sheet['banheiros']} banheiros" if sheet["banheiros"] else "",
             f"{sheet['vagas']} vagas" if sheet["vagas"] else ""]
    lines += [f"- {fact}" for fact in facts if fact]
    lines.append(f"Entre em contato com a {company} e agende uma visita.")
    return "\n".join(lines)
