import { apiFetch, send } from "@/lib/api";
import type { GeneralUpdate, SettingsPage, StatusOut } from "@/types";

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
