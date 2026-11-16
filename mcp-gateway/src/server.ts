// HTTP server: an authenticated, single-session reverse proxy in front of the
// upstream Conjur3 (conjur3-pilot) MCP.
//
//   customer MCP client ──Bearer <seat key>──▶  /mcp  ──▶  conjur3-pilot MCP
//
// The seat key is the API key. The first request (MCP `initialize`) starts the
// session; a second `initialize` for the same key takes over and the older
// session is evicted (its stream closed, its next request rejected).
import path from "path";
import fs from "fs";
import express, { type Request, type Response, type NextFunction } from "express";
import {
  createProxyMiddleware,
  fixRequestBody,
} from "http-proxy-middleware";
import { config, upstream } from "./config";
import { log } from "./logger";
import { redis } from "./redis";
import { resolveEntitlement, type Entitlement } from "./entitlements";
import { allow } from "./ratelimit";
import {
  activateSession,
  isActiveSession,
  registerConnection,
  unregisterConnection,
  releaseSession,
} from "./sessions";

interface GwRequest extends Request {
  ent?: Entitlement;
  isInit?: boolean;
}

function bearer(req: Request): string | null {
  const h = req.header("authorization");
  if (h?.toLowerCase().startsWith("bearer ")) return h.slice(7).trim();
  return req.header("x-api-key")?.trim() ?? null;
}

function clientIp(req: Request): string {
  return (req.header("x-forwarded-for")?.split(",")[0] || req.ip || "?").trim();
}

// ── Pre-session validation middleware (Redis-backed) ───────────────────────
// Stateless per request → Cloud Run friendly. Validates the seat key (entitlement
// cached in Redis) + rate limit on EVERY request. Single-session enforcement is
// intentionally OFF for now (SINGLE_SESSION=true to re-enable); multiple
// sessions per key are allowed.
async function gate(req: GwRequest, res: Response, next: NextFunction) {
  const key = bearer(req);
  if (!key) {
    return deny(res, 401, "missing_api_key", "Provide your seat key as a Bearer token.");
  }

  const ent = await resolveEntitlement(key);
  if (!ent) {
    log.audit("access.denied", { reason: "invalid_or_inactive_key", ip: clientIp(req) });
    return deny(res, 401, "invalid_key", "Key not found, not claimed, or subscription inactive.");
  }

  if (!(await allow(ent.keyId, config.rateLimitPerMin))) {
    return deny(res, 429, "rate_limited", "Too many requests for this seat.");
  }

  const msid = req.header("mcp-session-id");
  if (msid) {
    // Touch the Redis session record (validation + observability). Only enforce
    // single-session when explicitly enabled.
    if (config.singleSession && !(await isActiveSession(ent.keyId, msid))) {
      log.audit("access.denied", { reason: "session_superseded", keyId: ent.keyId, msid });
      return deny(res, 409, "session_superseded", "This session was taken over by a newer login.");
    }
  } else {
    // No session yet → only an `initialize` may open one.
    const isInit =
      req.method === "POST" &&
      typeof req.body === "object" &&
      (req.body as { method?: string })?.method === "initialize";
    if (!isInit) {
      return deny(res, 400, "no_session", "Missing mcp-session-id; send initialize first.");
    }
    req.isInit = true;
  }

  req.ent = ent;
  next();
}

function deny(res: Response, status: number, code: string, message: string) {
  res
    .status(status)
    .json({ jsonrpc: "2.0", error: { code: -32001, message }, data: { code } });
}

// ── Proxy to the upstream MCP ───────────────────────────────────────────────
const proxy = createProxyMiddleware<GwRequest, Response>({
  target: upstream.origin,
  changeOrigin: true,
  pathRewrite: () => upstream.path, // everything here routes to upstream /mcp
  on: {
    proxyReq: (proxyReq, req) => {
      // Tell conjur3-pilot which seat this request is for; it echoes this header
      // onto its FreeCAD RPC so the relay can route to that seat's connector.
      const seat = (req as GwRequest).ent?.keyId;
      if (seat) proxyReq.setHeader("x-conjur3-seat", seat);
      // express.json() consumed the body; re-stream it to the upstream.
      if (req.body && Object.keys(req.body).length) fixRequestBody(proxyReq, req);
    },
    proxyRes: (proxyRes, req, res) => {
      const gw = req as GwRequest;
      const incoming = req.headers["mcp-session-id"] as string | undefined;
      const minted = proxyRes.headers["mcp-session-id"] as string | undefined;

      // initialize succeeded → the minted session becomes the sole active one.
      if (gw.isInit && minted && gw.ent) {
        activateSession(gw.ent.keyId, minted).catch((e) =>
          log.error("activate failed", { err: String(e) }),
        );
      }

      // Track any live SSE stream so a takeover can close it instantly.
      const msid = minted || incoming;
      const ct = String(proxyRes.headers["content-type"] || "");
      if (msid && ct.includes("text/event-stream")) {
        registerConnection(msid, () => res.end());
        res.on("close", () => unregisterConnection(msid));
      }

      // Clean session teardown on DELETE.
      if (gw.ent && incoming && req.method === "DELETE") {
        releaseSession(gw.ent.keyId, incoming).catch(() => {});
      }
    },
    error: (err, _req, res) => {
      log.error("upstream proxy error", { err: err.message });
      if (res && "writeHead" in res && !res.headersSent) {
        (res as Response).status(502).json({
          jsonrpc: "2.0",
          error: { code: -32002, message: "Upstream MCP unavailable." },
        });
      }
    },
  },
});

// ── App ─────────────────────────────────────────────────────────────────────
export function createApp() {
  const app = express();
  app.disable("x-powered-by");
  app.set("trust proxy", true);

  // CORS — lets browser-based MCP clients (e.g. claude.ai connectors) reach the
  // gateway with the seat key. Token auth (no cookies), so "*" is safe; set
  // CORS_ORIGIN to lock down to a specific origin in production.
  app.use((req: Request, res: Response, next: NextFunction) => {
    const allow = config.corsOrigin === "*" ? req.headers.origin ?? "*" : config.corsOrigin;
    res.setHeader("Access-Control-Allow-Origin", allow);
    res.setHeader("Vary", "Origin");
    res.setHeader("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS");
    res.setHeader(
      "Access-Control-Allow-Headers",
      "authorization, content-type, accept, mcp-session-id, mcp-protocol-version, last-event-id",
    );
    res.setHeader("Access-Control-Expose-Headers", "mcp-session-id");
    res.setHeader("Access-Control-Max-Age", "86400");
    if (req.method === "OPTIONS") {
      res.status(204).end();
      return;
    }
    next();
  });

  // NB: GFE reserves the exact path "/healthz" on Cloud Run (returns its own 404
  // before the request reaches the container), so we also expose "/health".
  app.get(["/health", "/healthz"], async (_req, res) => {
    let redisOk = false;
    try {
      redisOk = (await redis.ping()) === "PONG";
    } catch {
      /* down */
    }
    let upstreamOk = false;
    try {
      const ctrl = AbortController ? new AbortController() : undefined;
      const t = ctrl ? setTimeout(() => ctrl.abort(), 1500) : undefined;
      const r = await fetch(upstream.origin, { signal: ctrl?.signal });
      if (t) clearTimeout(t);
      upstreamOk = r.status > 0; // any HTTP response means it's reachable
    } catch {
      /* unreachable */
    }
    res.json({
      ok: true,
      service: "conjur3-mcp-gateway",
      redis: redisOk ? "ok" : "down",
      upstream: upstreamOk ? "ok" : "down",
      upstreamUrl: config.upstreamMcpUrl,
    });
  });

  // Key verification — used by the installer's final "are we live?" check and
  // anything else that wants a cheap yes/no without opening an MCP session.
  app.get("/verify", async (req: Request, res: Response) => {
    const key = bearer(req);
    if (!key) {
      res.status(401).json({ ok: false, error: "missing_api_key" });
      return;
    }
    const ent = await resolveEntitlement(key);
    if (!ent) {
      log.audit("verify.denied", { ip: clientIp(req) });
      res.status(401).json({ ok: false, error: "invalid_key" });
      return;
    }
    if (!(await allow(ent.keyId, config.rateLimitPerMin))) {
      res.status(429).json({ ok: false, error: "rate_limited" });
      return;
    }
    res.json({ ok: true, orgId: ent.orgId });
  });

  // Public connector distribution: the curl installer + the bundled connector.
  //   curl -fsSL https://<host>/install.sh | bash
  const PUBLIC_DIR = path.join(__dirname, "..", "public");
  const servePublic = (file: string, type: string) => (_req: Request, res: Response) => {
    const p = path.join(PUBLIC_DIR, file);
    if (!fs.existsSync(p)) {
      res.status(404).type("text/plain").send("not available");
      return;
    }
    res.type(type);
    fs.createReadStream(p).pipe(res);
  };
  app.get("/install.sh",           servePublic("install.sh",           "text/x-shellscript"));
  app.get("/install.ps1",          servePublic("install.ps1",          "text/plain"));
  app.get("/update-mcp.sh",        servePublic("update-mcp.sh",        "text/x-shellscript"));
  app.get("/update-mcp.ps1",       servePublic("update-mcp.ps1",       "text/plain"));
  app.get("/connector.js",         servePublic("conjur3-connector.js", "application/javascript"));
  app.get("/conjur3-addon.tar.gz", servePublic("conjur3-addon.tar.gz", "application/gzip"));

  // Parse the small JSON-RPC body (needed to detect `initialize`), then gate,
  // then proxy. SSE/streaming responses pass straight through.
  app.use("/mcp", express.json({ limit: "4mb" }), gate, proxy);

  return app;
}
