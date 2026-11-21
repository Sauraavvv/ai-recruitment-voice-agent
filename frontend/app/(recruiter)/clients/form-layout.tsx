import type { ReactNode } from "react";

/**
 * The look shared by the client and requirement forms: numbered sections, a label column, and
 * borderless inputs that sit on a line, so the form reads like a document beside its live card.
 */
export const line =
  "w-full border-0 border-b border-white/10 bg-transparent px-0 py-2 text-[15px] text-white " +
  "placeholder:text-zinc-600 outline-none transition focus:border-[#2563eb] disabled:opacity-50 " +
  "[&>option]:bg-[#18191c]";

/** A label beside its input. `as="div"` when the row holds several controls or buttons. */
export function Row({
  label,
  required,
  hint,
  as: Tag = "label",
  children,
}: {
  label: string;
  required?: boolean;
  hint?: ReactNode;
  as?: "label" | "div";
  children: ReactNode;
}) {
  return (
    <Tag className="grid items-start gap-1 sm:grid-cols-[150px_1fr] sm:gap-6">
      <span className="pt-2.5 text-xs font-medium tracking-wide text-zinc-500 uppercase">
        {label}
        {required && <span className="text-[#5b8cff]"> *</span>}
      </span>
      <span className="block min-w-0">
        {children}
        {hint && <span className="mt-1.5 block text-xs text-zinc-600">{hint}</span>}
      </span>
    </Tag>
  );
}

export function Section({
  n,
  title,
  note,
  children,
}: {
  n: string;
  title: string;
  note?: string;
  children: ReactNode;
}) {
  return (
    <section className="space-y-4">
      <h2 className="flex items-center gap-3 text-sm font-semibold text-white">
        <span className="font-display text-xs text-[#5b8cff]">{n}</span>
        {title}
        {note && <span className="text-xs font-normal text-zinc-600">{note}</span>}
        <span className="h-px flex-1 bg-white/5" />
      </h2>
      {children}
    </section>
  );
}

/** One choice out of a few, as pills. */
export function Pills<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
  label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="flex flex-wrap gap-2 py-1">
      {options.map((o) => {
        const on = value === o.value;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={on}
            onClick={() => onChange(o.value)}
            className={`rounded-full border px-3 py-1 text-xs transition ${
              on
                ? "border-[#2563eb] bg-[#2563eb]/15 text-white"
                : "border-white/10 text-zinc-400 hover:border-white/25 hover:text-zinc-200"
            }`}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
