import { describe, expect, it, vi } from "vitest";
import { openNegotiatedRunSocket, openRunSocket } from "./realtime";

describe("run WebSocket", () => {
  it("connects with the JWT as a WebSocket subprotocol and scopes the subscription", () => {
    const Socket = vi.fn(function (this: { url: string; protocols: string[] }, url: string, protocols: string[]) {
      this.url = url;
      this.protocols = protocols;
    });

    openRunSocket(
      "wss://events.example/prod",
      "signed.jwt.token",
      "tenant-1",
      "run-1",
      Socket as unknown as typeof WebSocket,
    );

    expect(Socket).toHaveBeenCalledWith(
      "wss://events.example/prod?tenant_id=tenant-1&run_id=run-1",
      ["secondchance", "signed.jwt.token"],
    );
  });
});

describe("negotiated run WebSocket (Azure)", () => {
  it("opens exactly the URL the API returned, with no token of its own", async () => {
    const Socket = vi.fn(function (this: { url: string }, url: string) {
      this.url = url;
    });

    const socket = await openNegotiatedRunSocket(
      async () => ({ url: "wss://pubsub.example/client/hubs/runs?access_token=short-lived" }),
      Socket as unknown as typeof WebSocket,
    );

    expect(Socket).toHaveBeenCalledWith("wss://pubsub.example/client/hubs/runs?access_token=short-lived");
    expect(socket).toBeDefined();
  });

  it("fails without opening anything when the API refuses", async () => {
    const Socket = vi.fn();
    await expect(
      openNegotiatedRunSocket(async () => Promise.reject(new Error("503")), Socket as unknown as typeof WebSocket),
    ).rejects.toThrow("503");
    expect(Socket).not.toHaveBeenCalled();
  });
});
