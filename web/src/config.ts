// Runtime configuration: one build for every environment. Locally public/config.json;
// on AWS Terraform writes config.json next to the app in S3 (ADR-018), on Azure the web container serves it from its environment (ADR-023).
export type AppConfig = {
  apiUrl: string;
  realtimeUrl?: string;
  // "negotiate" (Azure Web PubSub): the API mints a short-lived socket URL per run; default "websocket"
  // (AWS API Gateway): realtimeUrl is opened directly with the access token as a subprotocol.
  realtimeMode?: "websocket" | "negotiate";
  authMode: "mock" | "oidc";
  // logoutUrl: Cognito publishes no end_session_endpoint, so sign-out goes to its /logout page.
  oidc?: { authority: string; clientId: string; scope?: string; logoutUrl?: string };
};

let current: AppConfig | null = null;

export async function loadConfig(): Promise<AppConfig> {
  if (current) return current;
  const response = await fetch("/config.json", { cache: "no-store" });
  if (!response.ok) throw new Error("config.json is not available");
  current = (await response.json()) as AppConfig;
  return current;
}

export function config(): AppConfig {
  if (!current) throw new Error("configuration not loaded");
  return current;
}

/** Tests only. */
export function setConfig(value: AppConfig): void {
  current = value;
}
