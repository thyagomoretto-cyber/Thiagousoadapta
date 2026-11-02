import { useEffect } from "react";

const MAX_TODAY_CHATS = 4;

const IDS = {
  oldButton: "dodaios-btn-antigas",
  companiesButton: "dodaios-btn-empresas",
  restartButton: "dodaios-btn-reinicio",
  companiesPanel: "dodaios-panel-empresas",
};

const ATTR = {
  hiddenChat: "data-dodaios-hidden-chat",
  hiddenAgent: "data-dodaios-hidden-agent",
  hiddenAgentHeader: "data-dodaios-hidden-agent-header",
};

function normalize(value: string | null | undefined): string {
  return (value ?? "")
    .replace(/\s+/g, " ")
    .trim()
    .toLocaleLowerCase("pt-BR");
}

function isVisible(el: HTMLElement): boolean {
  const style = window.getComputedStyle(el);
  const rect = el.getBoundingClientRect();
  return (
    style.display !== "none" &&
    style.visibility !== "hidden" &&
    rect.width > 0 &&
    rect.height > 0
  );
}

function exactText(text: string): HTMLElement | null {
  const wanted = normalize(text);

  const all = Array.from(document.querySelectorAll<HTMLElement>("body *")).filter(
    (el) => normalize(el.textContent) === wanted && isVisible(el),
  );

  if (!all.length) return null;

  all.sort((a, b) => {
    const ar = a.getBoundingClientRect();
    const br = b.getBoundingClientRect();
    return ar.width * ar.height - br.width * br.height;
  });

  return all[0] ?? null;
}


function sidebarRoot(): HTMLElement | null {
  const hoje = exactText("Hoje");
  if (!hoje) return null;

  let node: HTMLElement | null = hoje.parentElement;

  while (node && node !== document.body) {
    const rect = node.getBoundingClientRect();
    if (rect.width >= 180 && rect.width <= 560 && rect.height > 300) {
      return node;
    }
    node = node.parentElement;
  }

  return null;
}

function dedupeNested(rows: HTMLElement[]): HTMLElement[] {
  return rows.filter(
    (candidate) =>
      !rows.some(
        (other) =>
          other !== candidate &&
          other.contains(candidate) &&
          other.getBoundingClientRect().width >= candidate.getBoundingClientRect().width,
      ),
  );
}

function getInteractiveRowsBetween(
  root: HTMLElement,
  topY: number,
  bottomY: number,
): HTMLElement[] {
  const rootRect = root.getBoundingClientRect();

  const forbidden = new Set([
    "novo chat",
    "agentes",
    "agentic ide",
    "feito para si",
    "voz de jarvis",
    "plugins / skills / mcp",
    "artefactos",
    "artefatos",
    "mais",
    "hoje",
    "antigas",
    "empresas",
    "reinício",
    "reinicio",
    "conversas antigas",
  ]);

  const raw = Array.from(
    root.querySelectorAll<HTMLElement>('button, a, [role="button"], [tabindex="0"]'),
  ).filter((el) => {
    if (!isVisible(el)) return false;

    if (
      el.id === IDS.oldButton ||
      el.id === IDS.companiesButton ||
      el.id === IDS.restartButton
    ) {
      return false;
    }

    const rect = el.getBoundingClientRect();
    if (rect.top <= topY + 2) return false;
    if (rect.bottom >= bottomY - 2) return false;

    if (rect.width < rootRect.width * 0.50) return false;
    if (rect.height < 24 || rect.height > 110) return false;

    const text = normalize(el.textContent);
    if (!text) return false;
    if (forbidden.has(text)) return false;

    return true;
  });

  const clean = dedupeNested(raw);

  clean.sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top);

  return clean;
}

function setHidden(el: HTMLElement, attr: string, hide: boolean): void {
  if (hide) {
    el.setAttribute(attr, "1");
    el.style.setProperty("display", "none", "important");
  } else {
    el.removeAttribute(attr);
    el.style.removeProperty("display");
  }
}

function restoreHidden(attr: string): void {
  document.querySelectorAll<HTMLElement>(`[${attr}="1"]`).forEach((el) => {
    el.removeAttribute(attr);
    el.style.removeProperty("display");
  });
}

function agentRows(root: HTMLElement): HTMLElement[] {
  const agentesHeader = exactText("Agentes");
  const hojeHeader = exactText("Hoje");

  if (!agentesHeader || !hojeHeader) return [];

  const top = agentesHeader.getBoundingClientRect().bottom;
  const bottom = hojeHeader.getBoundingClientRect().top;

  return getInteractiveRowsBetween(root, top, bottom);
}

function hideAgentSection(root: HTMLElement): HTMLElement[] {
  restoreHidden(ATTR.hiddenAgent);
  restoreHidden(ATTR.hiddenAgentHeader);

  const agentesHeader = exactText("Agentes");
  const rows = agentRows(root);

  if (agentesHeader) {
    setHidden(agentesHeader, ATTR.hiddenAgentHeader, true);
  }

  rows.forEach((row) => setHidden(row, ATTR.hiddenAgent, true));

  return rows;
}

function bestLabel(el: HTMLElement): string {
  const lines = (el.innerText || el.textContent || "")
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);

  if (!lines.length) return "Item";

  lines.sort((a, b) => b.length - a.length);
  return lines[0];
}

function ensureButtons(root: HTMLElement): {
  oldButton: HTMLButtonElement;
  companiesButton: HTMLButtonElement;
  restartButton: HTMLButtonElement;
} {
  const makeButton = (id: string, label: string) => {
    let btn = document.getElementById(id) as HTMLButtonElement | null;

    if (!btn) {
      btn = document.createElement("button");
      btn.id = id;
      btn.type = "button";
      btn.textContent = label;

      Object.assign(btn.style, {
        position: "fixed",
        zIndex: "9998",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        textAlign: "center",
        borderRadius: "14px",
        border: "1px solid rgba(255,255,255,0.18)",
        background: "rgba(18,18,18,0.98)",
        color: "#f3f3f3",
        fontSize: "15px",
        fontWeight: "600",
        letterSpacing: "0",
        height: "58px",
        padding: "0 10px",
        boxSizing: "border-box",
        cursor: "pointer",
        backdropFilter: "blur(14px)",
        boxShadow: "0 0 0 1px rgba(255,255,255,0.03) inset",
      });

      document.body.appendChild(btn);
    }

    return btn;
  };

  const oldButton = makeButton(IDS.oldButton, "Antigas");
  const companiesButton = makeButton(IDS.companiesButton, "Empresas");
  const restartButton = makeButton(IDS.restartButton, "Reinício");

  const rect = root.getBoundingClientRect();

  const sidePadding = 22;
  const gap = 10;
  const width = Math.floor((rect.width - sidePadding * 2 - gap) / 2);
  const height = 58;

  const leftX = Math.round(rect.left + sidePadding);
  const rightX = leftX + width + gap;

  const bottomY = Math.round(window.innerHeight - 108);
  const topY = bottomY - height - 8;

  [oldButton, companiesButton, restartButton].forEach((btn) => {
    btn.style.width = `${width}px`;
    btn.style.height = `${height}px`;
    btn.style.fontSize = "15px";
  });

  oldButton.style.left = `${leftX}px`;
  oldButton.style.top = `${topY}px`;

  companiesButton.style.left = `${leftX}px`;
  companiesButton.style.top = `${bottomY}px`;

  restartButton.style.left = `${rightX}px`;
  restartButton.style.top = `${bottomY}px`;

  return { oldButton, companiesButton, restartButton };
}

function ensureCompaniesPanel(
  companiesButton: HTMLButtonElement,
  hiddenAgents: HTMLElement[],
): HTMLDivElement {
  let panel = document.getElementById(IDS.companiesPanel) as HTMLDivElement | null;

  if (!panel) {
    panel = document.createElement("div");
    panel.id = IDS.companiesPanel;

    Object.assign(panel.style, {
      position: "fixed",
      zIndex: "9999",
      display: "none",
      borderRadius: "16px",
      border: "1px solid rgba(255,255,255,0.12)",
      background: "rgba(12,12,12,0.98)",
      color: "#f3f3f3",
      boxSizing: "border-box",
      padding: "14px",
      backdropFilter: "blur(16px)",
      boxShadow: "0 10px 30px rgba(0,0,0,0.35)",
      maxHeight: "50vh",
      overflowY: "auto",
    });

    document.body.appendChild(panel);
  }

  const btnRect = companiesButton.getBoundingClientRect();
  const width = btnRect.width * 2 + 10;

  panel.style.left = `${btnRect.left}px`;
  panel.style.top = `${Math.max(40, btnRect.top - 16 - 260)}px`;
  panel.style.width = `${width}px`;

  panel.innerHTML = "";

  const title = document.createElement("div");
  title.textContent = "Empresas";
  Object.assign(title.style, {
    fontSize: "16px",
    fontWeight: "700",
    marginBottom: "10px",
  });

  const subtitle = document.createElement("div");
  subtitle.textContent = "Agentes";
  Object.assign(subtitle.style, {
    fontSize: "13px",
    fontWeight: "600",
    opacity: "0.72",
    marginBottom: "10px",
  });

  panel.appendChild(title);
  panel.appendChild(subtitle);

  if (!hiddenAgents.length) {
    const empty = document.createElement("div");
    empty.textContent = "Sem agentes disponíveis";
    Object.assign(empty.style, {
      fontSize: "14px",
      opacity: "0.72",
      padding: "10px 0",
    });
    panel.appendChild(empty);
    return panel;
  }

  hiddenAgents.forEach((agent) => {
    const row = document.createElement("button");
    row.type = "button";
    row.textContent = bestLabel(agent);

    Object.assign(row.style, {
      width: "100%",
      minHeight: "44px",
      borderRadius: "12px",
      border: "1px solid rgba(255,255,255,0.10)",
      background: "rgba(28,28,28,0.98)",
      color: "#f3f3f3",
      fontSize: "14px",
      fontWeight: "600",
      padding: "0 12px",
      marginBottom: "8px",
      textAlign: "left",
      cursor: "pointer",
    });

    row.addEventListener("click", () => {
      panel!.style.display = "none";
      agent.click();
    });

    panel.appendChild(row);
  });

  return panel;
}

function restartApp(): void {
  fetch("/api/app/restart", { method: "POST" }).catch(() => {});
  setTimeout(() => {
    window.location.reload();
  }, 450);
}

export function CompactChatHistory() {
  useEffect(() => {
    let showOld = false;
    let disposed = false;
    let timer: number | undefined;

    const apply = () => {
      if (disposed) return;

      const root = sidebarRoot();
      if (!root) return;

      const hiddenAgents = hideAgentSection(root);
      const { oldButton, companiesButton, restartButton } = ensureButtons(root);
      const panel = ensureCompaniesPanel(companiesButton, hiddenAgents);

      const hojeHeader = exactText("Hoje");
      if (hojeHeader) {
        const top = hojeHeader.getBoundingClientRect().bottom;
        const bottom = oldButton.getBoundingClientRect().top - 8;
        restoreHidden(ATTR.hiddenChat);

        const chats = getInteractiveRowsBetween(root, top, bottom);

        if (!showOld) {
          chats.slice(MAX_TODAY_CHATS).forEach((chat) => {
            setHidden(chat, ATTR.hiddenChat, true);
          });
        }
      }

      oldButton.onclick = () => {
        showOld = !showOld;
        oldButton.textContent = showOld ? "Ocultar" : "Antigas";
        apply();
      };

      companiesButton.onclick = () => {
        panel.style.display = panel.style.display === "block" ? "none" : "block";
      };

      restartButton.onclick = () => {
        restartApp();
      };

      document.addEventListener("click", (ev) => {
        const target = ev.target as Node | null;
        if (!target) return;
        if (
          panel.style.display === "block" &&
          !panel.contains(target) &&
          target !== companiesButton
        ) {
          panel.style.display = "none";
        }
      });
    };

    const schedule = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(apply, 120);
    };

    apply();

    const observer = new MutationObserver(schedule);
    observer.observe(document.body, {
      subtree: true,
      childList: true,
      characterData: true,
      attributes: true,
    });

    window.addEventListener("resize", schedule);

    return () => {
      disposed = true;
      observer.disconnect();
      window.removeEventListener("resize", schedule);
      window.clearTimeout(timer);

      restoreHidden(ATTR.hiddenChat);
      restoreHidden(ATTR.hiddenAgent);
      restoreHidden(ATTR.hiddenAgentHeader);

      document.getElementById(IDS.oldButton)?.remove();
      document.getElementById(IDS.companiesButton)?.remove();
      document.getElementById(IDS.restartButton)?.remove();
      document.getElementById(IDS.companiesPanel)?.remove();
    };
  }, []);

  return null;
}

export default CompactChatHistory;
