import { Card } from "@/components/ui";
import { fieldLabel, formatDate } from "@/lib/labels";
import type { CandidateSummary } from "@/types";

/**
 * The candidate's summary: from the latest call that collected answers (else the latest call),
 * with the missing information and any callback request (phase-08 P8-T6).
 */
export function SummaryCard({ summary }: { summary: CandidateSummary | null | undefined }) {
  if (!summary) {
    return (
      <Card title="Summary">
        <p className="text-sm text-zinc-500">A summary appears here after the first call.</p>
      </Card>
    );
  }
  const callback = summary.callback_request as {
    time_text?: string | null;
    time_iso?: string | null;
    needs_recruiter?: boolean;
  } | null;
  return (
    <Card
      title="Summary"
      description={`From call #${summary.attempt_number ?? "?"} · ${formatDate(summary.finalized_at)}${
        summary.generated_by === "deterministic" ? " · facts only" : ""
      }`}
    >
      <p className="text-sm leading-relaxed text-zinc-200">
        {summary.text ?? "The summary is being written…"}
      </p>
      {summary.newer_call_without_data && (
        <p className="mt-3 text-xs text-zinc-500">
          A later call collected no answers, so this summary is from the last call that did.
        </p>
      )}
      {(summary.missing_information.length > 0 || callback) && (
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          {summary.missing_information.length > 0 && (
            <div className="rounded-2xl bg-[#202226] p-3.5">
              <div className="text-xs text-zinc-500">Missing information</div>
              <div className="mt-1 text-sm text-amber-200">
                {summary.missing_information.map(fieldLabel).join(", ")}
              </div>
            </div>
          )}
          {callback && (
            <div className="rounded-2xl bg-[#202226] p-3.5">
              <div className="text-xs text-zinc-500">Callback requested</div>
              <div className="mt-1 text-sm text-[#93b4ff]">
                {callback.time_iso
                  ? formatDate(callback.time_iso)
                  : callback.time_text || "No time given"}
                {callback.needs_recruiter && " · needs a recruiter to pick a time"}
              </div>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
