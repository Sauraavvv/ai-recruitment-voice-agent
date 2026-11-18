// Small fetch wrapper for the backend's response envelope.
// Success: { data, meta? }   Error: { error: { code, message, details, request_id } }

export type ApiMeta = Record<string, unknown>;

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details?: unknown,
    readonly requestId?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type ErrorEnvelope = {
  error?: { code?: string; message?: string; details?: unknown; request_id?: string };
};

const LOGIN_PATH = "/login";

function redirectToLogin() {
  if (typeof window === "undefined" || window.location.pathname === LOGIN_PATH) return;
  const next = window.location.pathname + window.location.search;
  // A full navigation on purpose: this module has no router, and it drops any stale page state.
  // eslint-disable-next-line @next/next/no-location-assign-relative-destination
  window.location.assign(`${LOGIN_PATH}?next=${encodeURIComponent(next)}`);
}

export async function apiFetch<T>(
  path: string,
  init?: RequestInit & { acceptStatuses?: number[] },
): Promise<{ data: T; meta?: ApiMeta; status: number }> {
  const { acceptStatuses = [], ...requestInit } = init ?? {};
  let response: Response;
  try {
    response = await fetch(path, {
      ...requestInit,
      headers: { Accept: "application/json", ...requestInit.headers },
      credentials: "same-origin",
    });
  } catch {
    throw new ApiError(0, "network_error", "Can't reach the server");
  }

  const body: unknown = await response.json().catch(() => null);

  if (response.ok || acceptStatuses.includes(response.status)) {
    const envelope = body as { data?: T; meta?: ApiMeta } | null;
    if (envelope && "data" in envelope) {
      return { data: envelope.data as T, meta: envelope.meta, status: response.status };
    }
  }

  const error = (body as ErrorEnvelope | null)?.error;
  if (response.status === 401 && error?.code === "not_authenticated") {
    redirectToLogin();
  }
  throw new ApiError(
    response.status,
    error?.code ?? "http_error",
    error?.message ?? `Request failed (${response.status})`,
    error?.details,
    error?.request_id,
  );
}

/** JSON request helper: `send("PATCH", url, body)`. */
export function send<T>(method: "POST" | "PUT" | "PATCH" | "DELETE", path: string, body?: unknown) {
  return apiFetch<T>(path, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

/** Human-readable message for an error, including field-level validation details. */
export function errorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return "Something went wrong";
  if (error.code === "validation_error" && Array.isArray(error.details)) {
    const parts = (error.details as { loc?: unknown[]; msg?: string }[]).map((d) => {
      const field = d.loc?.filter((p) => p !== "body").join(".");
      return field ? `${field}: ${d.msg}` : d.msg;
    });
    return parts.join("; ") || error.message;
  }
  return error.message;
}
