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
  organization_id?: string | null;
  center_id?: string | null;
  display_name?: string | null;
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
  type: "ngo" | "donor" | "member";
  organization_name: string;
  role?: string | null;
  display_name?: string | null;
  country: string | null;
  donor_type: string | null;
  created_at: string;
};

// ---- Operations: centres, matching, missions, notifications, dashboard ----
export type Slot = { weekday: number; opens: string; closes: string };
export type Center = {
  id: string;
  name: string;
  status: "active" | "paused";
  address: string | null;
  latitude: number | null;
  longitude: number | null;
  timezone: string;
  accepted_categories: string[];
  storage_capabilities: string[];
  daily_capacity_kg: string;
  committed_today_kg: string;
  version: number;
  updated_at: string;
  slots: Slot[];
};
export type Versioned = { id: string; version: number };
export type MatchingRun = {
  id: string;
  status: "queued" | "running" | "succeeded" | "infeasible" | "failed";
  solver_status: string | null;
  input_sha256: string | null;
  time_limit_ms: number;
  stats: {
    offers?: number;
    centres?: number;
    proposals?: number;
    wall_ms?: number | null;
    unassigned?: { offer_id: string; category: string; quantity: number; unit: string; reasons: string[] }[];
  };
  error_category: string | null;
  created_at: string;
  finished_at: string | null;
};
export type Satisfied =
  | { code: "category_accepted" | "storage"; value: string }
  | { code: "slot"; from: string; until: string }
  | { code: "expiry"; kind: string; limit: string }
  | { code: "capacity"; load_kg: number; remaining_kg: number; capacity_kg: number }
  | { code: "distance"; km: number | null };
export type Alternative = {
  center_id: string;
  center_name: string;
  deliver_after: string;
  deliver_before: string;
  distance_km: number | null;
  score: number;
};
export type Proposal = {
  id: string;
  run_id: string;
  offer_id: string;
  center_id: string;
  center_name: string;
  donor_name: string;
  category: string;
  storage: string;
  date_kind: string;
  expires_on: string;
  pickup_from: string;
  pickup_until: string;
  quantity: string;
  unit: string;
  load_kg: string;
  score: number;
  distance_km: string | null;
  deliver_after: string;
  deliver_before: string;
  explanation: { satisfied: Satisfied[]; objective: Record<string, number>; rule: { country: string; version: number | null; grace_days: number } };
  alternatives: Alternative[];
  content_sha256: string;
  status: string;
  generated_by: string;
};
export type Volunteer = { membership_id: string; display_name: string; open_missions: number };
export type Mission = {
  id: string;
  status: "assigned" | "accepted" | "picked_up" | "delivered" | "failed" | "cancelled";
  version: number;
  offer_id: string;
  center_id: string;
  center_name: string;
  center_address: string | null;
  donor_name: string;
  donor_latitude: number | null;
  donor_longitude: number | null;
  category: string;
  storage: string;
  date_kind: string;
  expires_on: string;
  quantity: string;
  unit: string;
  pickup_from: string;
  pickup_until: string;
  deliver_after: string;
  deliver_before: string;
  reassignments: number;
  failure_reason: string | null;
  receipt: "confirmed" | "exception" | null;
  receipt_reason: string | null;
  received_quantity: string | null;
  volunteer_name: string | null;
  assigned_to_me: boolean;
  created_at: string;
  updated_at: string;
  accepted_at: string | null;
  picked_up_at: string | null;
  delivered_at: string | null;
  received_at: string | null;
};
export type MissionChanged = { id: string; status: string; version: number; replayed: boolean };
export type AppNotification = {
  id: string;
  kind: string;
  object_type: "mission" | "matching_run" | "allocation_proposal";
  object_id: string;
  created_at: string;
  read_at: string | null;
};
export type Inbox = { unread: number; items: AppNotification[] };
export type Dashboard = {
  window_days: number;
  offers: { by_status: Record<string, { count: number; kg: number }>; published: number; kg_published: number; expired: number };
  missions: {
    by_status: Record<string, number>;
    open: number;
    failure_rate: number | null;
    on_time_rate: number | null;
    reassignments: number;
    median_allocation_hours: number | null;
  };
  impact: { kg_received: number; receipts_confirmed: number; receipt_exceptions: number };
  matching: {
    runs: number;
    proposals: Record<string, number>;
    open_proposals: number;
    approval_rate: number | null;
    last_run: { id: string; status: string; created_at: string; finished_at: string | null; proposals: number | null; unassigned: number } | null;
  };
  centres: { id: string; name: string; status: string; capacity_kg: number; committed_today_kg: number; utilisation: number | null }[];
  categories: { category: string; kg_offered: number; kg_received: number }[];
  notifications: { email_pending: number };
};

/** A fresh key per user action: a retried request (flaky network, offline queue) is applied once (FR-027). */
export function idempotencyKey(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
