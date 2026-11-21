import { apiFetch, send } from "@/lib/api";
import type { SignupRequest, User } from "@/types";

export async function login(email: string, password: string) {
  return (await send<User>("POST", "/api/v1/auth/login", { email, password })).data;
}

/** Creates the organization and its super admin, and logs them in. */
export async function signup(body: SignupRequest) {
  return (await send<User>("POST", "/api/v1/auth/signup", body)).data;
}

export async function logout() {
  await send<null>("POST", "/api/v1/auth/logout");
}

export async function me() {
  return (await apiFetch<User>("/api/v1/auth/me", { cache: "no-store" })).data;
}
