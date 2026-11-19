import { apiFetch } from "@/lib/api";
import type { DashboardSummary } from "@/types";

export async function getDashboardSummary() {
  return (await apiFetch<DashboardSummary>("/api/v1/dashboard/summary", { cache: "no-store" }))
    .data;
}
