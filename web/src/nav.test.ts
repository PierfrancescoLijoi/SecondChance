import { describe, expect, it } from "vitest";
import { screensFor } from "./nav";
import { validateOffer } from "./screens/NewOffer";

describe("screensFor", () => {
  it("shows a donor only donor screens", () => {
    const paths = screensFor(["offers.own", "offers.create", "knowledge.search", "assistant"]).map((s) => s.path);
    expect(paths).toEqual(["/assistant", "/offers", "/offers/new", "/knowledge"]);
  });

  it("shows nothing for a pending membership (no capabilities)", () => {
    expect(screensFor([])).toEqual([]);
  });

  it("gives admins the review queue and document management", () => {
    const paths = screensFor(["registrations.review", "documents.manage"]).map((s) => s.path);
    expect(paths).toEqual(["/documents", "/registrations"]);
  });
});

describe("validateOffer", () => {
  const base = {
    quantity: "10", date_kind: "best_before", expires_on: "2030-01-01",
    pickup_from: "2030-01-01T09:00", pickup_until: "2030-01-01T12:00",
  };

  it("accepts a coherent offer", () => {
    expect(validateOffer(base)).toBeNull();
  });

  it.each([
    [{ quantity: "0" }, "offerError.quantity"],
    [{ pickup_until: "2030-01-01T08:00" }, "offerError.window"],
    [{ pickup_until: "2030-02-01T08:00" }, "offerError.windowTooLong"],
    [{ date_kind: "use_by", expires_on: "2020-01-01" }, "offerError.useByPassed"],
  ])("rejects %o before sending", (override, key) => {
    expect(validateOffer({ ...base, ...override }, new Date("2026-10-17"))).toBe(key);
  });
});
