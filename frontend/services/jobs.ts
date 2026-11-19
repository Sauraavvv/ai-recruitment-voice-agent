import { apiFetch, send } from "@/lib/api";
import type { DefaultQuestionsResult, Job, JobCreate, JobUpdate, ScreeningQuestion } from "@/types";

const DEFAULTS_PATH = "/api/v1/jobs/default-screening-questions";

export async function listJobs() {
  return (await apiFetch<Job[]>("/api/v1/jobs", { cache: "no-store" })).data;
}

export async function defaultQuestions() {
  return (
    await apiFetch<ScreeningQuestion[]>(DEFAULTS_PATH, {
      cache: "no-store",
    })
  ).data;
}

/** Replace the default questions; jobs still using the defaults follow along. */
export async function updateDefaultQuestions(questions: ScreeningQuestion[]) {
  return (await send<DefaultQuestionsResult>("PUT", DEFAULTS_PATH, { questions })).data;
}

/** Restore the ten original default questions. */
export async function resetDefaultQuestions() {
  return (await send<DefaultQuestionsResult>("DELETE", DEFAULTS_PATH)).data;
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
