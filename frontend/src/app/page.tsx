import { API_URL } from "@/lib/api";

export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 bg-background px-6">
      <h1
        className="bg-clip-text text-5xl font-semibold tracking-tight text-transparent"
        style={{ backgroundImage: "var(--accent-gradient)" }}
      >
        Need Map
      </h1>
      <p className="text-muted-foreground">Ask what your audience wants. Coming soon.</p>
      <p className="font-mono text-xs text-muted-foreground/60">API: {API_URL}</p>
    </main>
  );
}
