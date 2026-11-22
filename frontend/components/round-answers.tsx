"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { EvaluationPanel, QuestionScoreView } from "@/components/round-evaluation";
import { ErrorState } from "@/components/states";
import { usePolling } from "@/hooks/use-polling";
import { ApiError } from "@/lib/api";
import { useLoad } from "@/lib/use-load";
import { callAnswers, reevaluateCall } from "@/services/telephonic";
import type { CallAnswers, RoundAnswer } from "@/types";

export const ANSWER_STATUS: Record<RoundAnswer["status"], { label: string; tone: string }> = {
  answered: { label: "Answered", tone: "bg-green-500/10 text-green-300" },
  partial: { label: "Partly", tone: "bg-amber-400/10 text-amber-300" },
  dont_know: { label: "Didn't know", tone: "bg-white/5 text-zinc-300" },
  declined: { label: "Refused", tone: "bg-red-500/10 text-red-300" },
  not_asked: { label: "Not asked", tone: "bg-white/5 text-zinc-500" },
};

/** A telephonic round call's answers and their AI evaluation, loaded by call id. Polls while
 * the evaluation runs. `onEvaluated` lets a list refresh its badges. */
export function RoundAnswers({
  attemptId,
  transcriptHref,
  onEvaluated,
}: {
  attemptId: string;
  transcriptHref?: string;
  onEvaluated?: () => void;
}) {
  const { data, error, reload } = useLoad(`round-answers:${attemptId}`, () =>
    callAnswers(attemptId),
  );
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const pending = data?.evaluation?.state === "pending";
  usePolling(reload, true, pending);
  // The evaluation just finished: the list around this view refreshes its badge
  const wasPending = useRef(false);
  useEffect(() => {
    if (wasPending.current && !pending) onEvaluated?.();
    wasPending.current = pending;
  }, [pending, onEvaluated]);

  async function reevaluate() {
    setBusy(true);
    setFailure(null);
    try {
      await reevaluateCall(attemptId);
      reload();
      onEvaluated?.();
    } catch (e) {
      setFailure(e instanceof ApiError ? e.message : "Couldn't ask for a new evaluation.");
    } finally {
      setBusy(false);
    }
  }

  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data)
    return <div className="h-24 animate-pulse rounded-2xl bg-white/[0.03]" aria-label="Loading" />;
  return (
    <RoundAnswersView
      data={data}
      transcriptHref={transcriptHref}
      busy={busy}
      error={failure}
      onReevaluate={reevaluate}
    />
  );
}

/** The candidate's own words, question by question, in the order asked, with the AI's score
 * and reason for each (an AI recommendation: the recruiter decides). */
export function RoundAnswersView({
  data,
  transcriptHref,
  busy = false,
  error = null,
  onReevaluate,
}: {
  data: CallAnswers;
  transcriptHref?: string;
  busy?: boolean;
  error?: string | null;
  onReevaluate?: () => void;
}) {
  const scores = new Map(
    (data.evaluation?.result?.questions ?? []).map((q) => [q.question_id, q] as const),
  );
  return (
    <div className="space-y-3">
      {data.summary && <p className="text-sm text-zinc-300">{data.summary}</p>}
      {data.answers.length > 0 && (
        <EvaluationPanel
          evaluation={data.evaluation}
          finalized={data.finalized}
          busy={busy}
          error={error}
          onReevaluate={onReevaluate}
        />
      )}
      {data.answers.length === 0 ? (
        <p className="text-sm text-zinc-500">
          {data.finalized ? "No answers were recorded on this call." : "Answers are being saved…"}
        </p>
      ) : (
        <ol className="divide-y divide-white/5 rounded-2xl bg-[#202226] px-4">
          {data.answers.map((a, i) => {
            const status = ANSWER_STATUS[a.status] ?? ANSWER_STATUS.not_asked;
            const score = scores.get(a.question_id);
            return (
              <li key={a.question_id} className="flex gap-3 py-3 text-sm">
                <span className="w-5 shrink-0 text-right text-zinc-500 tabular-nums">{i + 1}</span>
                <div className="min-w-0 flex-1 space-y-1">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <span className="min-w-0 flex-1 text-zinc-400">{a.question}</span>
                    <span className={`shrink-0 rounded-md px-2 py-0.5 text-xs ${status.tone}`}>
                      {status.label}
                    </span>
                  </div>
                  {a.follow_up && (
                    <p className="text-xs text-zinc-500">Follow-up asked: {a.follow_up}</p>
                  )}
                  <p className={a.answer ? "text-zinc-100" : "text-zinc-600"}>
                    {a.answer ? `“${a.answer}”` : "—"}
                  </p>
                  {score && score.rule !== "not_asked" && <QuestionScoreView score={score} />}
                  {(a.checked === false || a.from_earlier_call) && (
                    <p className="text-xs text-zinc-500">
                      {[
                        a.from_earlier_call ? "From an earlier call" : "",
                        a.checked === false ? "Kept as said (the AI was busy on this turn)" : "",
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </p>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      )}
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-zinc-500">
        <span>
          {data.version != null && `Questions v${data.version}`}
          {data.candidate_questions.length > 0 &&
            ` · They asked about: ${data.candidate_questions.join("; ")}`}
        </span>
        {transcriptHref && (
          <Link href={transcriptHref} className="font-medium text-[#60a5fa] hover:underline">
            Transcript
          </Link>
        )}
      </div>
    </div>
  );
}
