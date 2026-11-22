"use client";

import type { EvaluationBadgeData, QuestionScore, RoundEvaluation, Verdict } from "@/types";

export const AI_NOTE = "AI recommendation — the recruiter decides";

export const VERDICT: Record<Verdict, { label: string; tone: string }> = {
  strong_fit: { label: "Strong fit", tone: "bg-green-500/10 text-green-300" },
  possible_fit: { label: "Possible fit", tone: "bg-amber-400/10 text-amber-300" },
  not_a_fit: { label: "Not a fit", tone: "bg-red-500/10 text-red-300" },
};

const ERRORS: Record<string, string> = {
  ai_timeout: "the AI took too long",
  ai_unavailable: "the AI service was busy",
  ai_rejected: "the AI service rejected the request",
  bad_output: "the AI's scores couldn't be checked against the answers",
  ai_not_configured: "the evaluating AI isn't set up",
};

export function errorText(code: string | null | undefined): string {
  return ERRORS[code ?? ""] ?? "something went wrong";
}

/** A score per answer: "4/5", or a dash for a question that wasn't asked. */
export function scoreText(score: QuestionScore): string {
  return score.score == null ? "—" : `${score.score}/5`;
}

function scoreTone(score: number | null): string {
  if (score == null) return "text-zinc-500";
  if (score >= 4) return "text-green-300";
  if (score >= 2) return "text-amber-300";
  return "text-red-300";
}

export function QuestionScoreView({ score }: { score: QuestionScore }) {
  return (
    <div className="rounded-xl bg-white/[0.03] px-3 py-2 text-xs">
      <span className={`font-semibold tabular-nums ${scoreTone(score.score)}`}>
        {scoreText(score)}
      </span>{" "}
      <span className="text-zinc-400">{score.reason}</span>
      {score.quote && <span className="text-zinc-500"> · “{score.quote}”</span>}
    </div>
  );
}

/** The verdict and score on a row (roster, calls list). Nothing when never evaluated. */
export function EvaluationBadge({ badge }: { badge: EvaluationBadgeData | null | undefined }) {
  if (!badge || badge.state === "skipped") return null;
  if (badge.score == null || badge.verdict == null) {
    if (badge.state === "pending")
      return <span className="animate-pulse text-xs text-zinc-500">Evaluating…</span>;
    if (badge.state === "failed")
      return (
        <span className="text-xs text-zinc-500" title="The AI evaluation failed">
          Not evaluated
        </span>
      );
    return null;
  }
  const verdict = VERDICT[badge.verdict];
  return (
    <span
      className={`rounded-md px-2 py-0.5 text-xs font-medium whitespace-nowrap tabular-nums ${verdict.tone} ${
        badge.state === "pending" ? "opacity-60" : ""
      }`}
      title={`${AI_NOTE}${badge.incomplete ? ". Only the questions asked were scored." : ""}`}
    >
      {verdict.label} · {badge.score}
      {badge.incomplete && <span className="font-normal opacity-80"> · incomplete</span>}
    </span>
  );
}

/** The round's overall evaluation above the answers, with Re-evaluate. */
export function EvaluationPanel({
  evaluation,
  finalized,
  busy,
  error,
  onReevaluate,
}: {
  evaluation: RoundEvaluation | null | undefined;
  finalized: boolean;
  busy: boolean;
  error: string | null;
  onReevaluate?: () => void;
}) {
  if (!finalized) return null;
  const result = evaluation?.result;
  const pending = evaluation?.state === "pending";
  const failed = evaluation?.state === "failed";
  const skipped = evaluation?.state === "skipped";
  const verdict = result?.verdict ? VERDICT[result.verdict] : null;

  return (
    <div className="rounded-2xl border border-white/5 bg-white/[0.02] px-4 py-3 text-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1 space-y-1">
          {result && result.score != null && verdict ? (
            <div className="flex flex-wrap items-center gap-2">
              <span className={`rounded-md px-2 py-0.5 font-semibold tabular-nums ${verdict.tone}`}>
                {verdict.label} · {result.score}/100
              </span>
              {result.incomplete && (
                <span className="rounded-md bg-white/5 px-2 py-0.5 text-xs text-zinc-300">
                  Incomplete
                </span>
              )}
              <span className="text-xs text-zinc-500">{AI_NOTE}</span>
            </div>
          ) : (
            <p className="text-zinc-400">
              {pending
                ? "The AI is evaluating the answers…"
                : skipped
                  ? "Nothing to evaluate: no question got an answer on this call."
                  : failed
                    ? "The AI evaluation didn't finish."
                    : "Not evaluated yet."}
            </p>
          )}
          {result && (
            <div className="space-y-0.5 text-zinc-300">
              {result.strengths && <p>{result.strengths}</p>}
              {result.gaps && <p>{result.gaps}</p>}
              {result.not_covered.length > 0 && (
                <p className="text-zinc-500">
                  Not asked, so not scored: {result.not_covered.join("; ")}
                </p>
              )}
            </div>
          )}
          {result && pending && (
            <p className="animate-pulse text-xs text-zinc-500">Evaluating again…</p>
          )}
          {failed && (
            <p className="text-xs text-amber-300">
              The last evaluation failed: {errorText(evaluation?.error)}.
              {result ? " The result above is from before." : ""}
            </p>
          )}
          {error && <p className="text-xs text-red-300">{error}</p>}
        </div>
        {onReevaluate && (
          <button
            type="button"
            onClick={onReevaluate}
            disabled={busy || pending}
            title="Score the answers again, with the latest approved rubrics"
            className="shrink-0 rounded-lg border border-white/10 px-3 py-1 text-xs text-zinc-200 transition hover:border-white/30 hover:bg-white/5 hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
          >
            {pending || busy ? "Evaluating…" : result ? "Re-evaluate" : "Evaluate"}
          </button>
        )}
      </div>
    </div>
  );
}
