"use client";

import Link from "next/link";
import { useState } from "react";

import { useLoad } from "@/lib/use-load";
import { questionCount, repeatsDefault } from "@/lib/must-haves";
import { screeningQuestions } from "@/services/requirements";
import type { ScreeningCallQuestion } from "@/types";

/** What the screening call asks, on the requirement page: a one-line count that opens the full
 * list in the order the agent asks it (defaults, then must-haves), with must-haves that only
 * repeat a default question flagged. */
export function CallQuestions({
  requirementId,
  version,
  editHref,
}: {
  requirementId: string;
  version: string; // reloads when the requirement changes (its must-haves)
  editHref: string;
}) {
  const [open, setOpen] = useState(false);
  const { data } = useLoad(`screening-questions:${requirementId}:${version}`, () =>
    screeningQuestions(requirementId),
  );
  if (!data) return null;
  return (
    <CallQuestionsView
      questions={data}
      open={open}
      onToggle={() => setOpen(!open)}
      editHref={editHref}
    />
  );
}

export function CallQuestionsView({
  questions,
  open,
  onToggle,
  editHref,
}: {
  questions: ScreeningCallQuestion[];
  open: boolean;
  onToggle: () => void;
  editHref: string;
}) {
  const defaults = questions.filter((q) => q.source === "default");
  const musts = questions.filter((q) => q.source === "must_have");
  const repeats = new Map(
    musts.map((q) => [q.key, repeatsDefault(q.must_have ?? q.prompt, defaults)] as const),
  );
  const flagged = [...repeats.values()].filter(Boolean).length;

  return (
    <div className="mt-4 rounded-2xl bg-[#202226]">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3 text-left text-sm"
      >
        <span className="text-zinc-300">
          The call asks <span className="font-medium text-white">{questions.length} questions</span>
        </span>
        <span className="text-zinc-500">{questionCount(defaults.length, musts.length)}</span>
        {flagged > 0 && (
          <span className="rounded-md bg-amber-400/10 px-2 py-0.5 text-xs text-amber-300">
            {flagged} repeat{flagged === 1 ? "s" : ""} a default question
          </span>
        )}
        <span className="ml-auto text-xs font-medium text-zinc-400">
          {open ? "Hide" : "See questions"}
        </span>
      </button>

      {open && (
        <div className="border-t border-white/5 px-4 pb-3">
          <ol className="divide-y divide-white/5">
            {questions.map((q) => {
              const repeat = repeats.get(q.key);
              return (
                <li key={q.key} className="flex items-start gap-3 py-2.5 text-sm">
                  <span className="w-6 shrink-0 pt-px text-right text-zinc-500 tabular-nums">
                    {q.number}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="text-zinc-200">
                      {q.source === "must_have" ? (q.must_have ?? q.prompt) : q.prompt}
                    </span>
                    {q.source === "must_have" && (
                      <span className="block text-xs text-zinc-500">
                        Asked as a yes / no question
                      </span>
                    )}
                    {repeat && (
                      <span className="mt-1 block text-xs text-amber-300">
                        Looks like question {repeat.number} ({repeat.prompt.replace(/\?$/, "")})
                      </span>
                    )}
                  </span>
                  <span
                    className={`shrink-0 rounded-md px-2 py-0.5 text-xs ${
                      q.source === "must_have" ? "bg-white/10 text-zinc-200" : "text-zinc-500"
                    }`}
                  >
                    {q.source === "must_have" ? "must-have" : "default"}
                  </span>
                </li>
              );
            })}
          </ol>
          <div className="flex flex-wrap justify-end gap-x-4 gap-y-1 pt-2 text-xs font-medium">
            <Link href="/default-questions" className="text-[#60a5fa] hover:underline">
              Edit default questions
            </Link>
            <Link href={editHref} className="text-[#60a5fa] hover:underline">
              Edit must-haves
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}
