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

from dodaios.core import kenlo_learning as learning
from dodaios.core.photo_order import FLOORS, VISIBLE_ITEMS
from dodaios.core.property_sheet import _fold

NEW_PROPERTY_URL: Final[str] = "https://imob.valuegaia.com.br/admin/default.aspx#/modules/imoveis_beta/imovel-novo.aspx?acao=incluir"
KIND_LABELS: Final[dict[str, tuple[str, str]]] = {
    "pavilhao": ("Comercial", "Pavilhão"), "apartamento": ("Residencial", "Apartamento"), "casa": ("Residencial", "Casa"),
    "sala": ("Comercial", "Sala"), "loja": ("Comercial", "Loja"), "predio": ("Comercial", "Prédio"), "terreno": ("Comercial", "Terreno"),
}
ROOM_KINDS: Final[tuple[str, ...]] = ("casa", "apartamento")
USEFUL_AREA: Final[tuple[str, ...]] = ("sala", "loja", "predio")
INTERCOM: Final[tuple[str, ...]] = ("sala", "predio")
REQUIRED_COUNTS: Final[dict[str, tuple[str, ...]]] = {"casa": ("dormitorios", "banheiros"), "apartamento": ("dormitorios", "banheiros"), "sala": ("banheiros",), "loja": ("banheiros",), "predio": ("banheiros",)}
COUNTED: Final[tuple[tuple[str, str], ...]] = (("dormitorios", "dormitórios"), ("suites", "suítes"), ("vagas", "vagas"), ("banheiros", "banheiros"))
ITEM_WORDS: Final[dict[str, str]] = {"Ar condicionado": r"ar[- ]condicionado|\bsplit\b", "Calefação": r"calefac", "Depósito": r"deposito", "Divisória": r"divisoria",
                                     "Elevador": r"elevador", "Gerador": r"gerador", "Portão eletrônico": r"portao eletronico", "Mobiliado": r"(?<!semi)(?<!semi-)mobiliad", "Semi-Mobiliado": r"semi-?mobiliad", "Aquecimento de água à gás": r"aquecimento.{0,20}gas|gas central",
                                     "Área de serviço": r"area de servico", "Pé direito duplo": r"pe[- ]direito duplo"}
ELEVATOR_ABOVE: Final[int] = 4
AD_REQUEST: Final[str] = ("Gere um texto para utilizarmos como anuncio no meu site deste imovel, nao coloque endereco, valor e proprietario. "
                          "Neste caso e {kind} para {purpose}. Comece pelo maior diferencial e destaque todos os pontos fortes, em texto persuasivo e facil de ler. "
                          "Use somente os dados abaixo, sem inventar nada e sem marcacao.")


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


def _optional(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Nem todo tipo de imovel mostra este campo: se nao existir, segue."""
    return [{**step, "opcional": True} for step in steps]


def condo_rules(sheet: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    """O que a empresa ja ensinou sobre o condominio da ficha."""
    name = _fold(sheet.get("condominio_nome", ""))
    return next((value for key, value in rules.get("condominios", {}).items() if name and _fold(key) in name), {})


def complete_sheet(item: dict[str, Any], sheet: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    """Completa a ficha com o que vale sempre naquele condominio."""
    condo = condo_rules(sheet, rules)
    if not condo:
        return sheet
    filled = {**sheet}
    for field in ("andares", "suites", "banheiros"):
        filled[field] = sheet[field] or condo.get(field, "")
    by_area = condo.get("dormitorios_por_area")
    if not sheet["dormitorios"] and by_area:
        area = float((sheet["area_construida"] or "0").replace(".", "").replace(",", "."))
        filled["dormitorios"] = by_area["acima"] if area > by_area["limite"] else by_area["ate"]
    return filled


def floor_of(apartment: str) -> str:
    """Apartamento 404 fica no 4o andar; 1203 no 12o."""
    return apartment[:-2].lstrip("0") if len(apartment) >= 3 else ""


def _apartment_details(sheet: dict[str, Any], rules: dict[str, Any], check: list[str]) -> list[dict[str, Any]]:
    section = "Detalhes"
    general = rules.get("apartamento", {})
    condo = condo_rules(sheet, rules)
    built = sheet["area_construida"] or sheet["area_terreno"]
    boxes = list(dict.fromkeys([*general.get("caixas", []), *condo.get("caixas", [])]))
    steps = [_step(section, "Área total:", "texto", sheet["area_terreno"] or built), _step(section, "*Área útil:", "texto", built),
             _step(section, "Altura do pé direito", "texto", sheet["pe_direito"] or general.get("pe_direito", ""))]
    steps += [_step(section, name, "marcar", True) for name in boxes]
    if sheet["mobiliado"]:
        steps.append(_step(section, "Mobiliado", "marcar", True))
    steps += [_step(section, "Nº de andares", "texto", sheet["andares"]), _step(section, "Nº do andar", "texto", floor_of(sheet["apartamento"])),
              _step(section, "Nº de salas", "texto", general.get("salas", "")), _step(section, "*Dormitórios", "texto", sheet["dormitorios"]),
              _step(section, "Suites", "lista", sheet["suites"]), _step(section, "Nº de banheiros", "texto", sheet["banheiros"])]
    if not condo:
        check.append("Condomínio sem regras salvas: confira nas fotos elevador, lazer, gás e demais caixas.")
    return [step for step in steps if step["valor"] != "" or step["campo"] == "*Dormitórios"]


def floor_steps(item: dict[str, Any], sheet: dict[str, Any], rules: dict[str, Any], check: list[str]) -> list[dict[str, Any]]:
    """O piso vem da ficha, das fotos ou das regras; sem certeza, pergunta ao dono."""
    section = "Detalhes"
    seen = sheet.get("pisos_fotos", [])
    if seen and not sheet.get("pisos"):
        check.append(f"Piso identificado pelas fotos: {', '.join(seen)}. Confira.")
    condo = condo_rules(sheet, rules)
    fallback = rules["piso"] if item.get("tipo") == "pavilhao" else rules.get("apartamento", {}).get("piso", []) if item.get("tipo") == "apartamento" else []
    # Cada piso da ficha ou das fotos e marcado: o imovel pode ter mais de um.
    names = list(dict.fromkeys([*sheet.get("pisos", []), *seen])) or condo.get("piso") or fallback
    if not names:
        return [_step(section, "Piso", "perguntar_piso", list(FLOORS))]
    return [_step(section, name, "marcar", True) for name in names]


def compare_with_photos(sheet: dict[str, Any], details: dict[str, Any]) -> list[str]:
    """Confere as quantidades da ficha com as fotos."""
    differences = []
    for field, name in COUNTED:
        written = int(re.sub(r"\D", "", str(sheet.get(field) or "")) or 0)
        seen = int(details.get("contagens", {}).get(field) or 0)
        if written and seen > written:
            differences.append(f"a ficha diz {written} {name} e as fotos mostram {seen}")
    return differences


def fill_counts(sheet: dict[str, Any], details: dict[str, Any], check: list[str], item_kind: str = "") -> dict[str, Any]:
    """A ficha nao informou: usa a quantidade vista nas fotos e pede conferencia."""
    filled = {**sheet}
    for field, name in COUNTED:
        seen = int(details.get("contagens", {}).get(field) or 0)
        if seen and not sheet.get(field):
            filled[field] = str(seen)
            check.append(f"{name.capitalize()}: {seen}, pelas fotos. Confira.")
    return apply_room_rules(item_kind, filled, check)


def apply_room_rules(kind: str, sheet: dict[str, Any], check: list[str]) -> dict[str, Any]:
    """Sem suite, vale zero; cada suite tem banheiro, entao ha pelo menos um por suite."""
    if kind not in ROOM_KINDS:
        return sheet
    filled = {**sheet, "suites": sheet.get("suites") or "0"}
    suites = int(re.sub(r"\D", "", filled["suites"]) or 0)
    baths = int(re.sub(r"\D", "", str(filled.get("banheiros") or "")) or 0)
    if suites > baths:
        filled["banheiros"] = str(suites)
        check.append(f"Banheiros ajustados para {suites}: cada suíte tem pelo menos um.")
    return filled


def missing_counts(item: dict[str, Any], sheet: dict[str, Any]) -> list[tuple[str, str]]:
    """Quantidades obrigatorias que nem a ficha nem as fotos trouxeram."""
    return [(field, name) for field, name in COUNTED if field in REQUIRED_COUNTS.get(item.get("tipo", ""), ()) and not sheet.get(field)]


def written_items(item: dict[str, Any], sheet: dict[str, Any]) -> list[str]:
    """Itens citados na ficha ou no texto do imovel."""
    text = _fold(f"{item.get('texto', '')} {item.get('titulo', '')}")
    return [name for name in VISIBLE_ITEMS if re.search(ITEM_WORDS.get(name, re.escape(_fold(name))), text)]


def needs_elevator(sheet: dict[str, Any]) -> list[str]:
    """Predio com mais de 4 andares sempre tem elevador."""
    floors = [str(sheet.get("andares") or ""), str(sheet.get("andar") or ""), floor_of(str(sheet.get("apartamento") or ""))]
    return ["Elevador"] if max(int(re.sub(r"\D", "", value) or 0) for value in floors) > ELEVATOR_ABOVE else []


def seen_items(sheet: dict[str, Any], check: list[str]) -> list[dict[str, Any]]:
    """Itens vistos nas fotos: marca se o campo existir e pede conferencia."""
    items = list(dict.fromkeys([*sheet.get("itens_ficha", []), *sheet.get("itens_fotos", []), *sheet.get("itens_condominio", []), *needs_elevator(sheet)]))
    if items:
        check.append(f"Marcado pela ficha e pelas fotos: {', '.join(items)}. Confira.")
    return [{**_step("Detalhes", name, "marcar", True), "opcional": True} for name in items]


def furnished_rooms(sheet: dict[str, Any], check: list[str]) -> list[dict[str, Any]]:
    """Imovel mobiliado: marca cada ambiente em que as fotos mostram moveis."""
    rooms = sheet.get("mobilia_ambientes", []) if sheet.get("mobiliado") else []
    if rooms:
        check.append(f"Ambientes com mobília nas fotos: {', '.join(rooms)}. Confira.")
    return [{**_step("Detalhes", name, "mobilia", True), "opcional": True} for name in rooms]


def _parking(sheet: dict[str, Any], rules: dict[str, Any]) -> list[dict[str, Any]]:
    if not sheet["vagas"]:
        return []
    section = "Detalhes"
    covered = sheet["vagas_cobertas"] or "0"
    open_air = sheet["vagas_descobertas"] or ("0" if sheet["vagas_cobertas"] else sheet["vagas"])
    return [_step(section, "Vagas cobertas", "texto", covered), _step(section, "Vagas descobertas", "texto", open_air),
            *_fixed(rules, section, ("Tipo de vaga", "lista"), ("Característica da vaga", "lista"))]


def _complement(item: dict[str, Any], sheet: dict[str, Any], rules: dict[str, Any]) -> str:
    if item.get("tipo") == "apartamento" and sheet["apartamento"]:
        return sheet["apartamento"]
    if item.get("condominio") and (sheet["lote"] or sheet["quadra"]):
        return " ".join(part for part in (f"Lote {sheet['lote']}" if sheet["lote"] else "", f"Quadra {sheet['quadra']}" if sheet["quadra"] else "") if part)
    return rules["fixos"].get("Complemento:", "")


def build_plan(item: dict[str, Any], sheet: dict[str, Any], rules: dict[str, Any], ad_text: str, today: date | None = None) -> dict[str, Any]:
    """Campos em ordem de tela e a lista do que o dono precisa conferir."""
    today = today or date.today()
    rules = learning.rules_for(rules, item.get("tipo", ""), sheet.get("sugestoes", {}).get("campos"))
    sheet = complete_sheet(item, sheet, rules)
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
    ]
    if sheet["condominio_nome"]:
        # Achando o condominio, o Kenlo preenche o endereco sozinho.
        steps.append(_step("Estrutura", "Nome do condomínio/edifício:", "condominio", {"busca": sheet["condominio_nome"], "rua": sheet["logradouro"], "bairro": sheet["bairro"], "cidade": sheet["cidade"]}))
    address = [_step("Localização do imóvel", "Cidade:", "lista", sheet["cidade"]),
               _step("Localização do imóvel", "Logradouro:", "logradouro", {"rua": sheet["logradouro"], "bairro": sheet["bairro"], "cep": sheet.get("cep", "")}),
               _step("Localização do imóvel", "Número", "texto", sheet["numero"])]
    steps += [{**step, "sem_condominio": True} for step in address]
    steps.append(_step("Localização do imóvel", "Complemento:", "texto", _complement(item, sheet, rules)))
    section = "Características"
    if sheet["venda"]:
        steps += [_step(section, "Venda", "marcar", True), _step(section, "*Valor de venda:", "dinheiro", sheet["venda"])]
        check.append("Venda ainda nao foi ensinada no video: confira os campos de venda.")
    if sheet["locacao"]:
        steps += [_step(section, "Locação", "marcar", True), _step(section, "*Valor de locação:", "dinheiro", sheet["locacao"])]
        steps += _fixed(rules, section, ("Tipo de Locação:", "lista"))
    rent_only = _fixed(rules, section, ("*Taxa de Administração (%):", "texto"))
    steps += rent_only if sheet["locacao"] else _optional(rent_only)
    condo_fee = [_step(section, "Valor do condomínio:", "dinheiro", sheet["condominio_valor"] or minimum)]
    steps += condo_fee if sheet["condominio_valor"] else _optional(condo_fee)
    steps += _fixed(rules, section, ("Condição de pagamento IPTU / ITR:", "lista"))
    steps += [_step(section, "Valor IPTU / ITR:", "dinheiro", sheet["iptu"] or minimum)]
    insurance = [_step(section, "Valor do Seguro Fiança", "dinheiro", minimum), _step(section, "Valor do seguro incêndio:", "dinheiro", minimum)]
    steps += insurance if sheet["locacao"] else _optional(insurance)
    steps += _fixed(rules, section, ("Padrão:", "lista"), ("Padrão da localização:", "lista"), ("Situação do imóvel:", "lista"))
    steps += _optional(_fixed(rules, section, ("Exclusividade:", "lista")))
    year = sheet["ano_construcao"] or str(today.year)
    steps += [_step(section, "Ano de construção:", "texto", year), _step(section, "Ano de reforma:", "texto", year)]
    steps += _fixed(rules, section, ("Usou FGTS nos últimos 3 anos?", "lista"), ("Aceita financiamento:", "lista"), ("Zoneamento:", "texto"))
    steps += [_step(section, "Valor de venda avaliado pela imobiliária:", "dinheiro", minimum),
              _step(section, "Valor de locação avaliado pela imobiliária:", "dinheiro", minimum),
              _step(section, "Data da avaliação:", "texto", today.strftime("%d/%m/%Y"))]
    if sheet["locacao"]:
        steps += [_step(section, name, "marcar", True) for name in rules["garantias"]]
    if item.get("tipo") == "apartamento":
        steps += _apartment_details(sheet, rules, check) + _parking(sheet, rules)
    else:
        section = "Detalhes"
        built = sheet["area_construida"] or sheet["area_terreno"]
        land = sheet["area_terreno"] or built
        if item.get("tipo") in USEFUL_AREA:
            steps += [_step(section, "Área total:", "texto", land), _step(section, "*Área útil:", "texto", built), *_optional([_step(section, "Área Privativa", "texto", built)])]
        else:
            steps += [_step(section, "*Área do terreno:", "texto", land), _step(section, "*Área construída:", "texto", built)]
        steps += _fixed(rules, section, ("Isolamento:", "lista"), ("Modo Isolamento:", "lista"), ("Posição solar/Face:", "lista"), ("Topografia:", "lista"))
        check.append(f"Topografia marcada como {fixed.get('Topografia:', '')}: confira pelas fotos.")
        if item.get("tipo") == "pavilhao":
            steps += [_step(section, name, "marcar", True) for name in rules["infraestrutura"]]
        if item.get("tipo") in INTERCOM:
            steps.append(_step(section, "Interfone", "marcar", True))
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
        steps += _parking(sheet, rules)
        if item.get("tipo") == "casa":
            steps += [_step(section, "*Dormitórios", "texto", sheet["dormitorios"]), _step(section, "Suites", "lista", sheet["suites"] or "0")]
        if sheet["banheiros"]:
            steps.append(_step(section, "Nº de banheiros", "texto", sheet["banheiros"]))
    steps += seen_items(sheet, check) + furnished_rooms(sheet, check) + floor_steps(item, sheet, rules, check)
    steps.append(_step("Fotos", "Fotos", "fotos"))
    section = "Publicação na web"
    steps += _fixed(rules, section, ("Anunciar:", "lista"), ("Comunicar proprietário:", "lista"), ("Imóvel em destaque:", "lista"), ("Imóvel em super destaque:", "lista"))
    steps += _optional(_fixed(rules, section, ("Publicar valor no site:", "lista")))
    steps += [_step(section, "gerar sugestão", "clicar")]
    steps += _fixed(rules, section, ("Usar título no meu site?", "opcao"))
    steps += [_step(section, "Todos", "marcar", True), _step(section, "Descrição do Site (diferenciais e detalhes do imóvel):", "texto_longo", ad_text)]
    steps += _fixed(rules, "Placas e faixas", ("Placa no local:", "lista"))
    section = "Comissões e condições"
    steps += _fixed(rules, section, ("*Tipo de Comissão:", "lista"), ("*Corretor:", "lista"))
    if sheet.get("observacao"):
        check.append(f"Observação da ficha, fora do anúncio: {sheet['observacao']}")
    if sheet.get("andar") and item.get("tipo") != "apartamento":
        place = next(i for i, step in enumerate(steps) if step["campo"] == "Nº de andares")
        if not sheet["andares"]:
            steps[place]["valor"] = sheet["andar"]
        steps.insert(place + 1, _step("Detalhes", "Nº do andar", "texto", sheet["andar"]))
    empty = [step["campo"] for step in steps if step["valor"] == "" and step["como"] not in ("clicar", "fotos")]
    return {"passos": [step for step in steps if step["campo"] not in empty], "faltando": missing + empty, "conferir": check}


def ad_prompt(item: dict[str, Any], sheet: dict[str, Any], rules: dict[str, Any] | None = None) -> str:
    """Mesmo pedido do dono, levando so os dados que podem ir no anuncio."""
    kind = {"pavilhao": "um pavilhao", "casa": "uma casa", "apartamento": "um apartamento", "sala": "uma sala comercial",
            "loja": "uma loja", "terreno": "um terreno", "predio": "um predio"}.get(item.get("tipo", ""), "um imovel")
    purpose = "locacao" if sheet["locacao"] and not sheet["venda"] else "venda" if sheet["venda"] and not sheet["locacao"] else "venda e locacao"
    facts = {"Condominio": sheet.get("condominio_nome", ""), "Bairro": sheet["bairro"], "Cidade": sheet["cidade"], "Area": f"{sheet['area_construida']} m2" if sheet["area_construida"] else "",
             "Docas": sheet["docas"], "Rampas": sheet["rampas"], "Banheiros": sheet["banheiros"], "Vagas": sheet["vagas"],
             "Dormitorios": sheet["dormitorios"], "Suites": sheet["suites"],
             "Piso": ", ".join(sheet.get("pisos") or sheet.get("pisos_fotos", [])),
             "Diferenciais": ", ".join([*condo_rules(sheet, rules or {}).get("caixas", []), *sheet.get("itens_ficha", []), *sheet.get("itens_fotos", [])])}
    return AD_REQUEST.format(kind=kind, purpose=purpose) + "\n" + "\n".join(f"{name}: {value}" for name, value in facts.items() if value)


def clean_ad(text: str, sheet: dict[str, Any]) -> str:
    """Tira marcacao; devolve vazio se vazou dado que nao pode aparecer."""
    plain = re.sub(r"\*+|^#+\s*", "", text or "", flags=re.MULTILINE).strip()
    banned = [sheet["logradouro"], sheet["proprietario"], sheet["telefone"], sheet["locacao"], sheet["venda"], sheet["iptu"]]
    folded = plain.lower()
    leaked = any(value and value.lower() in folded for value in banned) or "r$" in folded
    return "" if leaked or len(plain) < 80 else plain


def template_ad(item: dict[str, Any], sheet: dict[str, Any], company: str, rules: dict[str, Any] | None = None) -> str:
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
    lines += [f"- {extra}" for extra in condo_rules(sheet, rules or {}).get("caixas", [])]
    lines.append(f"Entre em contato com a {company} e agende uma visita.")
    return "\n".join(lines)
