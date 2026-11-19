import type { ReactNode } from "react";

/** A dashboard number. `definition` is the agreed meaning, shown as the tooltip. */
export function StatTile({
  label,
  value,
  definition,
  hint,
  tone,
}: {
  label: string;
  value: ReactNode;
  definition?: string;
  hint?: ReactNode;
  tone?: string;
}) {
  return (
    <div className="group relative rounded-3xl bg-[#18191c] p-5" title={definition}>
      <div className="flex items-center gap-1.5 text-xs font-medium tracking-wide text-zinc-500 uppercase">
        <span>{label}</span>
        {definition && (
          <span
            className="flex h-3.5 w-3.5 items-center justify-center rounded-full border border-zinc-600 text-[9px] text-zinc-500 normal-case"
            aria-hidden
          >
            i
          </span>
        )}
      </div>
      <div
        data-testid="stat-value"
        className={`font-display mt-2 text-3xl font-semibold tabular-nums ${tone ?? "text-white"}`}
      >
        {value}
      </div>
      {hint && <div className="mt-1 text-xs text-zinc-500">{hint}</div>}
      {definition && <span className="sr-only">{definition}</span>}
    </div>
  );
}
