import { describe, expect, it, vi } from "vitest";
import { openRunSocket } from "./realtime";

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
