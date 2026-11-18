import { apiFetch, send } from "@/lib/api";
import type { Job, JobCreate, JobUpdate, ScreeningQuestion } from "@/types";

export async function listJobs() {
  return (await apiFetch<Job[]>("/api/v1/jobs", { cache: "no-store" })).data;
}

export async function defaultQuestions() {
  return (await apiFetch<ScreeningQuestion[]>("/api/v1/jobs/default-screening-questions")).data;
}

export async function createJob(body: JobCreate) {
  return (await send<Job>("POST", "/api/v1/jobs", body)).data;
}

export async function updateJob(id: string, body: JobUpdate) {
  return (await send<Job>("PATCH", `/api/v1/jobs/${id}`, body)).data;
}

export async function activateJob(id: string) {
  return (await send<Job>("POST", `/api/v1/jobs/${id}/activate`)).data;
}
