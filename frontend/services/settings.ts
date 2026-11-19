import { apiFetch, send } from "@/lib/api";
import type {
  GeneralUpdate,
  SettingsPage,
  SheetAccessCheck,
  SheetsStatus,
  StatusOut,
} from "@/types";

export async function getSettings() {
  return (await apiFetch<SettingsPage>("/api/v1/settings", { cache: "no-store" })).data;
}

export async function updateSettings(body: GeneralUpdate) {
  return (await send<SettingsPage>("PATCH", "/api/v1/settings", body)).data;
}

export async function getProviderStatus(refresh = false) {
  return (
    await apiFetch<StatusOut>(`/api/v1/settings/status${refresh ? "?refresh=true" : ""}`, {
      cache: "no-store",
    })
  ).data;
}

const SHEETS = "/api/v1/integrations/google-sheets";

export async function getSheetsStatus(refresh = false) {
  return (
    await apiFetch<SheetsStatus>(`${SHEETS}/status${refresh ? "?refresh=true" : ""}`, {
      cache: "no-store",
    })
  ).data;
}

export async function syncCandidate(candidateId: string) {
  return (await send<{ queued: boolean }>("POST", `${SHEETS}/sync/${candidateId}`)).data;
}

export async function syncAll() {
  return (await send<{ queued_candidates: number }>("POST", `${SHEETS}/backfill`)).data;
}

/** Admin: can the service account use this sheet? */
export async function checkSheet(link: string, tab?: string) {
  return (await send<SheetAccessCheck>("POST", `${SHEETS}/check`, { link, tab: tab || null })).data;
}

/** Admin: copy candidates to this sheet from now on (checked again, then everyone re-synced). */
export async function changeSheet(link: string, tab?: string) {
  return (await send<SheetAccessCheck>("PUT", `${SHEETS}/sheet`, { link, tab: tab || null })).data;
}
