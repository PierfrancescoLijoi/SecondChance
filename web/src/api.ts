import { currentToken } from "./auth";
import { config } from "./config";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public retryAfter?: string | null,
  ) {
    super(message);
  }
}

const TENANT_KEY = "secondchance.tenant";
export const selectedTenant = {
  get: () => sessionStorage.getItem(TENANT_KEY),
  set: (tenantId: string) => sessionStorage.setItem(TENANT_KEY, tenantId),
};

function detail(body: unknown): string {
  const value = (body as { detail?: unknown } | null)?.detail;
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.map((e) => (e as { msg?: string }).msg ?? "invalid value").join("; ");
  return "Request failed";
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = await currentToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const tenant = selectedTenant.get();
  if (tenant) headers.set("X-Tenant-ID", tenant);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");

  const response = await fetch(`${config().apiUrl}${path}`, { ...init, headers });
  if (response.status === 204) return undefined as T;
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const message = response.status === 429 ? "Rate limit reached" : detail(body);
    throw new ApiError(response.status, message, response.headers.get("Retry-After"));
  }
  return body as T;
}

export const post = <T>(path: string, data?: unknown) =>
  api<T>(path, { method: "POST", body: data instanceof FormData ? data : JSON.stringify(data ?? {}) });

// ---- API types (mirror the backend OpenAPI schema) ----
export type Membership = {
  membership_id: string;
  tenant_id: string;
  network_name: string | null;
  role: string;
  status: "pending" | "active" | "suspended" | "rejected";
  capabilities: string[];
};
export type Me = { subject: string; memberships: Membership[] };
export type Network = { id: string; name: string; country: string };
export type Offer = {
  id: string;
  category: string;
  quantity: string;
  unit: string;
  date_kind: "use_by" | "best_before";
  expires_on: string;
  storage: string;
  status: string;
  version: number;
};
export type Hit = {
  chunk_id: string;
  document_id: string;
  title: string;
  version: number | null;
  section_path: string[];
  page_start: number;
  page_end: number;
  language: string;
  snippet: string;
  score: number;
};
export type Answer = {
  answer: string | null;
  abstained: boolean;
  reason: string | null;
  mode: "generated" | "extractive" | "none";
  sources: Hit[];
  cited: number[];
  model_id: string | null;
  generated_by: string;
};
export type AssistResult = {
  request_id: string;
  intent: string;
  kind: "answer" | "navigate" | "agent_run" | "clarify" | "unsupported" | "unavailable" | "not_allowed";
  message: string | null;
  target: string | null;
  run_id: string | null;
  answer: Answer | null;
};
export type AgentRun = {
  id: string;
  status: string;
  steps_used: number;
  max_steps: number;
  tokens_used: number;
  max_tokens: number;
  deadline_at: string;
  steps: { seq: number; agent: string; status: string }[];
  findings: string[];
};
export type Space = { id: string; tenant_id: string; name: string; kind: string; visibility: string; allowed_roles: string[] };
export type DocumentRow = { id: string; space_id: string; title: string; language: string; active_version: number | null };
export type Job = { id: string; document_id: string; version: number; status: string; error_category: string | null };
export type PendingRegistration = {
  membership_id: string;
  tenant_id: string;
  type: "ngo" | "donor";
  organization_name: string;
  country: string | null;
  donor_type: string | null;
  created_at: string;
};
