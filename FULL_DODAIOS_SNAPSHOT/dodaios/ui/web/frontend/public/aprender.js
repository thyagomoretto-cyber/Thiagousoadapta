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

  const TEACH_RULES = "Estou ensinando esta tarefa. Execute cada instrucao com as ferramentas, na tela, e pergunte quando tiver duvida. Prefira localizar elementos por texto, rotulo e estrutura da pagina; use coordenadas so como ultimo recurso. Nunca adivinhe link, nome, senha ou dado: se faltar algo, pare e faca uma pergunta curta. Responda em poucas frases, porque sua resposta sera falada. Quando o caminho mudar conforme o caso, como um imovel comercial ou residencial, pergunte como identificar e registre a decisao. No fim de cada resposta, liste o que aprendeu em linhas neste formato exato: PASSO: texto / REGRA: texto / CONDICAO: se tal caso, entao fazer tal coisa / EXCECAO: texto / VALIDAR: texto / EXEMPLO: situacao => resultado.";

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
    const context = first ? `${TEACH_RULES}\nHabilidade: ${skill.name}. Empresa: ${skill.company}. Passos ja aprendidos: ${skill.steps.join("; ") || "nenhum"}.\n\n` : "";
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
        reply.split("\n").forEach((line) => {
          const found = line.match(/^\W*(PASSO|REGRA|CONDICAO|EXCECAO|VALIDAR|EXEMPLO):\s*(.+)$/);
          if (found) teach.learned.push({ kind: found[1], text: found[2].trim() });
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
      if (live.error) state.error = live.error;
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
      row([button(state.reading ? "Lendo o grupo..." : "Ler grupo do WhatsApp", askGroup),
        state.batch ? button("Parar lote", () => { state.batch.stop = true; render(); }) : button("Cadastrar os novos", () => guarded(() => runBatch(skill))),
        button("Revisar imóveis", () => guarded(openReview))]),
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

  function render() {
    if (!panel) return;
    const body = state.asking ? askView() : state.review ? reviewView() : state.teach ? teachView() : state.skill ? skillView(state.skill) : listView();
    panel.replaceChildren(
      el("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between", gap: "12px" } }, [
        el("h2", { textContent: state.skill ? state.skill.name : "Aprender nova tarefa", style: { margin: "0", fontSize: "16px", fontWeight: "600" } }),
        button("Fechar", closePanel),
      ]),
      ...(state.error ? [el("div", { role: "alert", textContent: state.error, style: { marginTop: "10px", color: "hsl(var(--destructive))", fontSize: "12px" } })] : []),
      ...(state.notice ? [el("div", { textContent: state.notice, style: { marginTop: "10px", color: colors.muted, fontSize: "12px" } })] : []),
      ...body,
    );
    state.notice = "";
  }

  function closePanel() { if (panel) panel.remove(); panel = null; state.teach = null; }

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
    takeOverAddButton(host);
    if (host.querySelector('[data-testid="aprender-botao"]')) return;
    const launch = button("Aprender nova tarefa", () => { if (!panel) openPanel(host); }, true);
    launch.dataset.testid = "aprender-botao";
    Object.assign(launch.style, { position: "absolute", right: "20px", bottom: "20px", zIndex: "9" });
    host.append(launch);
  }

  let waiting = false;
  new MutationObserver(() => {
    if (waiting) return;
    waiting = true;
    setTimeout(() => { waiting = false; attach(); }, 250);
  }).observe(document.documentElement, { childList: true, subtree: true });
  attach();
})();
