import { apiFetch } from "@/lib/api";
import type {
  ActivityItem,
  AttentionItem,
  DashboardStats,
  DashboardSummary,
  QuickStart,
} from "@/types";

const get = async <T>(path: string) =>
  (await apiFetch<T>(`/api/v1/dashboard/${path}`, { cache: "no-store" })).data;

export const getDashboardSummary = () => get<DashboardSummary>("summary");
export const getStats = (range: "today" | "7d" | "all") =>
  get<DashboardStats>(`stats?range=${range}`);
export const getActivity = () => get<ActivityItem[]>("activity");
export const getAttention = () => get<AttentionItem[]>("attention");
export const getQuickStart = () => get<QuickStart>("quick-start");
