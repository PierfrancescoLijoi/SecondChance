import { UserManager, WebStorageStateStore } from "oidc-client-ts";
import { config } from "./config";

// Authentication only proves who the user is; what they may do comes from /me (ADR-017).
const TOKEN_KEY = "secondchance.token";
let manager: UserManager | null = null;

function oidc(): UserManager {
  const settings = config().oidc;
  if (!settings) throw new Error("OIDC is not configured");
  manager ??= new UserManager({
    authority: settings.authority,
    client_id: settings.clientId,
    redirect_uri: `${window.location.origin}/callback`,
    post_logout_redirect_uri: window.location.origin,
    response_type: "code", // authorization code + PKCE: no client secret in the browser
    scope: settings.scope ?? "openid email",
    userStore: new WebStorageStateStore({ store: window.sessionStorage }),
  });
  return manager;
}

export async function currentToken(): Promise<string | null> {
  if (config().authMode === "oidc") {
    const user = await oidc().getUser();
    return user && !user.expired ? user.access_token : null;
  }
  return sessionStorage.getItem(TOKEN_KEY);
}

export async function signIn(): Promise<void> {
  await oidc().signinRedirect();
}

export async function completeSignIn(): Promise<void> {
  await oidc().signinRedirectCallback();
}

/** Local mock OIDC only: the API mints a token for a demo or brand-new subject. */
export async function devSignIn(subject: string): Promise<void> {
  const response = await fetch(`${config().apiUrl}/dev/token`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ subject }),
  });
  if (!response.ok) throw new Error("Development sign-in failed");
  const body = (await response.json()) as { access_token: string };
  sessionStorage.setItem(TOKEN_KEY, body.access_token);
}

export async function signOut(): Promise<void> {
  sessionStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem("secondchance.tenant");
  if (config().authMode !== "oidc") return;
  const logoutUrl = config().oidc?.logoutUrl;
  if (!logoutUrl) return oidc().signoutRedirect();
  await oidc().removeUser(); // the local session ends even if the provider page is never reached
  window.location.assign(logoutUrl);
}
