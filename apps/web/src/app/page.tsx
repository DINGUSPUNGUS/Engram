const storageLayers = [
  {
    name: "Event log",
    role: "System of record",
    detail: "Append-only SQLite table. Every change is an immutable event.",
  },
  {
    name: "State tables",
    role: "Canonical runtime state",
    detail: "SQLite projections: search, graph, decay, analytics are queries.",
  },
  {
    name: "Markdown + git",
    role: "Portable representation & history",
    detail: "Human-readable export the user owns. Clone + rebuild = full state.",
  },
] as const;

export default function DashboardPage() {
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-10 px-6 py-16">
      <header className="flex flex-col gap-3">
        <p className="text-sm font-medium tracking-widest text-muted-foreground uppercase">
          pre-alpha · architecture phase
        </p>
        <h1 className="text-4xl font-bold tracking-tight">engram</h1>
        <p className="text-lg text-muted-foreground">
          One user-owned memory, shared by every AI assistant. This dashboard will show memories,
          timelines, and proposals once the engine exists.
        </p>
      </header>

      <section className="flex flex-col gap-4">
        <h2 className="text-xl font-semibold">How memory is stored</h2>
        <ul className="flex flex-col gap-3">
          {storageLayers.map((layer) => (
            <li key={layer.name} className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-baseline justify-between gap-4">
                <span className="font-medium">{layer.name}</span>
                <span className="text-sm text-muted-foreground">{layer.role}</span>
              </div>
              <p className="mt-1 text-sm text-muted-foreground">{layer.detail}</p>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
