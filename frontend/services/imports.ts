import { apiFetch, send } from "@/lib/api";
import type { ImportPreview } from "@/types";

export async function uploadImport(file: File, jobId: string | null) {
  const form = new FormData();
  form.append("file", file);
  if (jobId) form.append("job_id", jobId);
  return (
    await apiFetch<ImportPreview>("/api/v1/candidates/import", { method: "POST", body: form })
  ).data;
}

export async function getImport(id: string) {
  return (await apiFetch<ImportPreview>(`/api/v1/candidates/import/${id}`, { cache: "no-store" }))
    .data;
}

export async function remapImport(id: string, columnMapping: Record<string, number | null>) {
  return (
    await send<ImportPreview>("PUT", `/api/v1/candidates/import/${id}/mapping`, {
      column_mapping: columnMapping,
    })
  ).data;
}

export async function confirmImport(id: string) {
  return (
    await send<ImportPreview>("POST", `/api/v1/candidates/import/${id}/confirm`, {
      consent_attested: true,
    })
  ).data;
}
