import type { CaseSummary, CaseView, Metrics, ReviewInput, Sample } from "./types";

/** The browser only ever talks to this app's own /api routes; the server adds the API key. */
export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = body && typeof body.detail === "string" ? body.detail : body?.detail?.[0]?.msg;
    throw new ApiError(res.status, detail ?? `Request failed (${res.status})`);
  }
  return body as T;
}

export const api = {
  listCases: (status?: string) =>
    request<{ cases: CaseSummary[] }>(`cases${status ? `?status=${encodeURIComponent(status)}` : ""}`),
  getCase: (id: string) => request<CaseView>(`cases/${encodeURIComponent(id)}`),
  createCase: (input: { text: string; source_name?: string; request_date?: string }) =>
    request<{ case_id: string }>("cases", { method: "POST", body: JSON.stringify(input) }),
  review: (id: string, input: ReviewInput) =>
    request<CaseView>(`cases/${encodeURIComponent(id)}/review`, { method: "POST", body: JSON.stringify(input) }),
  samples: () => request<{ samples: Sample[] }>("samples"),
  metrics: (days: number) => request<Metrics>(`metrics?days=${days}`),
};
