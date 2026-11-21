import { apiFetch, send } from "@/lib/api";
import type {
  Candidate,
  CandidateCreate,
  CandidateListItem,
  CandidateOverview,
  CandidateUpdate,
  PageMeta,
} from "@/types";

export type CandidateQuery = {
  q?: string;
  screening_status?: string;
  call_status?: string;
  interested?: string;
  job_id?: string;
  requirement_id?: string;
  sort?: string;
  page?: number;
  page_size?: number;
};

export async function listCandidates(query: CandidateQuery) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  const { data, meta } = await apiFetch<CandidateListItem[]>(`/api/v1/candidates?${params}`, {
    cache: "no-store",
  });
  return { items: data, meta: meta as PageMeta };
}

export async function getCandidate(id: string) {
  return (await apiFetch<Candidate>(`/api/v1/candidates/${id}`, { cache: "no-store" })).data;
}

export async function createCandidate(body: CandidateCreate) {
  return (await send<Candidate>("POST", "/api/v1/candidates", body)).data;
}

export async function updateCandidate(id: string, body: CandidateUpdate) {
  return (await send<Candidate>("PATCH", `/api/v1/candidates/${id}`, body)).data;
}

export async function deleteCandidate(id: string) {
  await send<null>("DELETE", `/api/v1/candidates/${id}`);
}

/** Eligibility, the summary, the sheet sync status and open conflicts. */
export async function getOverview(id: string) {
  return (
    await apiFetch<CandidateOverview>(`/api/v1/candidates/${id}/overview`, { cache: "no-store" })
  ).data;
}

export async function resolveConflict(id: string, field: string, choice: "keep" | "use") {
  return (
    await send<Candidate>("POST", `/api/v1/candidates/${id}/conflicts/${field}/resolve`, {
      choice,
    })
  ).data;
}
