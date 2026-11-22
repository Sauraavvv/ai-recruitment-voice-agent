import { apiFetch, send } from "@/lib/api";
import type { CallAttempt, CallListItem, CallTranscript, PageMeta, StartCallResult } from "@/types";

/** Queue screening calls. Each candidate gets its own result (ok, or why not). `dryRun`: only
 *  check who could be called (the confirmation dialog); nothing is queued. */
export async function startCalls(candidateIds: string[], dryRun = false, overrideLimit = false) {
  const { data } = await send<StartCallResult[]>("POST", "/api/v1/calls/start", {
    candidate_ids: candidateIds,
    dry_run: dryRun,
    // the recruiter confirmed calling beyond the attempt limit (phase-09)
    override_limit: overrideLimit,
  });
  return data;
}

/** Queue one screening call. The result says why not if the candidate can't be called now. */
export async function startCall(candidateId: string) {
  return (await startCalls([candidateId]))[0];
}

export type CallQuery = {
  candidate_id?: string;
  call_status?: string[];
  q?: string;
  created_from?: string;
  created_to?: string;
  purpose?: "screening" | "telephonic";
  client_id?: string;
  page?: number;
  page_size?: number;
};

export async function searchCalls(query: CallQuery) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === "") continue;
    if (Array.isArray(value)) value.forEach((v) => params.append(key, v));
    else params.set(key, String(value));
  }
  const { data, meta } = await apiFetch<CallListItem[]>(`/api/v1/calls?${params}`, {
    cache: "no-store",
  });
  return { items: data, meta: meta as PageMeta };
}

export async function listCalls(candidateId: string) {
  return (await searchCalls({ candidate_id: candidateId, page_size: 50 })).items;
}

export async function getTranscript(attemptId: string) {
  return (
    await apiFetch<CallTranscript>(`/api/v1/calls/${attemptId}/transcript`, { cache: "no-store" })
  ).data;
}

export async function retryCall(attemptId: string, overrideLimit = false) {
  return (
    await send<StartCallResult>("POST", `/api/v1/calls/${attemptId}/retry`, {
      override_limit: overrideLimit,
    })
  ).data;
}

export async function cancelCall(attemptId: string) {
  return (await send<CallAttempt>("POST", `/api/v1/calls/${attemptId}/cancel`)).data;
}

export async function hangupCall(attemptId: string) {
  return (
    await send<{ call_attempt_id: string; ending: boolean }>(
      "POST",
      `/api/v1/calls/${attemptId}/hangup`,
    )
  ).data;
}
