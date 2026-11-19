import { apiFetch, send } from "@/lib/api";
import type { CallAttempt, StartCallResult } from "@/types";

/** Queue a screening call. The result says why not if the candidate can't be called now. */
export async function startCall(candidateId: string) {
  const { data } = await send<StartCallResult[]>("POST", "/api/v1/calls/start", {
    candidate_ids: [candidateId],
  });
  return data[0];
}

export async function listCalls(candidateId: string) {
  const params = new URLSearchParams({ candidate_id: candidateId, page_size: "10" });
  return (await apiFetch<CallAttempt[]>(`/api/v1/calls?${params}`, { cache: "no-store" })).data;
}
