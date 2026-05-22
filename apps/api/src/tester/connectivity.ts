import net from "node:net";
import { config } from "../config.js";

export type ConnectivityResult =
  | { ok: true; latencyMs: number }
  | { ok: false; reason: string };

export function testTcpConnection(host: string, port: number): Promise<ConnectivityResult> {
  return new Promise((resolve) => {
    const startedAt = Date.now();
    const socket = new net.Socket();
    let settled = false;

    const finish = (result: ConnectivityResult) => {
      if (settled) return;
      settled = true;
      socket.destroy();
      resolve(result);
    };

    socket.setTimeout(config.TEST_CONNECT_TIMEOUT_MS);
    socket.once("connect", () => {
      finish({ ok: true, latencyMs: Date.now() - startedAt });
    });
    socket.once("timeout", () => {
      finish({ ok: false, reason: "timeout" });
    });
    socket.once("error", (error) => {
      finish({ ok: false, reason: normalizeError(error) });
    });
    socket.connect(port, host);
  });
}

function normalizeError(error: Error & { code?: string }) {
  if (error.code === "ENOTFOUND") return "dns_failed";
  if (error.code === "ECONNREFUSED") return "connection_refused";
  if (error.code === "ETIMEDOUT") return "timeout";
  if (error.code === "EHOSTUNREACH") return "host_unreachable";
  return error.code ?? "connection_failed";
}
