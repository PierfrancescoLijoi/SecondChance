export type RunEvent = {
  type: "run.status";
  run_id: string;
  seq: number;
  outcome: string;
};

export function openRunSocket(
  baseUrl: string,
  token: string,
  tenantId: string,
  runId: string,
  Socket: typeof WebSocket = WebSocket,
): WebSocket {
  const url = new URL(baseUrl);
  url.searchParams.set("tenant_id", tenantId);
  url.searchParams.set("run_id", runId);
  return new Socket(url.toString(), ["secondchance", token]);
}

/** Azure Web PubSub: the API checks membership and ownership and returns a URL that only receives this run's events. */
export async function openNegotiatedRunSocket(
  negotiate: () => Promise<{ url: string }>,
  Socket: typeof WebSocket = WebSocket,
): Promise<WebSocket> {
  const { url } = await negotiate();
  return new Socket(url);
}
