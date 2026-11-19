// Status pills. The label is always text; colour only supports it (accessibility).
import {
  CALL_STATUS_LABELS,
  CALL_STATUS_TONE,
  FIELD_STATUS_LABELS,
  FIELD_STATUS_TONE,
  SCREENING_STATUS_LABELS,
  SCREENING_STATUS_TONE,
} from "@/lib/labels";

const NEUTRAL = "bg-white/5 text-zinc-400";
const LIVE = new Set(["in_progress", "ringing", "initiating"]);

export type BadgeKind = "call" | "screening" | "field";

export function badgeFor(kind: BadgeKind, status: string): { label: string; tone: string } {
  const [labels, tones] =
    kind === "call"
      ? [CALL_STATUS_LABELS, CALL_STATUS_TONE]
      : kind === "screening"
        ? [SCREENING_STATUS_LABELS, SCREENING_STATUS_TONE]
        : [FIELD_STATUS_LABELS, FIELD_STATUS_TONE];
  const fallback = status.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
  return { label: labels[status] ?? fallback, tone: tones[status] ?? NEUTRAL };
}

export function StatusBadge({
  kind,
  status,
  className = "",
  title,
}: {
  kind: BadgeKind;
  status: string;
  className?: string;
  title?: string;
}) {
  const { label, tone } = badgeFor(kind, status);
  const live = kind === "call" && LIVE.has(status);
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs whitespace-nowrap ${tone} ${className}`}
    >
      {live && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" aria-hidden />}
      {label}
    </span>
  );
}
