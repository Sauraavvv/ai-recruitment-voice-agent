"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { errorMessage } from "@/lib/api";
import { signup } from "@/services/auth";

const MIN_PASSWORD = 10;

const input =
  "h-10 w-full rounded-lg border border-[#34363d] bg-[#24262b] px-3 text-sm text-white " +
  "placeholder:text-zinc-500 outline-none transition " +
  "focus:border-[#2563eb] focus:ring-2 focus:ring-[#2563eb]/30";

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-2 block text-sm font-medium">{label}</span>
      {children}
      {hint && <span className="mt-1.5 block text-xs text-zinc-500">{hint}</span>}
    </label>
  );
}

export function SignupForm() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const password = String(form.get("password"));
    if (password !== String(form.get("confirm"))) {
      setError("Passwords don't match.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await signup({
        organization_name: String(form.get("organization")),
        name: String(form.get("name")),
        email: String(form.get("email")),
        password,
      });
      router.replace("/dashboard");
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
      <Field label="Company name">
        <input
          name="organization"
          autoComplete="organization"
          placeholder="Acme Hiring"
          required
          minLength={2}
          maxLength={200}
          className={input}
        />
      </Field>
      <Field label="Your name">
        <input
          name="name"
          autoComplete="name"
          placeholder="Asha Rao"
          required
          maxLength={200}
          className={input}
        />
      </Field>
      <Field label="Work email">
        <input
          name="email"
          type="email"
          autoComplete="email"
          placeholder="you@company.com"
          required
          maxLength={320}
          className={input}
        />
      </Field>
      <Field label="Password" hint={`At least ${MIN_PASSWORD} characters.`}>
        <input
          name="password"
          type="password"
          autoComplete="new-password"
          placeholder="••••••••••"
          required
          minLength={MIN_PASSWORD}
          maxLength={200}
          className={input}
        />
      </Field>
      <Field label="Confirm password">
        <input
          name="confirm"
          type="password"
          autoComplete="new-password"
          placeholder="••••••••••"
          required
          minLength={MIN_PASSWORD}
          maxLength={200}
          className={input}
        />
      </Field>
      <button
        type="submit"
        disabled={busy}
        className="mt-2 h-10 w-full rounded-lg bg-[#1d4ed8] text-sm font-semibold text-white transition hover:bg-[#2563eb] focus-visible:ring-2 focus-visible:ring-[#2563eb]/50 focus-visible:outline-none disabled:opacity-60"
      >
        {busy ? "Creating account…" : "Create account"}
      </button>
    </form>
  );
}
