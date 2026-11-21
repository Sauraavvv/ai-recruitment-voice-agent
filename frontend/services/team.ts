import { apiFetch, send } from "@/lib/api";
import type { TeamMember, TeamMemberCreate, TeamMemberUpdate } from "@/types";

// Super admins only: the logins of their company
export async function listTeam() {
  return (await apiFetch<TeamMember[]>("/api/v1/team", { cache: "no-store" })).data;
}

export async function addTeamMember(body: TeamMemberCreate) {
  return (await send<TeamMember>("POST", "/api/v1/team", body)).data;
}

export async function updateTeamMember(id: string, body: TeamMemberUpdate) {
  return (await send<TeamMember>("PATCH", `/api/v1/team/${id}`, body)).data;
}
