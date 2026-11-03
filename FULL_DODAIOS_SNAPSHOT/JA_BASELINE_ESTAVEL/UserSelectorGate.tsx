import { useEffect, useState } from "react";

type Profile = {
  id: string;
  display_name: string;
  role?: string;
};

type Props = {
  onSelected: (profileId: string) => void;
};

export function UserSelectorGate({ onSelected }: Props) {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [screen, setScreen] = useState<"select" | "create">("select");

  const [loading, setLoading] = useState(true);
  const [selecting, setSelecting] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [role, setRole] = useState<"user" | "administrator">("user");
  const [creating, setCreating] = useState(false);

  const [error, setError] = useState("");

  async function loadProfiles() {
    setLoading(true);

    try {
      const response = await fetch("/api/multiuser", {
        cache: "no-store",
      });

      if (!response.ok) {
        throw new Error(await response.text());
      }

      const data = await response.json();

      setProfiles(data.profiles ?? []);
      setError("");
    } catch {
      setError("Não foi possível carregar os usuários.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    try {
      const selected = window.sessionStorage.getItem("ja.selectedUser");

      if (selected) {
        onSelected(selected);
        return;
      }
    } catch {
      // segue fluxo normal
    }

    void loadProfiles();
  }, []);

  async function choose(profile: Profile) {
    if (selecting) return;

    setSelecting(profile.id);
    setError("");

    try {
      const selectRequest = fetch("/api/multiuser/select", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          profile_id: profile.id,
        }),
      });

      try {
        window.sessionStorage.setItem("ja.selectedUser", profile.id);
      } catch {
        // segue mesmo sem storage
      }

      // JA: interface abre enquanto a ativacao termina
      onSelected(profile.id);

      const response = await selectRequest;

      if (!response.ok) {
        throw new Error(await response.text());
      }

      
    } catch {
      setSelecting(null);
      setError("Não foi possível abrir este usuário.");
    }
  }

  async function createUser() {
    const cleanName = name.trim();

    if (!cleanName) {
      setError("Digite o nome do usuário.");
      return;
    }

    setCreating(true);
    setError("");

    try {
      const response = await fetch("/api/multiuser/create", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          display_name: cleanName,
          role,
        }),
      });

      if (!response.ok) {
        throw new Error(await response.text());
      }

      setName("");
      setRole("user");

      await loadProfiles();

      setScreen("select");
    } catch {
      setError("Não foi possível criar o usuário.");
    } finally {
      setCreating(false);
    }
  }

  if (screen === "create") {
    return (
      <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-[#080808] text-white">
        <div className="w-full max-w-xl px-8">

          <button
            type="button"
            onClick={() => {
              setError("");
              setScreen("select");
            }}
            className="mb-8 text-sm text-white/50 transition hover:text-white"
          >
            ← Voltar
          </button>

          <div className="mb-8">
            <div className="text-xs tracking-[0.45em] text-white/30">
              DODAIOS
            </div>

            <h1 className="mt-4 text-4xl font-semibold tracking-tight">
              Adicionar usuário
            </h1>

            <p className="mt-3 text-sm text-white/45">
              Crie um novo perfil para usar o DodaiOS.
            </p>
          </div>

          <div className="rounded-3xl border border-white/10 bg-white/[0.035] p-7">

            <label className="block text-sm text-white/60">
              Nome
            </label>

            <input
              autoFocus
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Nome do usuário"
              className="mt-2 w-full rounded-2xl border border-white/10 bg-black/30 px-4 py-4 text-white outline-none transition placeholder:text-white/20 focus:border-white/30"
            />

            <label className="mt-6 block text-sm text-white/60">
              Tipo de usuário
            </label>

            <div className="mt-2 grid grid-cols-2 gap-3">

              <button
                type="button"
                onClick={() => setRole("user")}
                className={`rounded-2xl border px-4 py-4 text-left transition ${
                  role === "user"
                    ? "border-white/35 bg-white/10"
                    : "border-white/10 bg-white/[0.03]"
                }`}
              >
                <div className="font-medium">Usuário</div>
                <div className="mt-1 text-xs text-white/40">
                  Perfil pessoal
                </div>
              </button>

              <button
                type="button"
                onClick={() => setRole("administrator")}
                className={`rounded-2xl border px-4 py-4 text-left transition ${
                  role === "administrator"
                    ? "border-white/35 bg-white/10"
                    : "border-white/10 bg-white/[0.03]"
                }`}
              >
                <div className="font-medium">Administrador</div>
                <div className="mt-1 text-xs text-white/40">
                  Acesso administrativo
                </div>
              </button>

            </div>

            {error && (
              <div className="mt-5 text-sm text-red-400">
                {error}
              </div>
            )}

            <button
              type="button"
              disabled={creating}
              onClick={() => void createUser()}
              className="mt-7 w-full rounded-2xl bg-white px-5 py-4 font-semibold text-black transition hover:bg-white/90 disabled:opacity-40"
            >
              {creating ? "Criando…" : "Criar usuário"}
            </button>

          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-[#080808] text-white">
      <div className="w-full max-w-4xl px-8">

        <div className="mb-10 text-center">

          <div className="text-xs tracking-[0.45em] text-white/30">
            DODAIOS
          </div>

          <h1 className="mt-4 text-4xl font-semibold tracking-tight">
            Quem está usando?
          </h1>

          <p className="mt-3 text-sm text-white/45">
            Selecione um usuário para continuar.
          </p>

        </div>

        {loading ? (
          <div className="text-center text-white/40">
            Carregando usuários…
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">

            {profiles.map((profile) => (
              <button
                key={profile.id}
                type="button"
                disabled={selecting !== null}
                onClick={() => void choose(profile)}
                className="rounded-3xl border border-white/10 bg-white/[0.04] px-7 py-7 text-left transition hover:border-white/25 hover:bg-white/[0.08] disabled:opacity-50"
              >
                <div className="flex items-center gap-5">

                  <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-white/10 text-xl font-semibold">
                    {profile.display_name.slice(0, 1).toUpperCase()}
                  </div>

                  <div>
                    <div className="text-lg font-medium">
                      {profile.display_name}
                    </div>

                    <div className="mt-1 text-xs text-white/35">
                      {selecting === profile.id
                        ? "Entrando…"
                        : profile.role === "administrator"
                          ? "Administrador"
                          : "Usuário"}
                    </div>
                  </div>

                </div>
              </button>
            ))}

            <button
              type="button"
              onClick={() => {
                setError("");
                setScreen("create");
              }}
              className="rounded-3xl border border-dashed border-white/15 bg-white/[0.025] px-7 py-7 text-left transition hover:border-white/30 hover:bg-white/[0.06]"
            >
              <div className="flex items-center gap-5">

                <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-white/10 text-3xl font-light">
                  +
                </div>

                <div>
                  <div className="text-lg font-medium">
                    Mais usuários
                  </div>

                  <div className="mt-1 text-xs text-white/35">
                    Criar e configurar outro perfil
                  </div>
                </div>

              </div>
            </button>

          </div>
        )}

        {error && screen === "select" && (
          <div className="mt-6 text-center text-sm text-red-400">
            {error}
          </div>
        )}

      </div>
    </div>
  );
}

