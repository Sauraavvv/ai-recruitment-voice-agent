import { apiFetch, send } from "@/lib/api";
import type { ImportPreview } from "@/types";

/** For a requirement (`target.requirementId`) or a job (`target.jobId`, else the active job). */
export async function uploadImport(
  file: File,
  target: { jobId?: string | null; requirementId?: string | null },
) {
  const form = new FormData();
  form.append("file", file);
  if (target.requirementId) form.append("requirement_id", target.requirementId);
  else if (target.jobId) form.append("job_id", target.jobId);
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
