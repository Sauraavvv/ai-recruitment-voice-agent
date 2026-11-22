import { apiFetch, send } from "@/lib/api";
import type { QuestionIn, QuestionSet, TelephonicState } from "@/types";

const base = (requirementId: string) => `/api/v1/requirements/${requirementId}/telephonic`;

export async function getTelephonic(requirementId: string) {
  return (await apiFetch<TelephonicState>(base(requirementId), { cache: "no-store" })).data;
}

/** Ask the AI for questions from the JD (replaces the draft). Can take up to a minute. */
export async function generateQuestions(requirementId: string, count: number, focus: string) {
  return (await send<QuestionSet>("POST", `${base(requirementId)}/generate`, { count, focus }))
    .data;
}

export async function saveDraft(requirementId: string, questions: QuestionIn[]) {
  return (await send<QuestionSet>("PUT", `${base(requirementId)}/draft`, { questions })).data;
}

export async function discardDraft(requirementId: string) {
  await send<null>("DELETE", `${base(requirementId)}/draft`);
}

export async function approveQuestions(requirementId: string) {
  return (await send<QuestionSet>("POST", `${base(requirementId)}/approve`)).data;
}
