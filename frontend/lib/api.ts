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
  throw new ApiError(
    response.status,
    error?.code ?? "http_error",
    error?.message ?? `Request failed (${response.status})`,
    error?.details,
    error?.request_id,
  );
}
