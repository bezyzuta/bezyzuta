"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";

export default function AdminLoginPage() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    const res = await fetch("/api/admin/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    setLoading(false);
    if (res.ok) {
      router.replace("/admin");
      router.refresh();
    } else {
      setError("Falsches Passwort.");
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-brand-cream px-4">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm space-y-5 rounded-2xl bg-white p-8 shadow-xl ring-1 ring-brand-ink/5"
      >
        <div>
          <p className="font-serif text-2xl text-brand-ink">
            <span className="text-brand-red">Swiss</span>Moments
          </p>
          <p className="mt-1 text-sm text-brand-ink/60">Admin-Bereich</p>
        </div>
        <div>
          <label
            htmlFor="password"
            className="block text-sm font-medium text-brand-ink"
          >
            Passwort
          </label>
          <input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="mt-2 block w-full rounded-lg border border-brand-ink/15 bg-brand-cream/40 px-4 py-2.5 text-sm outline-none focus:border-brand-red focus:ring-2 focus:ring-brand-red/20"
          />
        </div>
        {error && <p className="text-sm text-brand-red">{error}</p>}
        <Button type="submit" className="w-full" disabled={loading}>
          {loading ? "Anmelden…" : "Anmelden"}
        </Button>
      </form>
    </div>
  );
}
