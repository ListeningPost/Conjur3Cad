// Redis-decoupled relay — lets an AUTOSCALED fleet of gateway instances drive
// each customer's local FreeCAD, regardless of which instance holds the
// connector's websocket.
//
//   conjur3-pilot ─XML-RPC(+X-Conjur3-Seat)─▶ relay RPC (this instance)
//        local connector for that seat?  ── yes ─▶ forward over its ws
//                                         └─ no  ─▶ publish mcpgw:rpc:req:<seat>
//                                                     (the instance holding the
//                                                      connector picks it up,
//                                                      forwards, and replies on
//                                                      mcpgw:rpc:res:<thisInst>)
//
// So connectors and MCP requests can land on different instances; Redis routes
// between them. Multiple sessions per key are allowed (single-session is off).
import http from "http";
import type { Server } from "http";
import { randomUUID } from "crypto";
import { WebSocketServer, WebSocket } from "ws";
import { resolveEntitlement } from "./entitlements";
import { redis, subscriber } from "./redis";
import { config } from "./config";
import { log } from "./logger";

const INSTANCE = randomUUID().slice(0, 8);
const reqChan = (seat: string) => `mcpgw:rpc:req:${seat}`;
const resChan = (inst: string) => `mcpgw:rpc:res:${inst}`;

// seat → local connector websocket (only for connectors attached to THIS node)
const localConnectors = new Map<string, WebSocket>();
// wsReqId → how to deliver the connector's reply (local HTTP res, or back over Redis)
type WsWaiter =
  | { kind: "http"; res: http.ServerResponse; timer: NodeJS.Timeout }
  | { kind: "redis"; fromInstance: string; reqId: string };
const wsPending = new Map<number, WsWaiter>();
// reqId → local HTTP res awaiting a cross-instance reply
const httpPending = new Map<string, { res: http.ServerResponse; timer: NodeJS.Timeout }>();
let wsSeq = 0;
let reqSeq = 0;

function sendToConnector(ws: WebSocket, waiter: WsWaiter, path: string, headers: Record<string, string>, body: string) {
  const id = ++wsSeq;
  wsPending.set(id, waiter);
  ws.send(JSON.stringify({ t: "req", id, path, headers, body }));
}

function onConnectorReply(msg: { id: number; status?: number; headers?: Record<string, string>; body?: string }) {
  const w = wsPending.get(msg.id);
  if (!w) return;
  wsPending.delete(msg.id);
  const ct = msg.headers?.["content-type"] ?? "text/xml";
  if (w.kind === "http") {
    clearTimeout(w.timer);
    w.res.writeHead(msg.status ?? 200, { "content-type": ct });
    w.res.end(msg.body ?? "");
  } else {
    redis.publish(resChan(w.fromInstance), JSON.stringify({
      reqId: w.reqId, status: msg.status ?? 200, headers: { "content-type": ct }, body: msg.body ?? "",
    })).catch(() => {});
  }
}

function register(seat: string, ws: WebSocket) {
  const prev = localConnectors.get(seat);
  if (prev && prev !== ws && config.singleSession) {
    try { prev.close(4001, "superseded"); } catch { /* gone */ }
  }
  localConnectors.set(seat, ws);
  subscriber.subscribe(reqChan(seat)).catch((e) => log.error("sub req failed", { err: String(e) }));
  log.audit("connector.registered", { seat, instance: INSTANCE });

  ws.on("message", (data) => {
    try { onConnectorReply(JSON.parse(String(data))); } catch { /* ignore */ }
  });
  ws.on("close", () => {
    if (localConnectors.get(seat) === ws) {
      localConnectors.delete(seat);
      subscriber.unsubscribe(reqChan(seat)).catch(() => {});
    }
    log.audit("connector.closed", { seat, instance: INSTANCE });
  });
  ws.on("error", () => { /* close handler cleans up */ });
}

// Cross-instance routing over Redis pub/sub.
subscriber.on("message", (channel, raw) => {
  if (channel === resChan(INSTANCE)) {
    let m: { reqId: string; status: number; headers?: Record<string, string>; body: string };
    try { m = JSON.parse(raw); } catch { return; }
    const p = httpPending.get(m.reqId);
    if (!p) return;
    httpPending.delete(m.reqId);
    clearTimeout(p.timer);
    p.res.writeHead(m.status, { "content-type": m.headers?.["content-type"] ?? "text/xml" });
    p.res.end(m.body);
    return;
  }
  if (channel.startsWith("mcpgw:rpc:req:")) {
    const seat = channel.slice("mcpgw:rpc:req:".length);
    const ws = localConnectors.get(seat);
    if (!ws) return; // not ours (another instance holds it)
    let m: { reqId: string; fromInstance: string; path: string; headers: Record<string, string>; body: string };
    try { m = JSON.parse(raw); } catch { return; }
    sendToConnector(ws, { kind: "redis", fromInstance: m.fromInstance, reqId: m.reqId }, m.path, m.headers, m.body);
  }
});

export function attachRelay(httpServer: Server, rpcPort: number, rpcHost = "127.0.0.1") {
  subscriber.subscribe(resChan(INSTANCE)).catch((e) => log.error("sub res failed", { err: String(e) }));

  const wss = new WebSocketServer({ noServer: true });
  httpServer.on("upgrade", (req, socket, head) => {
    const url = new URL(req.url ?? "/", "http://x");
    if (url.pathname !== "/connector") return;
    const key = url.searchParams.get("key") ?? "";
    resolveEntitlement(key)
      .then((ent) => {
        if (!ent) {
          socket.write("HTTP/1.1 401 Unauthorized\r\n\r\n"); socket.destroy();
          log.audit("connector.denied", { reason: "invalid_key" }); return;
        }
        wss.handleUpgrade(req, socket, head, (ws) => register(ent.keyId, ws));
      })
      .catch(() => socket.destroy());
  });

  // The fake "FreeCAD addon" conjur3-pilot connects to. The seat is carried on
  // the X-Conjur3-Seat header (set by the gateway, echoed by conjur3-pilot).
  http
    .createServer((req, res) => {
      const chunks: Buffer[] = [];
      req.on("data", (c) => chunks.push(c));
      req.on("end", () => {
        const seat = String(req.headers["x-conjur3-seat"] ?? "");
        const body = Buffer.concat(chunks).toString("utf8");
        const headers = { "content-type": String(req.headers["content-type"] ?? "text/xml") };
        if (!seat) { res.writeHead(400); res.end("missing X-Conjur3-Seat"); return; }

        const local = localConnectors.get(seat);
        if (local) {
          const timer = setTimeout(() => { res.writeHead(504); res.end("relay timeout"); }, 30_000);
          sendToConnector(local, { kind: "http", res, timer }, req.url ?? "/", headers, body);
          return;
        }
        // Connector lives on another instance → route via Redis.
        const reqId = `${INSTANCE}:${++reqSeq}`;
        const timer = setTimeout(() => {
          httpPending.delete(reqId);
          if (!res.headersSent) { res.writeHead(504); res.end("relay timeout (no connector)"); }
        }, 30_000);
        httpPending.set(reqId, { res, timer });
        redis.publish(reqChan(seat), JSON.stringify({ reqId, fromInstance: INSTANCE, path: req.url ?? "/", headers, body }))
          .then((n) => { if (n === 0) { clearTimeout(timer); httpPending.delete(reqId); if (!res.headersSent) { res.writeHead(503); res.end("no connector attached"); } } })
          .catch(() => {});
      });
    })
    .listen(rpcPort, rpcHost, () => log.info("relay RPC forwarder listening", { rpcHost, rpcPort, instance: INSTANCE }));
}
