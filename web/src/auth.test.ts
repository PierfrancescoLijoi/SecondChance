import { afterEach, describe, expect, it, vi } from "vitest";

const removeUser = vi.fn(async () => undefined);
const signoutRedirect = vi.fn(async () => undefined);
vi.mock("oidc-client-ts", () => ({
  UserManager: class {
    removeUser = removeUser;
    signoutRedirect = signoutRedirect;
  },
  WebStorageStateStore: class {},
}));

import { signOut } from "./auth";
import { setConfig } from "./config";

describe("signOut with Cognito", () => {
  afterEach(() => vi.restoreAllMocks());

  it("drops the local session and opens the Cognito logout page (no end_session_endpoint)", async () => {
    const logoutUrl = "https://pool.auth.eu-central-1.amazoncognito.com/logout?client_id=c&logout_uri=https%3A%2F%2Fd.cloudfront.net%2F";
    setConfig({ apiUrl: "/api", authMode: "oidc", oidc: { authority: "https://cognito-idp.eu-central-1.amazonaws.com/p", clientId: "c", logoutUrl } });
    const assign = vi.fn();
    vi.spyOn(window, "location", "get").mockReturnValue({ ...window.location, origin: "https://d.cloudfront.net", assign });

    await signOut();

    expect(removeUser).toHaveBeenCalledOnce();
    expect(assign).toHaveBeenCalledWith(logoutUrl);
    expect(signoutRedirect).not.toHaveBeenCalled();
  });
});
