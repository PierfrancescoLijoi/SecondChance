import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { setConfig } from "./config";
import { I18nProvider } from "./i18n";
import { en } from "./locales/en";
import { screensFor } from "./nav";
import { Dashboard } from "./screens/Dashboard";
import { Matching } from "./screens/Matching";
import { Missions } from "./screens/Missions";

type Call = { url: string; init?: RequestInit };

function mockApi(routes: Record<string, unknown>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    const path = url.replace(/^\/api/, "").split("?")[0];
    const key = `${init?.method ?? "GET"} ${path}`;
    const body = key in routes ? routes[key] : path in routes ? routes[path] : [];
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  }));
  return calls;
}

const renderIn = (ui: React.ReactNode) => render(<MemoryRouter><I18nProvider>{ui}</I18nProvider></MemoryRouter>);

const mission = {
  id: "m1", status: "assigned", version: 1, offer_id: "o1", center_id: "c1", center_name: "Centro Demo Aurora",
  center_address: "Via Demo 1", donor_name: "Supermercato Demo", donor_latitude: 45.07, donor_longitude: 7.68,
  category: "dairy", storage: "chilled", date_kind: "use_by", expires_on: "2030-01-02", quantity: "12.000", unit: "kg",
  pickup_from: "2030-01-01T09:00:00Z", pickup_until: "2030-01-01T12:00:00Z", deliver_after: "2030-01-01T10:00:00Z",
  deliver_before: "2030-01-01T14:00:00Z", reassignments: 0, failure_reason: null, receipt: null, receipt_reason: null,
  received_quantity: null, volunteer_name: "Volontario Demo", assigned_to_me: true, created_at: "2030-01-01T08:00:00Z",
  updated_at: "2030-01-01T08:00:00Z", accepted_at: null, picked_up_at: null, delivered_at: null, received_at: null,
};

const proposal = {
  id: "p1", run_id: "r1", offer_id: "o1", center_id: "c1", center_name: "Centro Demo Aurora", donor_name: "Supermercato Demo",
  category: "dairy", storage: "chilled", date_kind: "use_by", expires_on: "2030-01-02", pickup_from: "2030-01-01T09:00:00Z",
  pickup_until: "2030-01-01T12:00:00Z", quantity: "12.000", unit: "kg", load_kg: "12.000", score: 10100, distance_km: "2.30",
  deliver_after: "2030-01-01T10:00:00Z", deliver_before: "2030-01-01T14:00:00Z",
  explanation: {
    satisfied: [
      { code: "category_accepted", value: "dairy" }, { code: "storage", value: "chilled" },
      { code: "slot", from: "2030-01-01T10:00:00Z", until: "2030-01-01T14:00:00Z" },
      { code: "expiry", kind: "use_by", limit: "2030-01-02" },
      { code: "capacity", load_kg: 12, remaining_kg: 300, capacity_kg: 300 }, { code: "distance", km: 2.3 },
    ],
    objective: { base: 10000 }, rule: { country: "IT", version: 1, grace_days: 30 },
  },
  alternatives: [{ center_id: "c2", center_name: "Emporio Solidale Demo", deliver_after: "2030-01-01T10:00:00Z",
                   deliver_before: "2030-01-01T14:00:00Z", distance_km: 4.1, score: 9900 }],
  content_sha256: "a".repeat(64), status: "proposed", generated_by: "secondchance-solver",
};

describe("operations screens", () => {
  beforeEach(() => {
    setConfig({ apiUrl: "/api", authMode: "mock" });
    sessionStorage.setItem("secondchance.token", "token");
  });

  it("gives each operational role its screens, first screen first", () => {
    const coordinator = ["offers.view", "offers.reserve", "assistant", "agents.run", "knowledge.search", "dashboard.view",
                         "matching.run", "missions.manage", "centers.view", "notifications"];
    expect(screensFor(coordinator).map((s) => s.path)).toEqual(
      ["/dashboard", "/missions", "/assistant", "/offers", "/matching", "/centers", "/knowledge", "/notifications"]);
    expect(screensFor(["missions.own", "knowledge.search", "notifications"]).map((s) => s.path))
      .toEqual(["/missions", "/knowledge", "/notifications"]);
    expect(screensFor(["center.manage", "knowledge.search", "notifications"])[0].path).toBe("/center");
  });

  it("approves a proposal with its content hash, the chosen centre and a volunteer", async () => {
    const calls = mockApi({
      "/matching-runs": [], "/proposals": [proposal],
      "/volunteers": [{ membership_id: "v1", display_name: "Volontario Demo", open_missions: 0 }],
      "POST /proposals/p1/decision": { proposal_id: "p1", status: "approved", mission_id: "m1" },
    });
    renderIn(<Matching />);
    expect(await screen.findByText("Optimiser suggestion · needs your approval")).toBeInTheDocument();
    expect(screen.getByText("the centre accepts Dairy")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Destination"), { target: { value: "c2" } });
    fireEvent.click(screen.getByRole("button", { name: "Approve and create mission" }));
    await waitFor(() => expect(calls.some((c) => c.init?.method === "POST")).toBe(true));
    const decision = calls.find((c) => c.init?.method === "POST")!;
    expect(JSON.parse(decision.init!.body as string)).toEqual({
      approve: true, content_sha256: "a".repeat(64), volunteer_membership_id: "v1", center_id: "c2",
    });
    expect(await screen.findByText(/the mission is assigned/)).toBeInTheDocument();
  });

  it("lets a volunteer accept a mission with an idempotency key", async () => {
    const calls = mockApi({
      "/missions": [mission],
      "POST /missions/m1/transition": { id: "m1", status: "accepted", version: 2, replayed: false },
    });
    renderIn(<Missions manage={false} />);
    fireEvent.click(await screen.findByRole("button", { name: "Accept" }));
    await waitFor(() => expect(calls.some((c) => c.init?.method === "POST")).toBe(true));
    const post = calls.find((c) => c.init?.method === "POST")!;
    expect(JSON.parse(post.init!.body as string)).toEqual({ to: "accepted", version: 1 });
    expect(new Headers(post.init!.headers).get("Idempotency-Key")).toMatch(/.{8,}/);
    expect(screen.queryByRole("button", { name: "Reassign" })).not.toBeInTheDocument();
  });

  it("shows aggregated figures only on the dashboard", async () => {
    mockApi({
      "/dashboard": {
        window_days: 30,
        offers: { by_status: { available: { count: 2, kg: 52 } }, published: 2, kg_published: 52, expired: 0 },
        missions: { by_status: { delivered: 1 }, open: 0, failure_rate: 0, on_time_rate: 1, reassignments: 0, median_allocation_hours: 2.5 },
        impact: { kg_received: 12, receipts_confirmed: 1, receipt_exceptions: 0 },
        matching: { runs: 1, proposals: { approved: 1 }, open_proposals: 0, approval_rate: 1, last_run: null },
        centres: [{ id: "c1", name: "Centro Demo Aurora", status: "active", capacity_kg: 300, committed_today_kg: 12, utilisation: 0.04 }],
        categories: [{ category: "dairy", kg_offered: 12, kg_received: 12 }],
        notifications: { email_pending: 0 },
      },
    });
    renderIn(<Dashboard />);
    expect(await screen.findByText("12 kg")).toBeInTheDocument();
    expect(screen.getByText("Centro Demo Aurora")).toBeInTheDocument();
    expect(screen.getAllByText("100%")).toHaveLength(2); // on time and approved; never a per-person figure
  });

  it("translates every code the operations API can return", () => {
    const groups: Record<string, string[]> = {
      missionStatus: ["assigned", "accepted", "picked_up", "delivered", "failed", "cancelled"],
      matchingStatus: ["queued", "running", "succeeded", "infeasible", "failed"],
      centerStatus: ["active", "paused"],
      receipt: ["confirmed", "exception"],
      reason: ["declined", "donor_absent", "vehicle_issue", "quality_rejected", "cold_chain_broken", "center_closed", "safety",
               "other", "no_longer_needed", "offer_withdrawn", "duplicate", "partial", "damaged", "wrong_items",
               "rejected_at_centre", "wrong_centre", "timing", "capacity", "quality_concern"],
      unassigned: ["storage_unavailable", "category_not_accepted", "exceeds_daily_capacity", "no_acceptance_slot", "past_use_by",
                   "past_best_before_grace", "capacity_full", "capacity_used_by_higher_priority", "pickup_window_passed",
                   "no_active_centre"],
      notification: ["mission_assigned", "mission_cancelled", "mission_withdrawn", "mission_failed", "delivery_incoming",
                     "receipt_exception", "proposals_ready", "matching_infeasible", "matching_failed"],
      role: ["donor", "coordinator", "volunteer", "center_staff", "org_admin", "platform_admin"],
    };
    const missing = Object.entries(groups).flatMap(([group, values]) =>
      values.map((v) => `${group}.${v}`).filter((key) => !(key in en)));
    expect(missing).toEqual([]);
  });
});
