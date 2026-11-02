import { useState } from "react";
import { RotateCw } from "lucide-react";

export function RestartDodaiOSButton() {
  const [loading, setLoading] = useState(false);

  async function restart() {
    if (loading) return;

    setLoading(true);

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
      setLoading(false);
      window.alert("Não foi possível reiniciar o DodaiOS.");
    }
  }

  return (
    <button
      type="button"
      onClick={restart}
      disabled={loading}
      title="Reiniciar DodaiOS"
      aria-label="Reiniciar DodaiOS"
      className="
        fixed
        left-[120px]
        bottom-[28px]
        z-[9999]

        flex
        h-[38px]
        w-[107px]
        items-center
        justify-center
        gap-2

        rounded-xl
        border
        border-border
        bg-background
        px-3

        text-sm
        font-semibold
        text-foreground

        shadow-md
        transition

        hover:bg-accent
        disabled:cursor-wait
        disabled:opacity-60
      "
    >
      <RotateCw
        className={`h-4 w-4 shrink-0 ${loading ? "animate-spin" : ""}`}
      />

      <span>Reinício</span>
    </button>
  );
}
