import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  Activity,
  BarChart3,
  Bot,
  BriefcaseBusiness,
  Building2,
  CheckCircle2,
  FileText,
  FolderKanban,
  Gauge,
  HardDrive,
  LoaderCircle,
  MemoryStick,
  Network,
  Plus,
  RefreshCw,
  Send,
  Sparkles,
  Upload,
  Users,
  Workflow,
  X,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { CompanyBuilding } from "./CompanyBuilding";

type AgentStatus = "livre" | "trabalhando" | "aguardando" | "erro";
type TaskStatus = "pendente" | "andamento" | "aguardando" | "concluida" | "erro";
type Tab = "overview" | "building" | "departments" | "team" | "tasks" | "projects" | "clients" | "files" | "automations" | "indicators" | "memory";

interface Department { id: string; name: string; floor: number; mission: string }
interface Member {
  id: string; name: string; role: string; departmentId: string;
  kind: "gerente" | "especialista" | "funcionario";
  status: AgentStatus; model: string; autonomy: "assistido" | "semi-autonomo" | "autonomo";
  currentTask?: string | null; missionId?: string | null;
}
interface BusinessTask {
  id: string; title: string; description: string; assigneeId?: string | null;
  departmentId?: string | null; status: TaskStatus; missionId?: string | null;
  createdAt?: string | null; updatedAt?: string | null;
}
interface Project { id: string; name: string; status: "planejado" | "andamento" | "aguardando" | "concluido"; owner: string }
interface Company {
  id: string; name: string; segment: string; description: string;
  departments: Department[]; members: Member[]; tasks: BusinessTask[]; projects: Project[];
  clients: string[]; files: string[]; automations: string[]; memory: string[];
}
interface CompaniesState { companies: Company[]; activeCompanyId: string | null; version: number }

const API = "/api/companies";
const tabs: Array<{ id: Tab; label: string; icon: typeof Building2 }> = [
  { id: "overview", label: "Visão geral", icon: Gauge },
  { id: "building", label: "Prédio", icon: Building2 },
  { id: "departments", label: "Departamentos", icon: Network },
  { id: "team", label: "Equipe", icon: Users },
  { id: "tasks", label: "Tarefas", icon: CheckCircle2 },
  { id: "projects", label: "Projetos", icon: FolderKanban },
  { id: "clients", label: "Clientes", icon: BriefcaseBusiness },
  { id: "files", label: "Arquivos", icon: HardDrive },
  { id: "automations", label: "Automações", icon: Workflow },
  { id: "indicators", label: "Indicadores", icon: BarChart3 },
  { id: "memory", label: "Memória", icon: MemoryStick },
];

function ask(label: string, initial = ""): string | null {
  const value = window.prompt(label, initial);
  const trimmed = value?.trim();
  return trimmed || null;
}

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { ...init, headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) } });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof payload?.detail === "string" ? payload.detail : `HTTP ${response.status}`);
  return payload as T;
}

function badge(status: AgentStatus | TaskStatus): string {
  if (status === "trabalhando" || status === "andamento") return "border-success/30 bg-success/15 text-success";
  if (status === "aguardando") return "border-warning/30 bg-warning/15 text-warning";
  if (status === "erro") return "border-destructive/30 bg-destructive/15 text-destructive";
  if (status === "concluida") return "border-primary/30 bg-primary/10 text-primary";
  return "border-border bg-secondary text-muted-foreground";
}

const taskNames: Record<TaskStatus, string> = { pendente: "Pendente", andamento: "Em andamento", aguardando: "Aguardando", concluida: "Concluída", erro: "Erro" };
const memberNames: Record<AgentStatus, string> = { livre: "Livre", trabalhando: "Trabalhando", aguardando: "Aguardando", erro: "Erro" };

export function CompaniesOverlayHost() {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const key = (event: KeyboardEvent) => event.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);
  return <>
    <button type="button" onClick={() => setOpen(true)} className="hidden" data-testid="companies-launcher">
      <Building2 className="h-4 w-4 text-primary" /><span className="hidden min-[900px]:inline">Empresas</span>
    </button>
    {open && <Workspace onClose={() => setOpen(false)} />}
  </>;
}

function Workspace({ onClose }: { onClose: () => void }) {
  const [state, setState] = useState<CompaniesState>({ companies: [], activeCompanyId: null, version: 2 });
  const [tab, setTab] = useState<Tab>("overview");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const hydrated = useRef(false);
  const saveTimer = useRef<number | null>(null);

  const active = state.companies.find((item) => item.id === state.activeCompanyId) ?? state.companies[0];
  const activeId = active?.id ?? null;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const remote = await json<CompaniesState>(API);
      setState({ ...remote, companies: remote.companies.map((company) => ({ ...company, tasks: company.tasks ?? [] })) });
      setError(null);
      hydrated.current = true;
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Falha ao carregar empresas.");
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    if (!hydrated.current || loading) return;
    if (saveTimer.current) window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(async () => {
      setSaving(true);
      try { await json(API, { method: "PUT", body: JSON.stringify(state) }); setError(null); }
      catch (exc) { setError(exc instanceof Error ? exc.message : "Falha ao salvar."); }
      finally { setSaving(false); }
    }, 450);
    return () => { if (saveTimer.current) window.clearTimeout(saveTimer.current); };
  }, [state, loading]);

  const updateActive = useCallback((mutate: (company: Company) => Company) => {
    if (!activeId) return;
    setState((current) => ({ ...current, companies: current.companies.map((company) => company.id === activeId ? mutate(company) : company) }));
  }, [activeId]);

  const createCompany = async () => {
    const name = ask("Nome da empresa"); if (!name) return;
    const segment = ask("Segmento", "Empresa") ?? "Empresa";
    try {
      const company = await json<Company>(API, { method: "POST", body: JSON.stringify({ name, segment }) });
      hydrated.current = false;
      const remote = await json<CompaniesState>(API);
      setState({ ...remote, activeCompanyId: company.id });
      hydrated.current = true;
      setTab("overview");
    } catch (exc) { setError(exc instanceof Error ? exc.message : "Falha ao criar empresa."); }
  };

  const createDepartment = () => {
    if (!active) return;
    const name = ask("Nome do departamento"); if (!name) return;
    const floor = Math.max(1, Number.parseInt(ask("Andar", String(active.departments.length + 1)) ?? "1", 10) || 1);
    const mission = ask("Missão do departamento", "Responsabilidade deste setor.") ?? "Responsabilidade deste setor.";
    updateActive((company) => ({ ...company, departments: [...company.departments, { id: `dept-${Date.now()}`, name, floor, mission }] }));
  };

  const createMember = () => {
    if (!active?.departments.length) return;
    const name = ask("Nome do gerente, especialista ou funcionário"); if (!name) return;
    const role = ask("Cargo / especialidade", "Especialista") ?? "Especialista";
    const deptName = ask(`Departamento (${active.departments.map((d) => d.name).join(", ")})`, active.departments[0].name);
    const department = active.departments.find((d) => d.name.toLowerCase() === deptName?.toLowerCase()) ?? active.departments[0];
    const raw = (ask("Tipo: gerente, especialista ou funcionario", "especialista") ?? "especialista").toLowerCase();
    const kind: Member["kind"] = raw.startsWith("ger") ? "gerente" : raw.startsWith("fun") ? "funcionario" : "especialista";
    updateActive((company) => ({ ...company, members: [...company.members, { id: `member-${Date.now()}`, name, role, departmentId: department.id, kind, status: "livre", model: "JARVIS", autonomy: kind === "gerente" ? "autonomo" : "semi-autonomo" }] }));
  };

  const companyPrompt = useCallback((member: Member, instruction: string) => {
    if (!active) return instruction;
    const department = active.departments.find((item) => item.id === member.departmentId);
    return [
      `EMPRESA: ${active.name}`, `SEGMENTO: ${active.segment}`,
      `DEPARTAMENTO: ${department?.name ?? "Não definido"}`, `RESPONSÁVEL: ${member.name}`,
      `FUNÇÃO: ${member.role}`, `AUTONOMIA: ${member.autonomy}`, "",
      "MEMÓRIA E REGRAS DA EMPRESA:", ...(active.memory.length ? active.memory.map((item) => `- ${item}`) : ["- Sem regras adicionais cadastradas."]),
      "", "TAREFA:", instruction, "",
      "Execute a tarefa usando as ferramentas disponíveis no JARVIS. Preserve o contexto desta empresa, registre dependências e peça confirmação quando uma ação sensível exigir autorização.",
    ].join("\n");
  }, [active]);

  const delegate = useCallback(async (member: Member) => {
    if (!active) return;
    const instruction = ask(`O que ${member.name} deve fazer?`); if (!instruction) return;
    const prompt = companyPrompt(member, instruction);
    const dispatch = async (confirmed: boolean): Promise<{ mission_id: string }> => {
      const response = await fetch("/api/missions/dispatch", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt, language: "pt", confirmed }) });
      const payload = await response.json().catch(() => ({}));
      if (response.status === 409 && payload?.requires_confirm && !confirmed) {
        if (window.confirm(`O JARVIS detectou uma ação sensível (${payload.matched_text ?? "ação"}). Autorizar esta missão?`)) return dispatch(true);
        throw new Error("Missão cancelada pelo usuário.");
      }
      if (!response.ok) throw new Error(payload?.detail ?? `HTTP ${response.status}`);
      return payload as { mission_id: string };
    };
    try {
      const result = await dispatch(false);
      const task: BusinessTask = { id: `task-${Date.now()}`, title: instruction.length > 90 ? `${instruction.slice(0, 87)}…` : instruction, description: instruction, assigneeId: member.id, departmentId: member.departmentId, status: "andamento", missionId: result.mission_id, createdAt: new Date().toISOString(), updatedAt: new Date().toISOString() };
      updateActive((company) => ({ ...company, tasks: [task, ...company.tasks], members: company.members.map((item) => item.id === member.id ? { ...item, status: "trabalhando", currentTask: instruction, missionId: result.mission_id } : item) }));
      setTab("tasks");
    } catch (exc) { setError(exc instanceof Error ? exc.message : "Falha ao delegar missão."); }
  }, [active, companyPrompt, updateActive]);

  const missionSignature = active?.tasks.filter((task) => task.missionId && (task.status === "andamento" || task.status === "aguardando")).map((task) => `${task.id}:${task.missionId}:${task.status}`).join("|") ?? "";
  useEffect(() => {
    if (!activeId || !missionSignature) return;
    let dead = false;
    const poll = async () => {
      const company = state.companies.find((item) => item.id === activeId); if (!company) return;
      const running = company.tasks.filter((task) => task.missionId && (task.status === "andamento" || task.status === "aguardando"));
      const changes = new Map<string, TaskStatus>();
      await Promise.all(running.slice(0, 20).map(async (task) => {
        try {
          const response = await fetch(`/api/missions/${task.missionId}`); if (!response.ok) return;
          const body = await response.json(); const raw = String(body?.mission?.state ?? "").toUpperCase();
          const next: TaskStatus = ["APPROVED", "COMPLETED", "SUCCEEDED"].includes(raw) ? "concluida" : ["FAILED", "CANCELLED", "TIMED_OUT"].includes(raw) ? "erro" : ["PENDING", "WAITING", "PAUSED"].includes(raw) ? "aguardando" : "andamento";
          if (next !== task.status) changes.set(task.id, next);
        } catch { /* keep local state on temporary read errors */ }
      }));
      if (dead || !changes.size) return;
      updateActive((current) => {
        const tasks = current.tasks.map((task) => changes.has(task.id) ? { ...task, status: changes.get(task.id)!, updatedAt: new Date().toISOString() } : task);
        const live = new Set(tasks.filter((task) => task.status === "andamento" || task.status === "aguardando").map((task) => task.missionId));
        const members = current.members.map((member) => member.missionId && !live.has(member.missionId) ? { ...member, status: "livre" as AgentStatus, currentTask: null, missionId: null } : member);
        return { ...current, tasks, members };
      });
    };
    void poll(); const timer = window.setInterval(() => void poll(), 8000);
    return () => { dead = true; window.clearInterval(timer); };
  // state is intentionally read as a snapshot; missionSignature changes whenever a live task changes.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId, missionSignature, updateActive]);

  const createAutomation = async () => {
    if (!active) return;
    const title = ask("Nome da automação"); if (!title) return;
    const instruction = ask("O que o JARVIS deve fazer automaticamente?"); if (!instruction) return;
    const hours = Number.parseFloat(ask("Repetir a cada quantas horas?", "24") ?? "24");
    if (!Number.isFinite(hours) || hours <= 0) { setError("Intervalo inválido."); return; }
    const manager = active.members.find((item) => item.kind === "gerente") ?? active.members[0];
    const prompt = manager ? companyPrompt(manager, instruction) : `EMPRESA: ${active.name}\nTAREFA AUTOMÁTICA: ${instruction}`;
    try {
      const result = await json<{ id: string }>("/api/tasks", { method: "POST", body: JSON.stringify({ title: `[${active.name}] ${title}`, trigger: { type: "every", interval_seconds: hours * 3600 }, action: { kind: "agent", prompt, model_tier: "auto", plugin_grants: [] }, created_by: "user", tags: [`company:${active.id}`, "jarvis-business"] }) });
      updateActive((company) => ({ ...company, automations: [...company.automations, `${title} · a cada ${hours}h · ${result.id}`] }));
    } catch (exc) { setError(exc instanceof Error ? exc.message : "Falha ao criar automação."); }
  };

  const uploadFiles = async (files: FileList | null) => {
    if (!active || !files?.length) return;
    const form = new FormData(); Array.from(files).forEach((file) => form.append("files", file));
    form.append("thread_id", `company-${active.id}`); form.append("surface", "jarvis-business");
    try {
      const response = await fetch("/api/chat/drop", { method: "POST", body: form });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload?.detail ?? `HTTP ${response.status}`);
      const names = Array.from(files).map((file) => file.name);
      updateActive((company) => ({ ...company, files: [...company.files, ...names.filter((name) => !company.files.includes(name))] }));
    } catch (exc) { setError(exc instanceof Error ? exc.message : "Falha ao enviar arquivo."); }
  };

  if (loading) return <div className="fixed inset-0 z-[100] grid place-items-center bg-background"><div className="flex items-center gap-3 text-sm text-muted-foreground"><LoaderCircle className="h-5 w-5 animate-spin" />Carregando JARVIS Business OS…</div></div>;

  return <div className="fixed inset-0 z-[100] flex bg-background text-foreground" data-testid="companies-workspace">
    <aside className="flex w-[270px] shrink-0 flex-col border-r border-border bg-card/70 backdrop-blur-xl">
      <div className="flex h-16 items-center justify-between border-b border-border px-4"><div className="flex items-center gap-2.5"><div className="grid h-9 w-9 place-items-center rounded-xl border border-primary/30 bg-primary/10 text-primary"><Building2 className="h-4 w-4" /></div><div><div className="text-sm font-semibold">Empresas</div><div className="text-[10px] tracking-[0.18em] text-muted-foreground">JARVIS BUSINESS OS</div></div></div><button type="button" onClick={onClose} className="rounded-lg p-2 text-muted-foreground hover:bg-secondary hover:text-foreground"><X className="h-4 w-4" /></button></div>
      <div className="p-3"><button type="button" onClick={() => void createCompany()} className="flex w-full items-center justify-center gap-2 rounded-lg border border-dashed border-border px-3 py-2.5 text-xs text-muted-foreground hover:border-primary/50 hover:text-foreground"><Plus className="h-3.5 w-3.5" />Adicionar empresa</button></div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2">{state.companies.map((company) => <button key={company.id} type="button" onClick={() => { setState((current) => ({ ...current, activeCompanyId: company.id })); setTab("overview"); }} className={cn("mb-1 w-full rounded-xl border px-3 py-3 text-left", company.id === activeId ? "border-primary/25 bg-primary/10" : "border-transparent text-muted-foreground hover:bg-secondary/60 hover:text-foreground")}><div className="truncate text-sm font-semibold">{company.name}</div><div className="mt-0.5 truncate text-[11px] opacity-70">{company.segment}</div></button>)}</div>
      <div className="border-t border-border p-3 text-[10px] text-muted-foreground">{saving ? <span className="flex items-center gap-1.5"><LoaderCircle className="h-3 w-3 animate-spin" />Salvando…</span> : <span className="flex items-center gap-1.5"><CheckCircle2 className="h-3 w-3" />Persistido no JARVIS</span>}</div>
    </aside>
    <div className="flex min-w-0 flex-1 flex-col">
      <header className="flex min-h-16 items-center justify-between gap-4 border-b border-border px-6"><div className="min-w-0"><div className="text-[10px] uppercase tracking-[0.2em] text-muted-foreground">Central empresarial</div><h1 className="truncate text-xl font-semibold">{active?.name ?? "Empresas"}</h1></div><div className="flex items-center gap-2">{error && <span className="hidden max-w-sm truncate rounded-full border border-destructive/30 bg-destructive/10 px-3 py-1 text-[11px] text-destructive lg:block" title={error}>{error}</span>}<button type="button" onClick={() => void load()} className="rounded-lg border border-border p-2 text-muted-foreground hover:bg-secondary"><RefreshCw className="h-4 w-4" /></button></div></header>
      {active ? <><nav className="flex shrink-0 gap-1 overflow-x-auto border-b border-border px-4 py-2">{tabs.map((item) => { const Icon = item.icon; return <button key={item.id} type="button" onClick={() => setTab(item.id)} className={cn("inline-flex shrink-0 items-center gap-2 rounded-lg px-3 py-2 text-xs", tab === item.id ? "bg-secondary font-medium" : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground")}><Icon className="h-3.5 w-3.5" />{item.label}</button>; })}</nav><main className="min-h-0 flex-1 overflow-y-auto p-6">
        {tab === "overview" && <Overview company={active} setTab={setTab} />}
        {tab === "building" && <CompanyBuilding key={active.id} company={active} delegate={delegate} />}
        {tab === "departments" && <Departments company={active} add={createDepartment} />}
        {tab === "team" && <Team company={active} add={createMember} delegate={delegate} />}
        {tab === "tasks" && <Tasks company={active} delegate={delegate} />}
        {tab === "projects" && <List title="Projetos" icon={FolderKanban} values={active.projects.map((p) => `${p.name} · ${p.status} · ${p.owner}`)} add={() => { const name = ask("Nome do projeto"); if (name) updateActive((c) => ({ ...c, projects: [...c.projects, { id: `project-${Date.now()}`, name, status: "planejado", owner: ask("Responsável", "Gerente Geral") ?? "Gerente Geral" }] })); }} />}
        {tab === "clients" && <List title="Clientes" icon={BriefcaseBusiness} values={active.clients} add={() => { const value = ask("Nome do cliente"); if (value) updateActive((c) => ({ ...c, clients: [...c.clients, value] })); }} />}
        {tab === "files" && <Files company={active} upload={uploadFiles} />}
        {tab === "automations" && <List title="Automações reais" icon={Workflow} values={active.automations} add={() => void createAutomation()} footer="As automações são registradas no agendador nativo do JARVIS, não apenas nesta tela." />}
        {tab === "indicators" && <Indicators company={active} />}
        {tab === "memory" && <List title="Memória da empresa" icon={MemoryStick} values={active.memory} add={() => { const value = ask("Regra, contexto ou decisão para guardar"); if (value) updateActive((c) => ({ ...c, memory: [...c.memory, value] })); }} footer="Esta memória permanece isolada por empresa e entra no contexto das missões delegadas." />}
      </main></> : <Empty text="Crie a primeira empresa para começar." />}
    </div>
  </div>;
}

function Overview({ company, setTab }: { company: Company; setTab: (tab: Tab) => void }) {
  const activeTasks = company.tasks.filter((task) => task.status === "andamento" || task.status === "aguardando").length;
  const cards = [["Departamentos", company.departments.length, Network], ["Equipe / agentes", company.members.length, Users], ["Trabalhando agora", company.members.filter((m) => m.status === "trabalhando").length, Activity], ["Tarefas ativas", activeTasks, CheckCircle2], ["Projetos", company.projects.length, FolderKanban], ["Automações", company.automations.length, Workflow]] as const;
  return <div className="mx-auto max-w-7xl space-y-6"><div className="relative overflow-hidden rounded-2xl border border-primary/20 bg-card p-6"><div className="pointer-events-none absolute -right-16 -top-20 h-56 w-56 rounded-full bg-primary/10 blur-3xl" /><div className="relative flex flex-col justify-between gap-5 lg:flex-row lg:items-center"><div><div className="mb-2 inline-flex items-center gap-2 rounded-full border border-primary/20 bg-primary/10 px-2.5 py-1 text-[11px] text-primary"><Sparkles className="h-3 w-3" />JARVIS Company Command</div><h2 className="text-2xl font-semibold">{company.name}</h2><p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">{company.description}</p></div><div className="flex gap-2"><button type="button" onClick={() => setTab("tasks")} className="rounded-xl border border-border px-4 py-2.5 text-sm hover:bg-secondary">Tarefas</button><button type="button" onClick={() => setTab("building")} className="rounded-xl bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground">Abrir prédio</button></div></div></div><div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{cards.map(([label, value, Icon]) => <div key={label} className="rounded-xl border border-border bg-card p-4"><div className="flex justify-between text-xs text-muted-foreground"><span>{label}</span><Icon className="h-4 w-4" /></div><div className="mt-3 text-2xl font-semibold">{value}</div></div>)}</div></div>;
}


function Departments({ company, add }: { company: Company; add: () => void }) {
  return <div className="mx-auto max-w-6xl"><Header title="Departamentos" desc="Estrutura, andares e responsabilidades." action="Adicionar departamento" run={add} /><div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{company.departments.map((d) => <Card key={d.id}><div className="flex justify-between"><Network className="h-4 w-4" /><span className="text-[11px] text-muted-foreground">{d.floor}º andar</span></div><div className="mt-4 text-sm font-semibold">{d.name}</div><p className="mt-2 text-xs leading-5 text-muted-foreground">{d.mission}</p></Card>)}</div></div>;
}

function Team({ company, add, delegate }: { company: Company; add: () => void; delegate: (member: Member) => void }) {
  const [query, setQuery] = useState(""); const members = useMemo(() => company.members.filter((m) => `${m.name} ${m.role}`.toLowerCase().includes(query.toLowerCase())), [company.members, query]);
  return <div className="mx-auto max-w-7xl"><Header title="Equipe" desc="Gerentes, especialistas, funcionários e agentes." action="Adicionar pessoa/agente" run={add} /><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Buscar por nome ou cargo…" className="mb-4 h-10 w-full max-w-md rounded-lg border border-border bg-background px-3 text-sm outline-none focus:border-primary" /><div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{members.map((member) => { const dept = company.departments.find((d) => d.id === member.departmentId); return <Card key={member.id}><div className="flex justify-between"><div className="grid h-10 w-10 place-items-center rounded-xl bg-secondary"><Bot className="h-5 w-5" /></div><span className={cn("h-fit rounded-full border px-2 py-1 text-[10px]", badge(member.status))}>{memberNames[member.status]}</span></div><div className="mt-4 text-sm font-semibold">{member.name}</div><div className="text-xs text-muted-foreground">{member.role}</div>{member.currentTask && <div className="mt-3 rounded-lg bg-primary/5 p-2 text-[10px] text-primary">{member.currentTask}</div>}<div className="mt-4 grid grid-cols-2 gap-2"><Mini label="Departamento" value={dept?.name ?? "Sem setor"} /><Mini label="Tipo" value={member.kind} /><Mini label="Modelo" value={member.model} /><Mini label="Autonomia" value={member.autonomy} /></div><button type="button" onClick={() => delegate(member)} className="mt-4 flex w-full items-center justify-center gap-2 rounded-lg bg-primary px-3 py-2 text-[11px] font-semibold text-primary-foreground"><Send className="h-3.5 w-3.5" />Delegar tarefa</button></Card>; })}</div></div>;
}

function Tasks({ company, delegate }: { company: Company; delegate: (member: Member) => void }) {
  return <div className="mx-auto max-w-7xl"><Header title="Tarefas e missões" desc="Trabalho real delegado ao motor de missões do JARVIS e acompanhado automaticamente." action={company.members.length ? "Delegar nova tarefa" : undefined} run={company.members.length ? () => delegate(company.members[0]) : undefined} /><div className="space-y-3">{company.tasks.length ? company.tasks.map((task) => { const member = company.members.find((m) => m.id === task.assigneeId); return <Card key={task.id}><div className="flex flex-col justify-between gap-3 sm:flex-row"><div><div className="flex items-center gap-2"><div className="text-sm font-semibold">{task.title}</div><span className={cn("rounded-full border px-2 py-0.5 text-[10px]", badge(task.status))}>{taskNames[task.status]}</span></div><p className="mt-2 text-xs leading-5 text-muted-foreground">{task.description}</p><div className="mt-3 text-[10px] text-muted-foreground">{member?.name ?? "Sem responsável"}{task.missionId ? ` · missão ${task.missionId}` : ""}</div></div>{member && !["concluida", "erro"].includes(task.status) && <button type="button" onClick={() => delegate(member)} className="h-fit rounded-lg border border-border px-3 py-2 text-[11px] hover:bg-secondary">Nova delegação</button>}</div></Card>; }) : <Empty text="Nenhuma tarefa delegada ainda." />}</div></div>;
}

function Files({ company, upload }: { company: Company; upload: (files: FileList | null) => void }) {
  return <div className="mx-auto max-w-5xl"><Header title="Arquivos" desc="Envie documentos, imagens, planilhas, código e outros arquivos para o contexto nativo do JARVIS." /><label className="mb-4 flex cursor-pointer items-center justify-center gap-2 rounded-xl border border-dashed border-primary/30 bg-primary/5 p-5 text-sm text-primary hover:bg-primary/10"><Upload className="h-4 w-4" />Enviar arquivos para esta empresa<input type="file" multiple className="hidden" onChange={(event) => { void upload(event.target.files); event.currentTarget.value = ""; }} /></label><div className="rounded-xl border border-border bg-card">{company.files.length ? company.files.map((file) => <div key={file} className="flex items-center gap-3 border-b border-border px-4 py-3 last:border-0"><FileText className="h-4 w-4 text-muted-foreground" /><span className="text-sm">{file}</span></div>) : <Empty text="Nenhum arquivo vinculado." />}</div></div>;
}

function Indicators({ company }: { company: Company }) {
  const data = [["Agentes", company.members.length], ["Trabalhando", company.members.filter((m) => m.status === "trabalhando").length], ["Tarefas", company.tasks.length], ["Concluídas", company.tasks.filter((t) => t.status === "concluida").length], ["Projetos", company.projects.length], ["Automações", company.automations.length]];
  return <div className="mx-auto max-w-6xl"><Header title="Indicadores" desc="Painel operacional desta empresa." /><div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{data.map(([label, value]) => <Card key={String(label)}><div className="text-xs text-muted-foreground">{label}</div><div className="mt-4 text-3xl font-semibold">{value}</div></Card>)}</div></div>;
}

function List({ title, icon: Icon, values, add, footer }: { title: string; icon: typeof FileText; values: string[]; add: () => void; footer?: string }) {
  return <div className="mx-auto max-w-5xl"><Header title={title} desc={`Área de ${title.toLowerCase()} da empresa.`} action="Adicionar" run={add} /><div className="rounded-xl border border-border bg-card">{values.length ? values.map((value, i) => <div key={`${value}-${i}`} className="flex items-center gap-3 border-b border-border px-4 py-3 last:border-0"><div className="grid h-8 w-8 place-items-center rounded-lg bg-secondary"><Icon className="h-4 w-4" /></div><span className="text-sm">{value}</span></div>) : <Empty text="Nenhum item cadastrado." />}</div>{footer && <p className="mt-3 text-[11px] leading-5 text-muted-foreground">{footer}</p>}</div>;
}

function Header({ title, desc, action, run }: { title: string; desc: string; action?: string; run?: () => void }) { return <div className="mb-5 flex flex-col justify-between gap-3 sm:flex-row sm:items-end"><div><h2 className="text-xl font-semibold">{title}</h2><p className="mt-1 text-sm text-muted-foreground">{desc}</p></div>{action && run && <button type="button" onClick={run} className="flex items-center justify-center gap-2 rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-primary-foreground"><Plus className="h-3.5 w-3.5" />{action}</button>}</div>; }
function Card({ children }: { children: ReactNode }) { return <div className="rounded-xl border border-border bg-card p-5">{children}</div>; }
function Mini({ label, value }: { label: string; value: string }) { return <div className="rounded-lg bg-secondary/40 p-2 text-[10px]"><div className="text-muted-foreground">{label}</div><div className="mt-1 truncate capitalize">{value}</div></div>; }
function Empty({ text }: { text: string }) { return <div className="p-10 text-center text-xs text-muted-foreground">{text}</div>; }
