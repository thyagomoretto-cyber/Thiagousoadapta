import { useEffect, useRef, useState } from "react";
import { Building2, RotateCw, X } from "lucide-react";

import SidebarAgents from "@/components/layout/SidebarAgents";

export default function SidebarBottomActions() {
  const [companiesOpen, setCompaniesOpen] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!companiesOpen) return;

    const close = (event: MouseEvent) => {
      const target = event.target as Node | null;
      if (
        target &&
        wrapperRef.current &&
        !wrapperRef.current.contains(target)
      ) {
        setCompaniesOpen(false);
      }
    };

    document.addEventListener("mousedown", close);

    return () => {
      document.removeEventListener("mousedown", close);
    };
  }, [companiesOpen]);

  async function restart() {
    if (restarting) return;

    setRestarting(true);

    try {
      const response = await fetch("/api/settings/restart-app", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      
    } catch (error) {
      console.error("Erro ao reiniciar DodaiOS:", error);
      setRestarting(false);
      window.alert("Não foi possível reiniciar o DodaiOS.");
    }
  }

  function openBusinessCenter() {
    const launcher = document.querySelector(
      '[data-testid="companies-launcher"]',
    ) as HTMLButtonElement | null;

    launcher?.click();
    setCompaniesOpen(false);
  }

  return (
    <div ref={wrapperRef} className="relative px-2 pb-2">
      {companiesOpen && (
        <div
          className="
            absolute
            bottom-full
            left-2
            right-2
            z-[90]
            mb-2
            max-h-[55vh]
            overflow-y-auto
            rounded-xl
            border
            border-border
            bg-background
            p-2
            shadow-xl
          "
        >
          <div className="mb-2 flex items-center justify-between px-2 py-1">
            <span className="text-sm font-semibold">Empresas</span>

            <button
              type="button"
              onClick={() => setCompaniesOpen(false)}
              aria-label="Fechar Empresas"
              className="
                flex h-7 w-7 items-center justify-center
                rounded-md
                text-muted-foreground
                hover:bg-secondary
                hover:text-foreground
              "
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          <button
            type="button"
            onClick={openBusinessCenter}
            className="
              mb-2
              flex h-9 w-full items-center gap-2
              rounded-lg
              px-3
              text-left
              text-sm
              text-foreground
              hover:bg-secondary
            "
          >
            <Building2 className="h-4 w-4 shrink-0" />
            <span>Central empresarial</span>
          </button>

          <div className="border-t border-border pt-2">
            <SidebarAgents />
          </div>
        </div>
      )}

      <div className="flex gap-1">
        <button
          type="button"
          onClick={() => setCompaniesOpen((value) => !value)}
          className="
            flex h-9 min-w-0 flex-1
            items-center justify-center gap-2
            rounded-lg
            border border-border
            bg-background
            px-2
            text-sm font-medium
            text-foreground
            transition-colors
            hover:bg-secondary
          "
        >
          <Building2 className="h-4 w-4 shrink-0" />
          <span className="truncate">Empresas</span>
        </button>

        <button
          type="button"
          onClick={restart}
          disabled={restarting}
          className="
            flex h-9 min-w-0 flex-1
            items-center justify-center gap-2
            rounded-lg
            border border-border
            bg-background
            px-2
            text-sm font-medium
            text-foreground
            transition-colors
            hover:bg-secondary
            disabled:cursor-wait
            disabled:opacity-60
          "
        >
          <RotateCw
            className={`h-4 w-4 shrink-0 ${
              restarting ? "animate-spin" : ""
            }`}
          />

          <span className="truncate">Reinício</span>
        </button>
      </div>
    </div>
  );
}

