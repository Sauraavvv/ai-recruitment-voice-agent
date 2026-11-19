"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, useState } from "react";

import { errorMessage } from "@/lib/api";
import { login } from "@/services/auth";

function safeNext(value: string | null) {
  // Only same-site paths, never "//evil.example".
  return value && value.startsWith("/") && !value.startsWith("//") ? value : "/dashboard";
}

const input =
  "h-10 w-full rounded-lg border border-[#34363d] bg-[#24262b] px-3 text-sm text-white " +
  "placeholder:text-zinc-500 outline-none transition " +
  "focus:border-[#2563eb] focus:ring-2 focus:ring-[#2563eb]/30";

export function LoginForm() {
  const router = useRouter();
  const next = safeNext(useSearchParams().get("next"));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    try {
      await login(String(form.get("email")), String(form.get("password")));
      router.replace(next);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-5">
      {error && (
        <p
          role="alert"
          className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300"
        >
          {error}
        </p>
      )}
      <label className="block">
        <span className="mb-2 block text-sm font-medium">Email</span>
        <input
          name="email"
          type="email"
          autoComplete="username"
          placeholder="you@company.com"
          required
          className={input}
        />
      </label>
      <label className="block">
        <span className="mb-2 block text-sm font-medium">Password</span>
        <input
          name="password"
          type="password"
          autoComplete="current-password"
          placeholder="••••••••••"
          required
          className={input}
        />
      </label>
      <button
        type="submit"
        disabled={busy}
        className="mt-2 h-10 w-full rounded-lg bg-[#1d4ed8] text-sm font-semibold text-white transition hover:bg-[#2563eb] focus-visible:ring-2 focus-visible:ring-[#2563eb]/50 focus-visible:outline-none disabled:opacity-60"
      >
        {busy ? "Signing in…" : "Sign in"}
      </button>
    </form>
  );
}
