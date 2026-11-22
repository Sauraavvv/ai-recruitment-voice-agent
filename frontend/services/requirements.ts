import { apiFetch, send } from "@/lib/api";
import type {
  JobListItem,
  Requirement,
  RequirementCreate,
  RequirementListItem,
  RequirementUpdate,
  ScreeningCallQuestion,
} from "@/types";

export async function listRequirements(clientId: string) {
  return (
    await apiFetch<RequirementListItem[]>(`/api/v1/clients/${clientId}/requirements`, {
      cache: "no-store",
    })
  ).data;
}

export async function getRequirement(id: string) {
  return (await apiFetch<Requirement>(`/api/v1/requirements/${id}`, { cache: "no-store" })).data;
}

export async function createRequirement(clientId: string, body: RequirementCreate) {
  return (await send<Requirement>("POST", `/api/v1/clients/${clientId}/requirements`, body)).data;
}

export async function updateRequirement(id: string, body: RequirementUpdate) {
  return (await send<Requirement>("PATCH", `/api/v1/requirements/${id}`, body)).data;
}

/** Every requirement (job) across the clients this account sees, with its client. */
export async function listJobs() {
  return (await apiFetch<JobListItem[]>("/api/v1/requirements", { cache: "no-store" })).data;
}

/** What the requirement's screening call asks, in order: the defaults, then its must-haves. */
export async function screeningQuestions(id: string) {
  return (
    await apiFetch<ScreeningCallQuestion[]>(`/api/v1/requirements/${id}/screening-questions`, {
      cache: "no-store",
    })
  ).data;
}
