import { apiFetch, send } from "@/lib/api";
import type { Client, ClientCreate, ClientListItem, ClientStatus, ClientUpdate } from "@/types";

// An account sees only the clients it added
export async function listClients(params: { q?: string; status?: ClientStatus | "" } = {}) {
  const query = new URLSearchParams();
  if (params.q) query.set("q", params.q);
  if (params.status) query.set("status", params.status);
  const suffix = query.size ? `?${query}` : "";
  return (await apiFetch<ClientListItem[]>(`/api/v1/clients${suffix}`, { cache: "no-store" })).data;
}

export async function getClient(id: string) {
  return (await apiFetch<Client>(`/api/v1/clients/${id}`, { cache: "no-store" })).data;
}

export async function createClient(body: ClientCreate) {
  return (await send<Client>("POST", "/api/v1/clients", body)).data;
}

export async function updateClient(id: string, body: ClientUpdate) {
  return (await send<Client>("PATCH", `/api/v1/clients/${id}`, body)).data;
}
