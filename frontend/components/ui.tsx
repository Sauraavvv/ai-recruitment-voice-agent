// Shared building blocks in HireCall's look: black page, dark-grey cards, blue primary action.
import type { ComponentProps, ReactNode } from "react";
import Link from "next/link";

export function PageHeader({
  title,
  subtitle,
  children,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="font-display text-2xl font-semibold text-white">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-zinc-500">{subtitle}</p>}
      </div>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </div>
  );
}

/** Dark-grey rounded panel, the same as the dashboard's cards. */
export function Card({
  title,
  description,
  action,
  children,
  className = "",
}: {
  title?: string;
  description?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-3xl bg-[#18191c] p-5 sm:p-6 ${className}`}>
      {(title || action) && (
        <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
          <div>
            {title && <h2 className="font-display text-base font-semibold text-white">{title}</h2>}
            {description && <p className="mt-1 text-sm text-zinc-500">{description}</p>}
          </div>
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

const BUTTON_STYLES = {
  primary: "bg-[#1d4ed8] text-white hover:bg-[#2563eb]",
  secondary: "border border-[#34363d] bg-[#24262b] text-zinc-200 hover:bg-[#2c2f35]",
  danger: "border border-red-500/30 bg-red-500/10 text-red-300 hover:bg-red-500/20",
};

export function buttonClass(variant: keyof typeof BUTTON_STYLES = "primary") {
  return (
    "inline-flex h-9 items-center justify-center rounded-lg px-3.5 text-sm font-medium transition " +
    "focus-visible:ring-2 focus-visible:ring-[#2563eb]/50 focus-visible:outline-none " +
    `disabled:cursor-not-allowed disabled:opacity-50 ${BUTTON_STYLES[variant]}`
  );
}

export function Button({
  variant = "primary",
  className = "",
  ...props
}: ComponentProps<"button"> & { variant?: keyof typeof BUTTON_STYLES }) {
  return <button type="button" className={`${buttonClass(variant)} ${className}`} {...props} />;
}

export const inputClass =
  "w-full rounded-lg border border-[#34363d] bg-[#24262b] px-3 py-2 text-sm text-white " +
  "placeholder:text-zinc-500 outline-none transition " +
  "focus:border-[#2563eb] focus:ring-2 focus:ring-[#2563eb]/30 disabled:opacity-60";

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: ReactNode;
  children: ReactNode;
}) {
  return (
    <label className="block text-sm">
      <span className="mb-2 block font-medium text-zinc-200">{label}</span>
      {children}
      {hint && <span className="mt-1.5 block text-xs text-zinc-500">{hint}</span>}
    </label>
  );
}

export function Alert({
  kind = "error",
  children,
}: {
  kind?: "error" | "success" | "info";
  children: ReactNode;
}) {
  const styles = {
    error: "border-red-500/30 bg-red-500/10 text-red-200",
    success: "border-green-500/30 bg-green-500/10 text-green-200",
    info: "border-white/10 bg-white/5 text-zinc-200",
  };
  return (
    <div
      role={kind === "error" ? "alert" : "status"}
      className={`rounded-xl border p-3 text-sm ${styles[kind]}`}
    >
      {children}
    </div>
  );
}

export function Muted({ children }: { children: ReactNode }) {
  return <p className="text-sm text-zinc-500">{children}</p>;
}

/** "← Back to …" above a page's title. */
export function BackLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link
      href={href}
      className="group mb-3 inline-flex items-center gap-1.5 rounded-lg text-sm text-zinc-500 transition hover:text-white focus-visible:ring-2 focus-visible:ring-white/30 focus-visible:outline-none"
    >
      <svg
        viewBox="0 0 24 24"
        className="h-4 w-4 transition group-hover:-translate-x-0.5"
        fill="none"
        stroke="currentColor"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d="M19 12H5" />
        <path d="m11 6-6 6 6 6" />
      </svg>
      {children}
    </Link>
  );
}
