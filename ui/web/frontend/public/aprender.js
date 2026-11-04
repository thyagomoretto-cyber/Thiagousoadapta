// Modo de aprendizado: painel simples, sem etapa de build, dentro do Empresas.
(function () {
  "use strict";
  const WORKSPACE = '[data-testid="companies-workspace"]';
  const state = { companyId: null, companies: [], skills: [], skill: null, error: "", teach: null };
  let panel = null;

  async function api(path, options) {
    const init = options ? { method: options.method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(options.body) } : undefined;
    const response = await fetch(path, init);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : `Erro ${response.status}`);
    return payload;
  }

  function el(tag, props, children) {
    const node = document.createElement(tag);
    Object.entries(props || {}).forEach(([key, value]) => {
      if (key === "style") Object.assign(node.style, value);
      else if (key === "onclick") node.addEventListener("click", value);
      else if (key === "onchange") node.addEventListener("change", value);
      else node[key] = value;
    });
    (children || []).forEach((child) => { if (child) node.append(child); });
    return node;
  }

  const colors = { text: "hsl(var(--foreground))", muted: "hsl(var(--muted-foreground))", line: "hsl(var(--border))", bg: "hsl(var(--background))", card: "hsl(var(--card))", main: "hsl(var(--primary))", onMain: "hsl(var(--primary-foreground))" };
  const fieldStyle = { width: "100%", boxSizing: "border-box", padding: "8px 10px", border: `1px solid ${colors.line}`, borderRadius: "8px", background: colors.card, color: colors.text, font: "inherit", fontSize: "13px" };
  const button = (label, onclick, primary) => el("button", { type: "button", textContent: label, onclick, style: { padding: "7px 12px", borderRadius: "8px", border: `1px solid ${primary ? colors.main : colors.line}`, background: primary ? colors.main : "transparent", color: primary ? colors.onMain : colors.text, font: "inherit", fontSize: "12px", cursor: "pointer" } });
  const label = (text) => el("div", { textContent: text, style: { margin: "14px 0 5px", fontSize: "12px", color: colors.muted } });
  const title = (text) => el("h3", { textContent: text, style: { margin: "20px 0 6px", fontSize: "14px", fontWeight: "600" } });
  const row = (children) => el("div", { style: { display: "flex", flexWrap: "wrap", gap: "8px", marginTop: "10px" } }, children);
  const input = (value, name) => el("input", { value: value || "", name, style: fieldStyle });
  const area = (value, name, rows) => el("textarea", { value: value || "", name, rows: rows || 3, style: { ...fieldStyle, resize: "vertical" } });
  const lines = (node) => node.value.split("\n").map((line) => line.trim()).filter(Boolean);

  function members(kindFilter) {
    const company = state.companies.find((item) => item.id === state.companyId);
    return (company ? company.members : []).filter(kindFilter);
  }

  function memberSelect(value, name, kindFilter) {
    const options = [el("option", { value: "", textContent: "A definir" })];
    members(kindFilter).forEach((member) => options.push(el("option", { value: member.id, textContent: `${member.name} · ${member.role}` })));
    const select = el("select", { name, style: fieldStyle }, options);
    select.value = value || "";
    return select;
  }

  async function guarded(action) {
    state.error = "";
    try { await action(); } catch (error) { state.error = error.message || "Falha"; }
    render();
  }

  async function loadCompany(companyId) {
    state.companyId = companyId;
    state.skill = null;
    state.skills = companyId ? (await api(`/api/companies/${encodeURIComponent(companyId)}/skills`)).skills : [];
  }

  const skillsUrl = (suffix) => `/api/companies/${encodeURIComponent(state.companyId)}/skills${suffix || ""}`;

  async function saved(skill) {
    state.skill = skill;
    state.skills = (await api(skillsUrl())).skills;
  }

  async function startSession(skill) {
    const catalog = await api("/api/agent-chat/catalog?surface=jarvis");
    const pick = catalog.selection || { provider: "local-openai", model: "", effort: "" };
    const session = await api("/api/agent-chat/sessions", { method: "POST", body: { provider: pick.provider, model: pick.model || "", effort: pick.effort || "", account_id: pick.account_id || "", surface: "jarvis", title: `Ensinar: ${skill.name}` } });
    return session.session_id;
  }

  const TEACH_RULES = "Estou ensinando esta tarefa. Execute cada instrucao com as ferramentas, na tela, e pergunte quando tiver duvida. Prefira localizar elementos por texto, rotulo e estrutura da pagina; use coordenadas so como ultimo recurso. Nunca adivinhe link, nome, senha ou dado: se faltar algo, pare e faca uma pergunta curta. Esta e uma conversa por voz: fale de forma natural, em poucas frases, como nas nossas conversas normais, e responda tambem ao que eu comentar. Quando o caminho mudar conforme o caso, como um imovel comercial ou residencial, pergunte como identificar e registre a decisao. No fim de cada resposta, liste o que aprendeu em linhas neste formato exato: PASSO: texto / REGRA: texto / CONDICAO: se tal caso, entao fazer tal coisa / EXCECAO: texto / VALIDAR: texto / EXEMPLO: situacao => resultado.";

  const VOICE_RULES = "Estou ensinando por voz. Os comandos de tela sao feitos por outro modulo, entao aqui voce so conversa comigo, em poucas frases. Nunca diga que abriu, clicou, digitou ou fez algo, porque voce nao opera a tela nesta conversa. Se eu pedir uma acao, responda: Nao consegui executar, diga clique em e o texto exato da tela. Nunca adivinhe link, nome ou dado; se faltar algo, faca uma pergunta curta.";

  async function sendTeach(text, alreadyLogged) {
    const teach = state.teach;
    if (!alreadyLogged) teach.log.push({ who: "Você", text });
    teach.busy = true;
    render();
    try {
      await runTeachTurn(teach, text);
      const last = teach.log[teach.log.length - 1];
      if (alreadyLogged && last.who === "Ele") {
        const spoken = last.text.split("\n").filter((line) => !/^\W*(PASSO|REGRA|CONDICAO|EXCECAO|VALIDAR|EXEMPLO):/.test(line)).join(" ").trim();
        if (spoken) await api("/api/company-voice/ensino/falar", { method: "POST", body: { text: spoken } });
      }
    } finally {
      teach.busy = false;
    }
  }

  async function runTeachTurn(teach, text) {
    const skill = state.skill;
    const first = !teach.session;
    if (first) teach.session = await startSession(skill);
    const context = first ? `${teach.live ? VOICE_RULES : TEACH_RULES}\nHabilidade: ${skill.name}. Empresa: ${skill.company}. Passos ja aprendidos: ${skill.steps.join("; ") || "nenhum"}.\n\n` : "";
    const sent = await api(`/api/agent-chat/sessions/${teach.session}/messages`, { method: "POST", body: { text: context + text } });
    for (let tries = 0; tries < 300; tries += 1) {
      await new Promise((done) => setTimeout(done, 2000));
      if (state.teach !== teach) return;
      const data = await api(`/api/agent-chat/sessions/${teach.session}?tail=200`);
      const events = data.events || [];
      const ours = (event) => (event.payload || {}).turn_id === sent.turn_id;
      if (events.some((event) => event.kind === "approval_required" && ours(event)) && !teach.warned) {
        teach.warned = true;
        state.notice = `Ele pediu permissão. Aprove no chat "Ensinar: ${skill.name}".`;
        render();
      }
      if (events.some((event) => event.kind === "turn_finished" && ours(event))) {
        const reply = events.filter((event) => event.kind === "assistant_text" && ours(event)).map((event) => event.payload.text).join("\n");
        teach.log.push({ who: "Ele", text: reply || "Terminou sem resposta." });
        // Por voz, so passos executados ou observados entram na habilidade.
        if (!teach.live) reply.split("\n").forEach((line) => {
          const found = line.match(/^\W*(PASSO|REGRA|CONDICAO|EXCECAO|VALIDAR|EXEMPLO):\W*(.+)$/);
          if (found && !/\*\*/.test(found[2])) teach.learned.push({ kind: found[1], text: found[2].trim() });
        });
        // Registra a cada passo, para nada se perder se o ensino parar no meio.
        if (teach.learned.length) await saveLearned();
        return;
      }
    }
    throw new Error("Ele demorou demais para responder. Veja o chat do ensino.");
  }

  // Uma conversa nova por imovel: o historico de um nao pesa no proximo.
  async function askAgent(skill, text, batch) {
    const session = await startSession(skill);
    const url = `/api/agent-chat/sessions/${session}`;
    const sent = await api(`${url}/messages`, { method: "POST", body: { text } });
    for (let tries = 0; tries < 900 && !batch.stop; tries += 1) {
      await new Promise((done) => setTimeout(done, 2000));
      const events = (await api(`${url}?tail=200`)).events || [];
      const ours = (event) => (event.payload || {}).turn_id === sent.turn_id;
      if (events.some((event) => event.kind === "turn_finished" && ours(event))) {
        return events.filter((event) => event.kind === "assistant_text" && ours(event)).map((event) => event.payload.text).join("\n");
      }
    }
    return "";
  }

  function batchPrompt(skill, item) {
    const place = item.condominio ? "em condomínio" : "fora de condomínio";
    return [`Cadastre um imóvel usando a habilidade "${skill.name}" da empresa ${skill.company}.`,
      `Classificação: ${item.tipo}, ${item.finalidade}, ${place}.`, `Texto recebido:\n${item.texto}`,
      `Fotos: ${(item.fotos || []).join(", ") || "nenhuma"}.`,
      "Antes de cadastrar, procure no sistema se o imóvel já existe. Confira o cadastro no final.",
      "Termine com uma linha exata: RESULTADO: CADASTRADO, ou RESULTADO: JA EXISTE, ou RESULTADO: REVISAR e o motivo."].join("\n");
  }

  async function runBatch(skill) {
    const batch = { stop: false, done: 0, existed: 0, review: 0 };
    state.batch = batch;
    render();
    for (;;) {
      const item = (await api("/api/company-voice/imoveis")).proximo;
      if (!item || batch.stop) break;
      batch.current = item.texto.split("\n")[0];
      render();
      const reply = await askAgent(skill, batchPrompt(skill, item), batch);
      if (batch.stop) break;
      const result = (reply.match(/RESULTADO:\s*(CADASTRADO|JA EXISTE|REVISAR)(.*)/i) || []);
      const verdict = (result[1] || "").toUpperCase();
      const status = verdict === "CADASTRADO" || verdict === "JA EXISTE" ? "cadastrado" : "revisar";
      await api(`/api/company-voice/imoveis/${encodeURIComponent(item.chave)}/situacao`, { method: "POST", body: { status, note: verdict ? `${verdict}${result[2] || ""}`.trim() : "Sem resultado claro do assistente" } });
      if (verdict === "CADASTRADO") batch.done += 1; else if (verdict === "JA EXISTE") batch.existed += 1; else batch.review += 1;
    }
    state.batch = null;
    state.notice = `Lote encerrado: ${batch.done} cadastrados, ${batch.existed} já existiam, ${batch.review} para revisar.`;
  }

  function askGroup() {
    ask("Nome exato do grupo do WhatsApp", async (grupo) => {
      state.notice = "";
      state.reading = true;
      render();
      try {
        const result = await api("/api/company-voice/imoveis/ler", { method: "POST", body: { grupo } });
        state.notice = `Grupo lido: ${result.novos} novos, ${result.ja_conhecidos} já conhecidos, ${result.fotos} fotos.`;
      } finally {
        state.reading = false;
      }
    });
  }

  async function openReview() {
    state.review = (await api("/api/company-voice/imoveis")).revisar[0] || null;
    if (!state.review) state.notice = "Nenhum imóvel para revisar.";
  }

  const companyUrl = (suffix) => `/api/company-voice/empresa/${encodeURIComponent(state.companyId)}${suffix}`;

  async function loadOrganization() {
    state.photoPanel = null;
    state.org = await api(companyUrl("/organizacao"));
    loadNames().catch(() => {});
    state.skills = (await api(skillsUrl())).skills;
    if (state.sector) state.sector = state.org.setores.find((item) => item.nome === state.sector.nome) || null;
  }

  async function openOrganization(sectorName, memberName) {
    await loadOrganization();
    state.skill = null;
    const holder = memberName ? state.org.setores.find((item) => item.time.some((person) => person.nome === memberName)) : null;
    state.sector = holder || (sectorName ? state.org.setores.find((item) => item.nome === sectorName) || null : null);
    state.member = holder ? holder.time.find((person) => person.nome === memberName).id : null;
    state.showOrg = true;
    render();
  }

  async function sendMission(prompt, label) {
    const dispatch = async (confirmed) => {
      const response = await fetch("/api/missions/dispatch", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt, language: "pt", confirmed }) });
      const payload = await response.json().catch(() => ({}));
      if (response.status === 409 && payload.requires_confirm && !confirmed) {
        if (!panel) await openPanel(document.querySelector(WORKSPACE));
        ask(`Ação sensível detectada (${payload.matched_text || "ação"}). Autorizar?`, async () => { await dispatch(true); state.notice = label; }, false);
        return false;
      }
      if (!response.ok) throw new Error(payload.detail || `Erro ${response.status}`);
      return true;
    };
    if (await dispatch(false)) state.notice = label;
  }

  function requestTask(member) {
    ask(member ? `O que ${member.nome} deve fazer?` : "Qual é a nova tarefa?", async (texto) => {
      const route = await api(companyUrl("/tarefa"), { method: "POST", body: { texto, membro: member ? member.id : "" } });
      const label = `Tarefa: ${route.rota.join(" → ")}.`;
      if (route.criado) state.notice = `${route.rota[route.rota.length - 2]} criou ${route.criado}. Ele está pesquisando na internet.`;
      else if (route.resposta) { state.answer = { rota: route.rota, resposta: route.resposta, fontes: route.fontes || [] }; }
      else if (route.agente) state.notice = route.aviso ? `${label} ${route.aviso}.` : `${label} Agente iniciado.`;
      else await sendMission(route.prompt, `${label} Acompanhe em Tarefas e missões.`);
      await loadOrganization();
    });
  }

  const studyLabel = (study) => {
    if (!study || study.estado === "vazio") return "";
    if (study.estado === "aguardando") return " · na fila para estudar";
    if (study.estado === "pesquisando") return " · estudando na internet";
    if (study.estado === "sem_fontes") return " · não achou fontes";
    return ` · ${study.fontes} fontes, ${study.oficiais} oficiais`;
  };

  function answerView() {
    const reply = state.answer;
    return [row([button("← Voltar", () => { state.answer = null; render(); })]), title(reply.rota.join(" → ")),
      el("div", { textContent: reply.resposta, style: { whiteSpace: "pre-wrap", fontSize: "13px" } }),
      ...(reply.fontes.length ? [title("Fontes"), ...reply.fontes.map((url) => el("a", { href: url, target: "_blank", rel: "noreferrer", textContent: url, style: { display: "block", marginTop: "4px", fontSize: "12px", color: colors.text, wordBreak: "break-all" } }))] : [])];
  }

  const STATUS_LABELS = { livre: "Livre", trabalhando: "Trabalhando", aguardando: "Aguardando", erro: "Com erro" };

  function memberActions(person, sector) {
    const openSkill = () => {
      const found = state.skills.find((skill) => person.habilidades.some((item) => item.id === skill.id));
      if (!found) return learnFunction(sector);
      state.showOrg = false;
      state.skill = found;
      render();
    };
    const edit = () => ask(`Novo nome de ${person.nome}`, async (nome) => {
      await api(companyUrl(`/funcionario/${encodeURIComponent(person.id)}`), { method: "PATCH", body: { nome, cargo: person.cargo } });
      await loadOrganization();
      state.notice = `Nome alterado para ${nome}.`;
    }, true, person.nome);
    const fire = () => ask(`Demitir ${person.nome}? As habilidades dele serão apagadas e não será possível recuperar.`, async () => {
      await api(companyUrl(`/funcionario/${encodeURIComponent(person.id)}`), { method: "DELETE", body: {} });
      await loadOrganization();
      state.notice = `${person.nome} foi demitido.`;
    }, false);
    return row([button("Mandar tarefa", () => requestTask(person), true), button("Ensinar", openSkill), button("Alterar nome", edit), ...(person.tipo === "gerente" ? [] : [button("Demitir", fire)])]);
  }

  function memberCard(person, sector) {
    return el("button", { type: "button", onclick: () => { state.sector = sector; state.member = person.id; render(); }, style: { display: "block", width: "100%", textAlign: "left", padding: "10px 12px", borderRadius: "10px", border: `1px solid ${colors.line}`, background: colors.card, color: colors.text, cursor: "pointer" } }, [
      el("div", { textContent: person.nome, style: { fontWeight: "600", fontSize: "13px" } }),
      el("div", { textContent: `${person.tipo === "gerente" ? "Gerente" : person.cargo} · ${STATUS_LABELS[person.status] || person.status}`, style: { fontSize: "12px", color: colors.muted } }),
      ...(person.agora ? [el("div", { textContent: `Agora: ${person.agora}`, style: { marginTop: "2px", fontSize: "12px" } })] : []),
    ]);
  }

  function knowledgeView(item) {
    const small = { marginTop: "4px", fontSize: "12px", color: colors.muted };
    const study = item.conhecimento || {};
    const again = () => guarded(async () => {
      await api(companyUrl(`/habilidade/${encodeURIComponent(item.id)}/estudar`), { method: "POST", body: {} });
      await loadOrganization();
      state.notice = "Ele voltou a estudar. Acompanhe aqui.";
    });
    const list = (name, values) => (values && values.length ? [el("div", { textContent: name, style: { marginTop: "8px", fontSize: "12px", fontWeight: "600" } }), ...values.map((text) => el("div", { textContent: `• ${text}`, style: small }))] : []);
    const sources = (study.lista || []).map((source) => el("a", { href: source.url, target: "_blank", textContent: `${source.oficial ? "Oficial · " : ""}${source.titulo}`, style: { ...small, display: "block", color: colors.text } }));
    return [...list("Como faz", item.listaPassos), ...list("Regras", item.listaRegras),
      ...(sources.length ? [el("div", { textContent: `Fontes estudadas (${study.trechos} trechos)`, style: { marginTop: "8px", fontSize: "12px", fontWeight: "600" } }), ...sources] : []),
      ...(["aguardando", "pesquisando"].includes(study.estado) ? [] : [row([button("Estudar de novo", again)])])];
  }

  function photoWork() {
    const small = { marginTop: "4px", fontSize: "12px", color: colors.muted };
    const panelData = state.photoPanel;
    if (!panelData) {
      guarded(async () => { state.photoPanel = await api("/api/company-voice/imoveis/fotos/painel"); });
      return [title("Fotos dos imóveis"), el("div", { textContent: "Carregando...", style: small })];
    }
    const rows = panelData.itens.flatMap((item) => [
      el("div", { textContent: `${item.titulo} · ${item.fotos || 0} fotos · ${item.aprovada ? "ordem aprovada" : item.duvidas && item.duvidas.length ? `${item.duvidas.length} em dúvida` : "sem dúvidas"}`, style: { marginTop: "8px", fontSize: "13px" } }),
      ...(item.faltando && item.faltando.length ? [el("div", { textContent: `Falta foto: ${item.faltando.join(", ")}`, style: small })] : []),
      ...(item.aprovada ? [] : (item.duvidas || []).slice(0, 4).map((text) => el("div", { textContent: `• ${text}`, style: small }))),
      row([button("Ver fotos", () => guarded(() => openProperty(item.chave)))])]);
    return [title("Fotos dos imóveis"), el("div", { textContent: `${panelData.correcoes} correções suas aprendidas`, style: small }),
      ...(rows.length ? rows : [el("div", { textContent: "Nenhum imóvel analisado ainda.", style: small })])];
  }

  function memberView(person, sector) {
    const small = { marginTop: "4px", fontSize: "12px", color: colors.muted };
    const skills = person.habilidades.length ? person.habilidades.map((item) => el("div", { style: { marginTop: "6px", fontSize: "13px" } }, [
      el("div", { textContent: `${item.nome}${studyLabel(item.conhecimento)}` }),
      el("div", { textContent: `${item.quando || "Sem descrição"} · ${item.passos} passos · ${item.regras} regras`, style: small }),
      ...knowledgeView(item)])) : [el("div", { textContent: person.tipo === "gerente" ? "Coordena o setor e distribui as tarefas." : "Ainda sem habilidade ensinada.", style: small })];
    const tasks = person.tarefas.length ? person.tarefas.map((task) => el("div", { textContent: `${task.status} · ${task.titulo}`, style: small })) : [el("div", { textContent: "Nenhuma tarefa ainda.", style: small })];
    return [row([button(`← ${sector.nome}`, () => { state.member = null; render(); })]), title(person.nome),
      el("div", { textContent: `${person.cargo} · ${sector.nome} · ${STATUS_LABELS[person.status] || person.status}`, style: small }),
      title("Fazendo agora"), el("div", { textContent: person.agora || "Nada no momento.", style: { fontSize: "13px" } }),
      memberActions(person, sector), ...(person.habilidades.some((item) => /fotos/i.test(item.nome)) ? photoWork() : []), title("O que faz"), ...skills, title("Últimas tarefas"), ...tasks];
  }

  function learnFunction(sector) {
    ask(`Especialista em quê? (${sector.nome})`, async (nome) => {
      await api(companyUrl(`/setor/${encodeURIComponent(sector.id)}/aprender`), { method: "POST", body: { nome } });
      await loadOrganization();
      state.notice = `Especialista em ${nome} criado. Ele já vai estudar a função.`;
    });
  }

  function organizationView() {
    const studying = state.org.setores.some((sector) => sector.time.some((person) => person.habilidades.some((item) => item.conhecimento && ["pesquisando", "aguardando"].includes(item.conhecimento.estado))));
    clearTimeout(state.orgTimer);
    if (studying) state.orgTimer = setTimeout(() => guarded(loadOrganization), 5000);
    const teamGrid = (sector) => el("div", { style: { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(230px, 1fr))", gap: "8px", marginTop: "8px" } }, sector.time.map((person) => memberCard(person, sector)));
    const pick = (sector) => { state.sector = sector; state.member = null; render(); };
    const options = [{ value: "", text: "Todos os departamentos" }, ...state.org.setores.map((item) => ({ value: item.nome, text: item.nome }))];
    const select = el("select", { "ariaLabel": "Departamento", style: { ...fieldStyle, width: "auto", minWidth: "240px" }, onchange: (event) => pick(state.org.setores.find((item) => item.nome === event.target.value) || null) },
      options.map((item) => el("option", { value: item.value, textContent: item.text })));
    select.value = state.sector ? state.sector.nome : "";
    const addSector = () => ask("Nome do novo departamento", async (nome) => {
      await api(companyUrl("/departamento"), { method: "POST", body: { nome } });
      await loadOrganization();
      state.sector = state.org.setores.find((item) => item.nome === nome) || null;
      state.notice = `Departamento ${nome} criado, com gerente.`;
    });
    const chooser = row([select, button("Nova tarefa", () => requestTask(null)), button("Adicionar departamento", addSector)]);
    if (!state.sector) {
      return [...(state.wide ? [] : [row([button("← Voltar", () => { state.showOrg = false; render(); })])]), chooser,
        ...state.org.setores.flatMap((sector) => [title(sector.nome), el("div", { textContent: `${sector.time.length} no time · ${sector.missao}`, style: { fontSize: "12px", color: colors.muted } }), teamGrid(sector)])];
    }
    const sector = state.sector;
    const opened = sector.time.find((person) => person.id === state.member);
    if (opened) return memberView(opened, sector);
    const build = () => guarded(async () => {
      state.notice = "O gerente está montando a equipe...";
      render();
      const result = await api(companyUrl(`/setor/${encodeURIComponent(sector.id)}/montar-equipe`), { method: "POST", body: {} });
      await loadOrganization();
      state.notice = result.criados.length ? `Novos especialistas: ${result.criados.join(", ")}.${result.basico ? " Comecei pelas funções básicas; ensine como a empresa faz." : ""}` : "A equipe já cobre as funções do setor.";
    });
    return [chooser, title(sector.nome), el("div", { textContent: sector.missao, style: { fontSize: "12px", color: colors.muted } }),
      ...(sector.id ? [row([button("Adicionar especialista", () => learnFunction(sector), true), button("Montar equipe", build)])] : []), teamGrid(sector)];
  }

  const isProperty = (skill) => /im[oó]ve/i.test(`${skill.name} ${skill.id}`);

  async function loadAgent() {
    state.agent = await api("/api/company-voice/imoveis/agente");
    clearTimeout(state.agentTimer);
    if (state.agent.rodando) state.agentTimer = setTimeout(() => guarded(loadAgent), 4000);
  }

  function specialistCard(skill) {
    const name = (members(() => true).find((member) => member.id === skill.specialistId) || {}).name || "Especialista";
    const head = el("div", { textContent: name, style: { fontWeight: "600", fontSize: "14px" } });
    const box = { marginTop: "12px", padding: "12px", borderRadius: "10px", border: `1px solid ${colors.line}`, background: colors.card };
    if (!isProperty(skill)) return el("div", { style: box }, [head, el("div", { textContent: "Use Testar habilidade para pedir esta tarefa.", style: { marginTop: "4px", fontSize: "12px", color: colors.muted } })]);
    const agent = state.agent;
    if (!agent) {
      guarded(loadAgent);
      return el("div", { style: box }, [head]);
    }
    const run = (save) => guarded(async () => {
      state.agent = await api("/api/company-voice/imoveis/agente", { method: "POST", body: { salvar: save } });
      await loadAgent();
    });
    const labels = { cadastrado: "Cadastrado", pendente: "Pendente", revisar: "Revisar" };
    const lines = agent.itens.slice(-12).map((item) => el("div", { textContent: `${labels[item.status] || item.status} · ${item.chave} · ${item.titulo}${item.nota ? ` · ${item.nota}` : ""}`, style: { marginTop: "4px", fontSize: "12px" } }));
    const save = button("Cadastrar agora", () => run(true), true);
    save.disabled = agent.rodando || !agent.salvar_liberado;
    const check = button("Conferir sem salvar", () => run(false));
    check.disabled = agent.rodando;
    [save, check].forEach((item) => { if (item.disabled) item.style.opacity = "0.5"; });
    return el("div", { style: box }, [head,
      el("div", { textContent: `${agent.rodando ? "Trabalhando agora" : "Parado"} · ${agent.contagem.cadastrado} cadastrados · ${agent.contagem.pendente} pendentes · ${agent.contagem.revisar} para revisar`, style: { marginTop: "4px", fontSize: "12px", color: colors.muted } }),
      ...(agent.ultimo ? [el("div", { textContent: `Último: ${agent.ultimo}`, style: { marginTop: "4px", fontSize: "12px", color: colors.muted } })] : []),
      ...(agent.salvar_liberado ? [] : [el("div", { textContent: "Salvamento ainda não liberado: por enquanto ele preenche e espera você conferir.", style: { marginTop: "4px", fontSize: "12px", color: colors.muted } })]),
      ...lines, row([save, check, button("Atualizar", () => guarded(loadAgent))])]);
  }

  async function openProperty(key) {
    const item = key ? { chave: key } : (await api("/api/company-voice/imoveis")).proximo;
    if (!item) { state.notice = "Nenhum imóvel na fila."; return; }
    state.notice = "Analisando as fotos...";
    render();
    const data = await api(`/api/company-voice/imoveis/${encodeURIComponent(item.chave)}/fotos`);
    state.property = { ...data, changed: {} };
    state.notice = "";
  }

  async function sendToKenlo(save) {
    const item = state.property;
    const path = `/api/company-voice/imoveis/${encodeURIComponent(item.imovel.chave)}/fotos`;
    await api(path, { method: "POST", body: { ordem: item.ordem.map((photo) => photo.nome), ambientes: item.changed } });
    item.changed = {};
    state.notice = "Abrindo o Kenlo...";
    render();
    const reply = await api("/api/company-voice/imoveis/kenlo", { method: "POST", body: { key: item.imovel.chave, salvar: save } });
    state.notice = `Kenlo: ${reply.resultado}`;
  }

  function propertyView() {
    const item = state.property;
    const key = encodeURIComponent(item.imovel.chave);
    const move = (index, step) => {
      const target = index + step;
      if (target < 0 || target >= item.ordem.length) return;
      [item.ordem[index], item.ordem[target]] = [item.ordem[target], item.ordem[index]];
      render();
    };
    const tile = (photo, index) => {
      const room = el("select", { style: fieldStyle }, item.ambientes.map((name) => el("option", { value: name, textContent: name.replace(/_/g, " ") })));
      room.value = photo.ambiente;
      room.addEventListener("change", () => { photo.ambiente = room.value; item.changed[photo.nome] = room.value; });
      return el("div", { style: { width: "170px", fontSize: "12px" } }, [
        el("img", { src: `/api/company-voice/imoveis/${key}/foto/${encodeURIComponent(photo.nome)}`, alt: photo.ambiente, style: { width: "100%", height: "110px", objectFit: "cover", borderRadius: "6px" } }),
        el("div", { textContent: `${index + 1}${index === 0 ? " · capa" : ""}${photo.confianca < 0.6 ? " · conferir" : ""}`, style: { margin: "4px 0", color: colors.muted } }),
        room, row([button("◀", () => move(index, -1)), button("▶", () => move(index, 1))])]);
    };
    return [row([button("← Voltar", () => { state.property = null; render(); })]),
      title("Fotos e cadastro"), el("div", { textContent: item.imovel.texto, style: { whiteSpace: "pre-wrap", fontSize: "13px" } }),
      ...item.avisos.map((text) => el("div", { textContent: `• ${text}`, style: { marginTop: "6px", fontSize: "12px", color: colors.muted } })),
      ...(item.repetidas.length ? [el("div", { textContent: `Repetidas, fora do anúncio: ${item.repetidas.join(", ")}`, style: { marginTop: "6px", fontSize: "12px", color: colors.muted } })] : []),
      el("div", { style: { display: "flex", flexWrap: "wrap", gap: "12px", marginTop: "12px" } }, item.ordem.map(tile)),
      row([button("Preencher no Kenlo sem salvar", () => guarded(() => sendToKenlo(false)), true), button("Cadastrar e salvar", () => guarded(() => sendToKenlo(true)))])];
  }

  function reviewView() {
    const item = state.review;
    const choose = (name, value, options) => {
      const select = el("select", { name, style: fieldStyle }, options.map(([id, text]) => el("option", { value: id, textContent: text })));
      select.value = value;
      return select;
    };
    const kind = choose("tipo", item.tipo || "", [["", "Escolha"], ...["apartamento", "casa", "sala", "loja", "predio", "pavilhao", "terreno"].map((id) => [id, id])]);
    const purpose = choose("finalidade", item.finalidade || "", [["", "Escolha"], ["residencial", "residencial"], ["comercial", "comercial"]]);
    const condo = choose("condominio", item.condominio === null ? "" : String(item.condominio), [["", "Escolha"], ["true", "Sim"], ["false", "Não"]]);
    const release = () => guarded(async () => {
      if (!condo.value) throw new Error("Diga se está em condomínio.");
      await api(`/api/company-voice/imoveis/${encodeURIComponent(item.chave)}/resposta`, { method: "POST", body: { tipo: kind.value, finalidade: purpose.value, condominio: condo.value === "true" } });
      await openReview();
    });
    return [row([button("← Voltar", () => { state.review = null; render(); })]),
      title("Imóvel para revisar"), el("div", { textContent: item.texto, style: { whiteSpace: "pre-wrap", fontSize: "13px" } }),
      ...[...(item.duvidas || []), ...(item.nota ? [item.nota] : [])].map((text) => el("div", { textContent: `• ${text}`, style: { marginTop: "6px", fontSize: "12px", color: colors.muted } })),
      label("Tipo"), kind, label("Finalidade"), purpose, label("Em condomínio"), condo, row([button("Liberar para cadastro", release, true)])];
  }

  async function saveLearned() {
    const skill = await api(skillsUrl(`/${state.skill.id}`));
    const learned = state.teach.learned;
    const pick = (kind) => learned.filter((item) => item.kind === kind).map((item) => item.text);
    const merge = (old, kind) => [...new Set([...old, ...pick(kind)])];
    let updated = await api(skillsUrl(`/${skill.id}`), { method: "PATCH", body: {
      steps: merge(skill.steps, "PASSO"), rules: merge(skill.rules, "REGRA"), conditions: merge(skill.conditions || [], "CONDICAO"), exceptions: merge(skill.exceptions, "EXCECAO"),
      validation: merge(skill.validation, "VALIDAR"), note: "Aprendido no modo ensino",
    } });
    for (const text of pick("EXEMPLO")) {
      const [situation, outcome] = text.split("=>").map((part) => part.trim());
      updated = await api(skillsUrl(`/${skill.id}/examples`), { method: "POST", body: { situation, outcome: outcome || "" } });
    }
    state.teach.saved.push(...learned);
    state.teach.learned = [];
    await saved(updated);
  }

  async function record(field, control) {
    if (state.recorder) {
      const stop = state.recorder;
      state.recorder = null;
      control.textContent = "Falar";
      await stop();
      return;
    }
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const context = new AudioContext();
    await context.resume();
    const source = context.createMediaStreamSource(stream);
    const node = context.createScriptProcessor(4096, 1, 1);
    const pieces = [];
    node.onaudioprocess = (event) => pieces.push(toSixteenK(event.inputBuffer.getChannelData(0), context.sampleRate));
    source.connect(node);
    node.connect(context.destination);
    control.textContent = "Parar";
    state.recorder = async () => {
      node.disconnect();
      source.disconnect();
      stream.getTracks().forEach((track) => track.stop());
      await context.close();
      const audio = new Int16Array(pieces.reduce((sum, piece) => sum + piece.length, 0));
      let at = 0;
      pieces.forEach((piece) => { audio.set(piece, at); at += piece.length; });
      control.textContent = "Transcrevendo...";
      const response = await fetch("/api/company-voice/transcribe", { method: "POST", body: audio.buffer });
      const payload = await response.json().catch(() => ({}));
      control.textContent = "Falar";
      if (!response.ok) throw new Error(payload.detail || "Falha ao transcrever");
      field.value = [field.value, payload.text].filter(Boolean).join(" ");
    };
  }

  // A escuta roda no servidor: o painel so acompanha e entrega ao assistente
  // os pedidos que nao sao imediatos.
  async function teachByVoice() {
    const teach = state.teach;
    const skill = state.skill;
    await api("/api/company-voice/ensino/iniciar", { method: "POST", body: { companyId: state.companyId, skillId: skill.id } });
    teach.live = true;
    let seen = 0;
    let handed = 0;
    let working = Promise.resolve();
    while (state.teach === teach) {
      await new Promise((done) => setTimeout(done, 700));
      const live = await api(`/api/company-voice/ensino/estado?desde=${seen}&assistente=${handed}`);
      seen = live.total;
      handed = live.agent_total;
      teach.level = live.level;
      teach.status = teach.busy ? "Ouvindo enquanto o assistente executa..." : live.status;
      live.log.forEach((entry) => {
        teach.log.push(entry);
        if (entry.who === "Observei" || entry.text.startsWith("Feito: ")) teach.saved.push({ kind: "PASSO", text: entry.text.replace(/^Feito: /, "") });
      });
      state.error = live.error || "";
      live.agent.forEach((text) => { working = working.then(() => sendTeach(text, true)).catch((error) => { state.error = error.message; render(); }); });
      if (live.log.length) state.skill = await api(skillsUrl(`/${skill.id}`));
      teach.live = live.live;
      if (!live.live) break;
      render();
    }
    await working;
    state.skill = await api(skillsUrl(`/${skill.id}`));
    state.skills = (await api(skillsUrl())).skills;
    teach.live = false;
    teach.status = "";
    state.notice = "Aprendizado finalizado. Tudo já está registrado na habilidade.";
  }

  function stopTeachByVoice() {
    api("/api/company-voice/ensino/parar", { method: "POST", body: {} }).catch(() => null);
  }

  function teachView() {
    const teach = state.teach;
    const text = area("", "ensino", 3);
    const speakButton = button("Falar", () => record(text, speakButton).catch((error) => { state.error = error.message; render(); }));
    const send = button(teach.busy ? "Executando..." : "Enviar", () => {
      if (!text.value.trim() || teach.busy) return;
      guarded(() => sendTeach(text.value.trim()));
    }, true);
    const lineOf = (entry) => el("div", { style: { marginTop: "10px" } }, [
      el("div", { textContent: entry.who, style: { fontSize: "11px", color: colors.muted } }),
      el("div", { textContent: entry.text, style: { whiteSpace: "pre-wrap", fontSize: "13px" } }),
    ]);
    const learned = teach.saved.map((item) => el("div", { textContent: `${item.kind}: ${item.text}`, style: { marginTop: "4px", fontSize: "12px" } }));
    const voice = teach.live
      ? button("Parar de ouvir", stopTeachByVoice, true)
      : button("Ensinar por voz", () => guarded(teachByVoice), true);
    return [row([button("← Sair do ensino", () => { if (teach.live) stopTeachByVoice(); state.teach = null; render(); }), voice]),
      el("p", { textContent: teach.status || "Fale ou clique você mesmo. Ele executa, observa e aprende até você dizer finalizar aprendizado.", style: { fontSize: "12px", color: colors.muted } }),
      ...(teach.live ? [el("div", { textContent: `Microfone: ${Math.round(Math.min(1, (teach.level || 0) * 20) * 100)}%`, style: { fontSize: "12px", color: colors.muted } })] : []),
      ...teach.log.map(lineOf), label("Ou escreva a instrução"), text, row([speakButton, send]),
      ...(learned.length ? [title("Já registrado nesta conversa"), ...learned] : [])];
  }

  // O app do Mac nao mostra window.prompt nem window.confirm, entao pergunta aqui.
  function ask(question, onAnswer, hasText, initial) {
    state.asking = { question, onAnswer, hasText: hasText !== false, initial: initial || "" };
    render();
  }

  async function reloadCompanies(preferred) {
    const data = await api("/api/companies");
    state.companies = data.companies || [];
    const found = state.companies.some((item) => item.id === preferred);
    await loadCompany(found ? preferred : data.activeCompanyId || (state.companies[0] && state.companies[0].id) || null);
    const host = document.querySelector(WORKSPACE);
    const refresh = host && host.querySelector("header button");
    if (refresh) refresh.click();
  }

  function addCompany() {
    ask("Nome da empresa", (name) => {
      ask("Segmento da empresa", async (segment) => {
        const company = await api("/api/companies", { method: "POST", body: { name, segment } });
        await reloadCompanies(company.id);
        state.notice = `Empresa ${company.name} adicionada.`;
      }, true, "Empresa");
    });
  }

  function removeCompany() {
    const company = state.companies.find((item) => item.id === state.companyId);
    if (!company) return;
    ask(`Para apagar, digite exatamente: ${company.name}`, async (typed) => {
      if (typed !== company.name) throw new Error("O nome não confere. Nada foi apagado.");
      const url = `/api/companies/${encodeURIComponent(company.id)}`;
      await api(`${url}/skills/archive`, { method: "POST", body: {} });
      await api(url, { method: "DELETE", body: {} });
      await reloadCompanies(null);
      state.notice = `Empresa ${company.name} apagada. Uma cópia foi guardada.`;
    });
  }

  function askView() {
    const asking = state.asking;
    const answer = input(asking.initial, "resposta");
    const finish = () => {
      if (asking.hasText && !answer.value.trim()) return;
      state.asking = null;
      guarded(() => asking.onAnswer(answer.value.trim()));
    };
    answer.addEventListener("keydown", (event) => { if (event.key === "Enter") finish(); });
    setTimeout(() => answer.focus(), 0);
    return [label(asking.question), ...(asking.hasText ? [answer] : []),
      row([button(asking.hasText ? "Continuar" : "Confirmar", finish, true), button("Cancelar", () => { state.asking = null; render(); })])];
  }

  function createSkill() {
    ask("Nome da tarefa a ensinar", async (name) => saved(await api(skillsUrl(), { method: "POST", body: { name } })));
  }

  function listView() {
    const company = el("select", { value: state.companyId || "", style: fieldStyle, onchange: (event) => guarded(() => loadCompany(event.target.value)) },
      state.companies.map((item) => el("option", { value: item.id, textContent: item.name })));
    company.value = state.companyId || "";
    const removeSkill = (skill) => ask(`Apagar a habilidade "${skill.name}"? Não será possível recuperar.`, async () => {
      await api(skillsUrl(`/${skill.id}`), { method: "DELETE", body: {} });
      state.skills = (await api(skillsUrl())).skills;
      state.notice = `Habilidade ${skill.name} apagada.`;
    }, false);
    const items = state.skills.map((skill) => el("div", { style: { display: "flex", gap: "8px", alignItems: "stretch", marginTop: "8px" } }, [
      el("button", {
        type: "button", onclick: () => { state.skill = skill; render(); },
        style: { flex: "1", minWidth: "0", textAlign: "left", padding: "10px 12px", borderRadius: "10px", border: `1px solid ${colors.line}`, background: colors.card, color: colors.text, font: "inherit", cursor: "pointer" },
      }, [
        el("div", { textContent: skill.name, style: { fontSize: "13px", fontWeight: "600" } }),
        el("div", { textContent: `${skill.examples.length} de 10 exemplos · ${skill.rules.length} regras · versão ${skill.version}`, style: { marginTop: "3px", fontSize: "12px", color: colors.muted } }),
      ]),
      button("Apagar", () => removeSkill(skill)),
    ]));
    return [label("Empresa"), company, row([button("Adicionar empresa", addCompany), ...(state.companyId ? [button("Apagar empresa", removeCompany)] : [])]),
      ...(state.companyId ? [row([button("Criar nova habilidade", createSkill, true)])] : []), title("Habilidades ensinadas"),
      ...(items.length ? items : [el("p", { textContent: "Nenhuma habilidade ainda. Crie a primeira e ensine passo a passo.", style: { fontSize: "13px", color: colors.muted } })])];
  }

  function skillView(skill) {
    const form = {
      name: input(skill.name, "name"), whenToUse: area(skill.whenToUse, "whenToUse"),
      steps: area(skill.steps.join("\n"), "steps", 6), rules: area(skill.rules.join("\n"), "rules", 4),
      conditions: area((skill.conditions || []).join("\n"), "conditions"),
      exceptions: area(skill.exceptions.join("\n"), "exceptions"), validation: area(skill.validation.join("\n"), "validation"),
      managerId: memberSelect(skill.managerId, "managerId", (member) => member.kind === "gerente"),
      specialistId: memberSelect(skill.specialistId, "specialistId", (member) => member.kind !== "gerente"),
    };
    const save = () => guarded(async () => saved(await api(skillsUrl(`/${skill.id}`), { method: "PATCH", body: {
      name: form.name.value, whenToUse: form.whenToUse.value, managerId: form.managerId.value, specialistId: form.specialistId.value,
      steps: lines(form.steps), rules: lines(form.rules), conditions: lines(form.conditions), exceptions: lines(form.exceptions), validation: lines(form.validation),
    } })));
    const exampleText = area("", "situation"); const exampleResult = area("", "outcome", 2);
    const addExample = () => guarded(async () => saved(await api(skillsUrl(`/${skill.id}/examples`), { method: "POST", body: { situation: exampleText.value, outcome: exampleResult.value } })));
    const correctionText = area("", "correction", 2);
    const addCorrection = () => guarded(async () => saved(await api(skillsUrl(`/${skill.id}/corrections`), { method: "POST", body: { text: correctionText.value } })));
    const test = () => ask(`Descreva um caso para testar "${skill.name}"`, async (task) => {
      const person = (id) => (members(() => true).find((member) => member.id === id) || {}).name;
      const chain = [person("gerente-geral"), person(skill.managerId), person(skill.specialistId)].filter(Boolean).join(" -> ");
      const prompt = `EMPRESA: ${skill.company}\nENCAMINHAMENTO: ${chain || "A definir"}\nExecute a habilidade "${skill.name}": ${task}. Valide o resultado e relate o que fez.`;
      const dispatch = async (confirmed) => {
        const response = await fetch("/api/missions/dispatch", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt, language: "pt", confirmed }) });
        const payload = await response.json().catch(() => ({}));
        if (response.status === 409 && payload.requires_confirm && !confirmed) {
          ask(`Ação sensível detectada (${payload.matched_text || "ação"}). Autorizar o teste?`, async () => {
            await dispatch(true);
            state.notice = "Teste enviado. Acompanhe em Tarefas e missões.";
          }, false);
          return false;
        }
        if (!response.ok) throw new Error(payload.detail || `Erro ${response.status}`);
        return true;
      };
      if (await dispatch(false)) state.notice = "Teste enviado. Acompanhe em Tarefas e missões.";
    });
    const history = skill.history.slice().reverse().slice(0, 30).map((item) => el("div", { textContent: `v${item.version} · ${item.at.slice(0, 16).replace("T", " ")} · ${item.change}`, style: { padding: "4px 0", fontSize: "12px", color: colors.muted } }));
    const teach = () => { state.teach = { session: null, log: [], learned: [], saved: [], busy: false }; render(); };
    return [row([button("← Voltar", () => { state.skill = null; render(); }), button("Ensinar conversando", teach, true), button("Testar habilidade", test)]),
      specialistCard(skill),
      row([button(state.reading ? "Lendo o grupo..." : "Ler grupo do WhatsApp", askGroup),
        ...(isProperty(skill) ? [] : [state.batch ? button("Parar lote", () => { state.batch.stop = true; render(); }) : button("Cadastrar os novos", () => guarded(() => runBatch(skill)))]),
        button("Revisar imóveis", () => guarded(openReview)), button("Fotos e Kenlo", () => guarded(openProperty))]),
      ...(state.batch ? [el("div", { textContent: `Cadastrando: ${state.batch.current || "..."} (${state.batch.done} feitos)`, style: { marginTop: "10px", fontSize: "12px", color: colors.muted } })] : []),
      el("div", { textContent: `${skill.examples.length} de 10 exemplos · versão ${skill.version}`, style: { marginTop: "12px", fontSize: "12px", color: colors.muted } }),
      label("Nome"), form.name, label("Quando usar"), form.whenToUse, label("Passos, um por linha"), form.steps,
      label("Regras, uma por linha"), form.rules, label("Decisões conforme o caso, uma por linha"), form.conditions, label("Exceções, uma por linha"), form.exceptions, label("Como validar, um por linha"), form.validation,
      label("Gerente responsável"), form.managerId, label("Funcionário especialista"), form.specialistId, row([button("Salvar", save, true)]),
      title("Adicionar exemplo"), label("Situação"), exampleText, label("Resultado esperado"), exampleResult, row([button("Adicionar exemplo", addExample)]),
      ...skill.examples.slice(-5).reverse().map((item) => el("div", { textContent: `• ${item.situation}`, style: { marginTop: "6px", fontSize: "12px", color: colors.muted } })),
      title("Corrigir"), label("O que deve mudar"), correctionText, row([button("Registrar correção", addCorrection)]),
      ...skill.corrections.slice(-5).reverse().map((item) => el("div", { textContent: `• ${item.text}`, style: { marginTop: "6px", fontSize: "12px", color: colors.muted } })),
      title("Histórico de aprendizado"), ...history];
  }

  // Na aba Equipe a tela ocupa a area das abas e deixa o menu visivel.
  function placePanel() {
    const nav = panel.parentElement.querySelector("nav:not(aside nav)");
    if (state.wide && nav) {
      const host = panel.parentElement.getBoundingClientRect();
      const bar = nav.getBoundingClientRect();
      Object.assign(panel.style, { left: `${bar.left - host.left}px`, top: `${bar.bottom - host.top}px`, width: "auto", borderLeft: "none" });
    } else {
      Object.assign(panel.style, { left: "", top: "0", width: "min(480px, 100%)", borderLeft: `1px solid ${colors.line}` });
    }
  }

  function render() {
    if (!panel) return;
    placePanel();
    const body = state.asking ? askView() : state.review ? reviewView() : state.property ? propertyView() : state.teach ? teachView() : state.answer ? answerView() : state.showOrg ? organizationView() : state.skill ? skillView(state.skill) : listView();
    panel.replaceChildren(
      el("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between", gap: "12px" } }, [
        el("h2", { textContent: state.showOrg ? "Departamentos" : state.skill ? state.skill.name : "Aprender nova tarefa", style: { margin: "0", fontSize: "16px", fontWeight: "600" } }),
        ...(state.teamTab && state.showOrg ? [] : [button("Fechar", closePanel)]),
      ]),
      ...(state.error ? [el("div", { role: "alert", textContent: state.error, style: { marginTop: "10px", color: "hsl(var(--destructive))", fontSize: "12px" } })] : []),
      ...(state.notice ? [el("div", { textContent: state.notice, style: { marginTop: "10px", color: colors.muted, fontSize: "12px" } })] : []),
      ...body,
    );
    state.notice = "";
  }

  function closePanel() { if (panel) panel.remove(); panel = null; state.teach = null; state.showOrg = false; state.sector = null; state.member = null; state.answer = null; state.wide = false; state.teamTab = false; }

  function openPanel(host) {
    panel = el("section", { "ariaLabel": "Aprender nova tarefa", style: { position: "absolute", top: "0", right: "0", bottom: "0", zIndex: "10", width: "min(480px, 100%)", boxSizing: "border-box", padding: "20px", overflowY: "auto", borderLeft: `1px solid ${colors.line}`, background: colors.bg, color: colors.text, fontSize: "13px" } });
    panel.dataset.testid = "aprender-painel";
    host.append(panel);
    return guarded(async () => {
      const data = await api("/api/companies");
      state.companies = data.companies || [];
      await loadCompany(data.activeCompanyId || (state.companies[0] && state.companies[0].id) || null);
    });
  }

  // O botao da barra lateral usa uma janela que o app do Mac nao mostra.
  function takeOverAddButton(host) {
    const add = [...host.querySelectorAll("aside button")].find((node) => node.textContent.trim() === "Adicionar empresa");
    if (!add || add.dataset.aprender) return;
    add.dataset.aprender = "1";
    add.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopImmediatePropagation();
      const go = () => addCompany();
      if (panel) go(); else { openPanel(host).then(go); }
    }, true);
  }

  async function openTeam(host, name, member) {
    state.wide = true;
    state.teach = null; state.review = null; state.property = null; state.answer = null; state.asking = null;
    if (!panel) await openPanel(host);
    if (state.shownCompany && state.shownCompany !== state.companyId) await guarded(() => loadCompany(state.shownCompany));
    await guarded(() => openOrganization(name, member));
  }

  async function loadNames() {
    const data = await api("/api/companies");
    state.activeCompany = data.activeCompanyId || (data.companies[0] && data.companies[0].id) || null;
    state.sectorNames = data.companies.flatMap((company) => (company.departments || []).map((item) => item.name));
    state.memberNames = data.companies.flatMap((company) => (company.members || []).map((item) => item.name));
  }

  // Os cartoes de setor e de pessoa abrem a ficha; a aba Equipe abre os setores.
  function watchClicks(host) {
    if (host.dataset.setores) return;
    host.dataset.setores = "1";
    host.addEventListener("click", (event) => {
      const target = event.target;
      if (!(target instanceof Element) || target.closest('[data-testid="aprender-painel"], [data-testid="conversa-empresa"]')) return;
      const side = target.closest("aside");
      if (side) {
        const chosen = target.closest("button");
        const company = chosen && (state.companies || []).find((item) => chosen.textContent.includes(item.name));
        if (company) state.shownCompany = company.id;
        if (company && state.wide) closePanel();
        return;
      }
      const tab = target.closest("nav button");
      if (tab) {
        state.teamTab = tab.textContent.trim() === "Departamentos";
        if (state.teamTab) openTeam(host, "");
        else if (state.wide) closePanel();
        return;
      }
      if (target.closest("button, input, select, textarea, a")) return;
      let node = target;
      for (let depth = 0; node && node !== host && depth < 3; depth += 1, node = node.parentElement) {
        const leaves = [...node.querySelectorAll("div, span, h3, h4, p"), node].filter((item) => !item.childElementCount).map((item) => item.textContent.trim());
        const members = [...new Set(leaves.filter((text) => (state.memberNames || []).includes(text)))];
        const sectors = [...new Set(leaves.filter((text) => (state.sectorNames || []).includes(text)))];
        if (members.length + sectors.length > 1) return;
        if (members.length) { openTeam(host, "", members[0]); return; }
        if (sectors.length) { openTeam(host, sectors[0]); return; }
      }
    });
    window.addEventListener("resize", () => { if (panel) placePanel(); });
  }

  const DRAFT = "dodaios-conversa-rascunho";
  const chatUrl = () => `/api/company-voice/empresa/${encodeURIComponent(state.shownCompany || state.activeCompany)}/conversa`;
  const remembered = () => { try { return localStorage.getItem(DRAFT) || ""; } catch { return ""; } };
  const remember = (text) => { try { localStorage.setItem(DRAFT, text); } catch { /* sem armazenamento */ } };

  function chatBubble(message) {
    const mine = message.quem === "voce";
    return el("div", { style: { display: "flex", justifyContent: mine ? "flex-end" : "flex-start", marginTop: "8px" } }, [
      el("div", { style: { maxWidth: "80%", padding: "9px 12px", borderRadius: "12px", background: mine ? colors.main : colors.card, color: mine ? colors.onMain : colors.text, border: mine ? "none" : `1px solid ${colors.line}`, fontSize: "13px" } }, [
        ...(message.rota && message.rota.length ? [el("div", { textContent: message.rota.join(" → "), style: { marginBottom: "4px", fontSize: "11px", color: colors.muted } })] : []),
        el("div", { textContent: message.texto, style: { whiteSpace: "pre-wrap" } }),
        ...(message.fontes || []).map((url) => el("a", { href: url, target: "_blank", rel: "noreferrer", textContent: url, style: { display: "block", marginTop: "4px", fontSize: "11px", color: colors.muted, wordBreak: "break-all" } })),
      ]),
    ]);
  }

  async function refreshChat() {
    const box = state.chatBox;
    if (!box || !box.isConnected) return;
    clearTimeout(state.chatTimer);
    const data = await api(chatUrl());
    const list = box.querySelector('[data-testid="conversa-lista"]');
    const opening = el("div", { textContent: "Pergunte, peça ou mande fazer. O Gerente Geral busca com quem sabe.", style: { fontSize: "12px", color: colors.muted } });
    list.replaceChildren(...(data.mensagens.length ? data.mensagens.map(chatBubble) : [opening]));
    list.scrollTop = list.scrollHeight;
    if (data.estudando) state.chatTimer = setTimeout(() => refreshChat().catch(() => {}), 4000);
  }

  function chatPanel() {
    const list = el("div", { style: { height: "130px", overflowY: "auto", padding: "4px 2px" } });
    list.dataset.testid = "conversa-lista";
    const field = el("textarea", { rows: 1, name: "conversa", placeholder: "Fale com a empresa...", value: remembered(), style: { ...fieldStyle, flex: "1", resize: "none" } });
    const status = el("div", { style: { minHeight: "16px", marginTop: "4px", fontSize: "12px", color: colors.muted } });
    const send = async () => {
      const texto = field.value.trim();
      if (!texto || field.disabled) return;
      field.disabled = true;
      status.textContent = "A empresa está respondendo...";
      list.append(chatBubble({ quem: "voce", texto }));
      list.scrollTop = list.scrollHeight;
      try {
        const reply = await api(chatUrl(), { method: "POST", body: { texto } });
        field.value = "";
        remember("");
        if (reply.missao) await sendMission(reply.missao, "Tarefa encaminhada.");
        status.textContent = "";
      } catch (error) {
        status.textContent = `Não consegui enviar: ${error.message}`;
      }
      field.disabled = false;
      field.focus();
      await refreshChat().catch(() => {});
    };
    field.addEventListener("input", () => remember(field.value));
    field.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); send(); }
    });
    const box = el("section", { style: { padding: "12px 16px", borderRadius: "16px", border: `1px solid ${colors.line}`, background: colors.bg, color: colors.text } }, [
      el("div", { textContent: "Conversar com a empresa", style: { fontSize: "14px", fontWeight: "600" } }), list,
      el("div", { style: { display: "flex", gap: "8px", alignItems: "flex-end", marginTop: "8px" } }, [field, button("Enviar", send, true)]), status]);
    box.dataset.testid = "conversa-empresa";
    return box;
  }

  function placeChat(host) {
    if (!state.activeCompany && !state.shownCompany) return;
    const mark = [...host.querySelectorAll("div, span")].find((node) => !node.childElementCount && node.textContent.trim() === "JARVIS Company Command")
      || [...host.querySelectorAll("div, span")].find((node) => [...node.childNodes].some((child) => child.nodeType === 3 && child.textContent.trim() === "JARVIS Company Command"));
    const hero = mark && mark.closest(".overflow-hidden");
    if (!hero) return;
    const shown = state.shownCompany || state.activeCompany;
    if (!state.chatBox) state.chatBox = chatPanel();
    if (state.chatBox.previousElementSibling !== hero) {
      hero.after(state.chatBox);
      state.chatLoaded = false;
    }
    if (state.chatCompany !== shown || !state.chatLoaded) {
      state.chatCompany = shown;
      state.chatLoaded = true;
      refreshChat().catch(() => { state.chatLoaded = false; });
    }
  }

  function hideTeamTab(host) {
    host.querySelectorAll("nav button").forEach((node) => {
      if (node.textContent.trim() === "Equipe" && !node.closest('[data-testid="aprender-painel"]')) node.style.display = "none";
    });
  }

  function markCards(host) {
    const names = [...(state.sectorNames || []), ...(state.memberNames || [])];
    host.querySelectorAll("div").forEach((node) => {
      if (node.childElementCount || !names.includes(node.textContent.trim()) || node.closest('[data-testid="aprender-painel"]') || !node.parentElement) return;
      node.parentElement.style.cursor = "pointer";
      node.style.textDecoration = "underline";
    });
  }

  function markManagers(host) {
    const open = () => { if (!panel) openPanel(host); };
    host.querySelectorAll("button, div, span, h3, h4, p").forEach((node) => {
      if (node.childElementCount || node.textContent.trim() !== "Gerente Geral" || node.closest('[data-testid="aprender-painel"]')) return;
      const parent = node.parentElement;
      if (!parent || parent.querySelector("[data-aprender]") || node.tagName === "BUTTON") return;
      const small = button("Aprender", open);
      small.dataset.aprender = "1";
      Object.assign(small.style, { marginTop: "4px", padding: "3px 8px", fontSize: "11px" });
      parent.append(small);
    });
  }

  function attach() {
    const host = document.querySelector(WORKSPACE);
    if (!host) { closePanel(); return; }
    markManagers(host);
    watchClicks(host);
    markCards(host);
    hideTeamTab(host);
    placeChat(host);
    takeOverAddButton(host);
    if (!state.organized) {
      state.organized = true;
      api("/api/company-voice/empresas/organizar", { method: "POST", body: {} }).then(async () => {
        await loadNames();
        attach();
      }).catch(() => { state.organized = false; });
    }
    if (host.querySelector('[data-testid="aprender-botao"]')) return;
    const launch = button("Aprender nova tarefa", () => { if (!panel) openPanel(host); }, true);
    launch.dataset.testid = "aprender-botao";
    const task = button("Nova tarefa", () => openTeam(host, "").then(() => requestTask(null)), true);
    task.dataset.testid = "nova-tarefa";
    const actions = el("div", { style: { position: "absolute", top: "18px", right: "76px", zIndex: "9", display: "flex", gap: "8px" } }, [task, launch]);
    host.append(actions);
  }

  let waiting = false;
  new MutationObserver(() => {
    if (waiting) return;
    waiting = true;
    setTimeout(() => { waiting = false; attach(); }, 250);
  }).observe(document.documentElement, { childList: true, subtree: true });
  attach();
})();
