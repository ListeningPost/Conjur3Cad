#!/usr/bin/env node
// Conjur3 connector — runs on the user's machine next to FreeCAD.
//
// It dials OUT to the hosted relay (so there are no inbound ports / firewall
// holes), authenticates with the seat key, and forwards each request the hosted
// MCP makes down to the local FreeCAD addon, streaming the response back.
// It contains no product logic — the MCP commands/code/knowledge stay on the
// server.
//
//   CONJUR3_KEY=CJ3-XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX \
//   conjur3-connector --relay wss://mcp.conjur3.com --local http://127.0.0.1:9875
import { WebSocket } from "ws";

function arg(flag: string, env: string, def: string): string {
  const i = process.argv.indexOf(flag);
  if (i !== -1 && process.argv[i + 1]) return process.argv[i + 1];
  return process.env[env] ?? def;
}

const KEY = arg("--key", "CONJUR3_KEY", "");
const RELAY = arg("--relay", "CONJUR3_RELAY", "ws://127.0.0.1:8090").replace(/\/$/, "");
const LOCAL = arg("--local", "CONJUR3_LOCAL", "http://127.0.0.1:9875").replace(/\/$/, "");

if (!KEY) {
  console.error("Missing seat key. Pass --key CJ3-… or set CONJUR3_KEY.");
  process.exit(1);
}

interface Req { t: "req"; id: number; path: string; headers: Record<string, string>; body: string }

let backoff = 1000;
function connect() {
  const url = `${RELAY}/connector?key=${encodeURIComponent(KEY)}`;
  const ws = new WebSocket(url);

  ws.on("open", () => {
    backoff = 1000;
    console.log(`[connector] linked to ${RELAY} → forwarding to ${LOCAL}`);
  });

  ws.on("message", async (data) => {
    let m: Req;
    try { m = JSON.parse(String(data)); } catch { return; }
    if (m.t !== "req") return;
    try {
      const r = await fetch(`${LOCAL}${m.path}`, {
        method: "POST",
        headers: { "content-type": m.headers["content-type"] ?? "text/xml" },
        body: m.body,
      });
      const body = await r.text();
      ws.send(JSON.stringify({
        t: "res", id: m.id, status: r.status,
        headers: { "content-type": r.headers.get("content-type") ?? "text/xml" }, body,
      }));
    } catch (e) {
      ws.send(JSON.stringify({ t: "res", id: m.id, status: 502, body: `connector: ${String(e)}` }));
    }
  });

  ws.on("close", (code) => {
    if (code === 4001) { console.error("[connector] superseded by a newer session — exiting."); process.exit(0); }
    console.error(`[connector] disconnected (code ${code}); retrying in ${backoff}ms`);
    setTimeout(connect, backoff);
    backoff = Math.min(backoff * 2, 15000);
  });
  ws.on("error", (e) => console.error("[connector] error:", e.message));
}

connect();
