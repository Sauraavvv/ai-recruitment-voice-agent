/**
 * A row of numbers in one dark bar, sized like the dashboard's statistics bar: small grey
 * label, 28px number, thin dividers. An item with `onClick` is a filter toggle; the active
 * one (`on`) only turns its label white, with no box around it.
 */
export type Kpi = {
  label: string;
  value: number | string;
  dot?: string;
  hint?: string;
  on?: boolean;
  onClick?: () => void;
};

export function KpiBar({ items }: { items: Kpi[] }) {
  const columns: Record<number, string> = {
    3: "sm:grid-cols-3",
    4: "sm:grid-cols-4",
    5: "sm:grid-cols-3 lg:grid-cols-5",
  };
  return (
    <div
      className={`grid grid-cols-2 gap-y-4 rounded-3xl bg-[#18191c] py-5 ${columns[items.length] ?? "sm:grid-cols-4"}`}
    >
      {items.map((k, i) => {
        const body = (
          <>
            <div
              className={`flex items-center gap-1.5 truncate text-xs transition ${
                k.on ? "text-white" : "text-zinc-400 group-hover:text-zinc-200"
              }`}
            >
              {k.dot && <span className={`h-[7px] w-[7px] shrink-0 rounded-full ${k.dot}`} />}
              {k.label}
            </div>
            <div className="font-display mt-2 text-[28px] leading-none font-semibold text-white tabular-nums">
              {k.value}
            </div>
            {k.hint && <div className="mt-1 text-[11px] text-zinc-500">{k.hint}</div>}
          </>
        );
        const edge = i > 0 ? "sm:border-l sm:border-white/[0.06]" : "";
        if (!k.onClick) {
          return (
            <div key={k.label} className={`min-w-0 px-4 xl:px-5 ${edge}`}>
              {body}
            </div>
          );
        }
        return (
          <button
            key={k.label}
            type="button"
            onClick={k.onClick}
            aria-pressed={k.on}
            className={`group min-w-0 px-4 text-left outline-none xl:px-5 ${edge}`}
          >
            {body}
          </button>
        );
      })}
    </div>
  );
}
