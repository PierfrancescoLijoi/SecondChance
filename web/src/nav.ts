import type { MessageKey } from "./locales/en";

// Screens are offered by capability, never by role name, so the backend stays the single
// source of truth (GET /me). The API enforces roles on every endpoint anyway (ADR-017).
export type Screen = { path: string; label: MessageKey; anyOf: string[]; soon?: boolean };

export const SCREENS: Screen[] = [
  { path: "/dashboard", label: "nav.dashboard", anyOf: ["dashboard.view"] },
  { path: "/missions", label: "nav.missions", anyOf: ["missions.own", "missions.manage"] },
  { path: "/center", label: "nav.center", anyOf: ["center.manage"] },
  { path: "/assistant", label: "nav.assistant", anyOf: ["assistant"] },
  { path: "/offers", label: "nav.offers", anyOf: ["offers.view", "offers.own"] },
  { path: "/offers/new", label: "nav.newOffer", anyOf: ["offers.create"] },
  { path: "/matching", label: "nav.matching", anyOf: ["matching.run"] },
  { path: "/centers", label: "nav.centers", anyOf: ["centers.manage", "centers.view"] },
  { path: "/knowledge", label: "nav.knowledge", anyOf: ["knowledge.search"] },
  { path: "/documents", label: "nav.documents", anyOf: ["documents.manage"] },
  { path: "/registrations", label: "nav.registrations", anyOf: ["registrations.review", "networks.review"] },
  { path: "/notifications", label: "nav.notifications", anyOf: ["notifications"] },
];

export function screensFor(capabilities: string[]): Screen[] {
  return SCREENS.filter((screen) => screen.anyOf.some((c) => capabilities.includes(c)));
}
