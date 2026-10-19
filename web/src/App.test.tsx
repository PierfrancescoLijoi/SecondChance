import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { setConfig } from "./config";

function mockMe(memberships: unknown[]) {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    const body = url.endsWith("/me") ? { subject: "s", memberships } : [];
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  }));
}

function renderApp() {
  return render(<MemoryRouter initialEntries={["/"]}><App /></MemoryRouter>);
}

const active = (role: string, capabilities: string[]) => ({
  membership_id: "m1", tenant_id: "t1", network_name: "Test network", role, status: "active", capabilities,
});

describe("App routing by membership", () => {
  beforeEach(() => {
    setConfig({ apiUrl: "/api", authMode: "mock" });
    sessionStorage.setItem("secondchance.token", "token");
  });

  it("asks a new user to register as donor or NGO", async () => {
    mockMe([]);
    renderApp();
    expect(await screen.findByRole("heading", { name: "How do you want to use SecondChance?" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /I am a donor/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /I am an organisation/ })).toBeInTheDocument();
  });

  it("keeps a pending user on the waiting screen", async () => {
    mockMe([{ ...active("donor", []), status: "pending" }]);
    renderApp();
    expect(await screen.findByRole("heading", { name: /waiting to be checked/ })).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });

  it("gives a donor donor screens only", async () => {
    mockMe([active("donor", ["offers.own", "offers.create", "knowledge.search", "assistant"])]);
    renderApp();
    const nav = await screen.findByRole("navigation", { name: "Available features" });
    expect(nav).toHaveTextContent("New offer");
    expect(nav).not.toHaveTextContent("Documents");
    expect(nav).not.toHaveTextContent("Membership requests");
  });

  it("shows the landing page in English without a session", async () => {
    sessionStorage.clear();
    mockMe([]);
    renderApp();
    expect(await screen.findByRole("heading", { level: 1, name: /Surplus food reaches/ })).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("en");
  });

  it.each([
    ["da", /Overskudsmad når frem/],
    ["pl", /Nadwyżki żywności trafiają/],
    ["it", /Il cibo in eccesso arriva/],
  ])("switches the interface to %s and remembers it", async (lang, heading) => {
    sessionStorage.clear();
    mockMe([]);
    renderApp();
    fireEvent.change(await screen.findByRole("combobox", { name: "Language" }), { target: { value: lang } });
    expect(await screen.findByRole("heading", { level: 1, name: heading })).toBeInTheDocument();
    expect(document.documentElement.lang).toBe(lang);
    expect(localStorage.getItem("secondchance.lang")).toBe(lang);
  });
});
