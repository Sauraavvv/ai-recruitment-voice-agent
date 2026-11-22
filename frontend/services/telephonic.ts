import { apiFetch, send } from "@/lib/api";
import type {
  CallAnswers,
  QuestionIn,
  QuestionSet,
  RoundRoster,
  StartCallResult,
  TelephonicState,
} from "@/types";

const base = (requirementId: string) => `/api/v1/requirements/${requirementId}/telephonic`;

export async function getTelephonic(requirementId: string) {
  return (await apiFetch<TelephonicState>(base(requirementId), { cache: "no-store" })).data;
}

export type QuestionLevel = "easy" | "medium" | "hard";

/** Ask the AI for questions from the JD (replaces the draft). Can take up to a minute.
 *  `level`: how hard (easy = an HR screening call). */
export async function generateQuestions(
  requirementId: string,
  count: number,
  focus: string,
  level: QuestionLevel,
) {
  return (
    await send<QuestionSet>("POST", `${base(requirementId)}/generate`, { count, focus, level })
  ).data;
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

/** The requirement's interested candidates and where each stands in the round. */
export async function telephonicRoster(requirementId: string) {
  return (await apiFetch<RoundRoster>(`${base(requirementId)}/candidates`, { cache: "no-store" }))
    .data;
}

export type StartOptions = { dryRun: boolean; overrideLimit: boolean; callAgain: boolean };

/** Queue telephonic round calls (each asks the latest approved questions). No ids: up to 20
 *  interested candidates not called yet. `dryRun`: only check who could be called. */
export async function startTelephonicCalls(
  requirementId: string,
  candidateIds: string[],
  options: StartOptions,
) {
  return (
    await send<StartCallResult[]>("POST", `${base(requirementId)}/calls`, {
      candidate_ids: candidateIds,
      dry_run: options.dryRun,
      override_limit: options.overrideLimit,
      call_again: options.callAgain,
    })
  ).data;
}

/** What a telephonic round call recorded, question by question. */
export async function callAnswers(attemptId: string) {
  return (await apiFetch<CallAnswers>(`/api/v1/calls/${attemptId}/answers`, { cache: "no-store" }))
    .data;
}

/** Ask the AI to evaluate a finished round call again (e.g. after a rubric was sharpened).
 *  Returns the answers with the evaluation pending; the old result stays until the new one. */
export async function reevaluateCall(attemptId: string) {
  return (await send<CallAnswers>("POST", `/api/v1/calls/${attemptId}/evaluate`)).data;
}
