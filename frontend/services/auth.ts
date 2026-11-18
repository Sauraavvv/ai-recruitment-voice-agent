import { apiFetch, send } from "@/lib/api";
import type { User } from "@/types";

export async function login(email: string, password: string) {
  return (await send<User>("POST", "/api/v1/auth/login", { email, password })).data;
}

export async function logout() {
  await send<null>("POST", "/api/v1/auth/logout");
}

export async function me() {
  return (await apiFetch<User>("/api/v1/auth/me", { cache: "no-store" })).data;
}
