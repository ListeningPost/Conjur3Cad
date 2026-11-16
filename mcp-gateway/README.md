# Conjur3 MCP Gateway

An authenticated, **single-session** reverse proxy that sits in front of the
Conjur3 **conjur3-pilot** MCP and turns it into a DRM-protected premium product.

```
customer MCP client ──Bearer <seat key>──▶  gateway (/mcp)  ──▶  conjur3-pilot MCP
        (Claude Code, etc.)                  │  Firestore: validate seat
                                             │  Redis: one live session / key
                                             ▼
                                   newest login wins · oldest is killed
```

The customer puts their **seat key** (`CJ3-XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX`) into their MCP client
as a bearer token. The gateway validates it against the same Firestore the web
app writes (`organizations` / `keys`), enforces exactly one live session per
key, and proxies authorized traffic to the upstream FreeCAD MCP.

## What it enforces

- **Key-gated** — no valid, *claimed* seat key whose org subscription is
  `active` → no access.
- **One session per key** — the first request (`initialize`) opens the session;
  a second `initialize` for the same key **takes over** and the earlier session
  is evicted: its SSE stream is closed and its next request gets `409
  session_superseded`.
- **Instant revocation** — entitlements are cached only ~30 s, so a cancelled
  subscription or revoked seat cuts access promptly (`onSubscriptionWrite` keeps
  `org.status` current).
- **Per-key rate limit** + structured **audit log** (`session.started`,
  `session.takeover`, `session.evicted`, `access.denied`).

## Why hosting is the real DRM
Because the FreeCAD kernel + agent run on **your** VM, the customer only ever
receives results — your IP never ships to the client. Single-session + key
revocation + watermarking (stamp the key id into exported STEP/STL metadata)
make sharing painful and traceable. What you *can't* stop: a paying user
scripting their own legitimate session or resharing the models they generate —
DRM here is access control + traceability, not unbreakable copy protection.

## Local development

```bash
npm install
cp .env.example .env
# .env: keep UPSTREAM_MCP_URL=http://localhost:8765/mcp,
#       set FIRESTORE_EMULATOR_HOST=127.0.0.1:8088 to use the emulator,
#       and run a local Redis (docker compose up redis, in the web app repo).
node --env-file=.env -r tsx/cjs src/index.ts   # or: npm run dev (loads ./.env)
```

Health check: `curl localhost:8080/healthz`.

### Test the gate
1. No key → `401 missing_api_key`. Bad key → `401 invalid_key`.
2. A **claimed** seat key (claim one in the web app's `/claim`) → `initialize`
   opens a session and traffic proxies through to FreeCAD.
3. Run a second client with the same key → the first is evicted (`409
   session_superseded` on its next call, stream closed).

## Deploy on your GCP VM

1. Attach a **service account** to the VM (roles: *Datastore User*, *Firebase
   Authentication Viewer*). ADC is then automatic — no key file.
2. `.env`: `NODE_ENV=production`, real `FIREBASE_PROJECT_ID`, **unset**
   `FIRESTORE_EMULATOR_HOST`, point `REDIS_URL` at local Redis or Memorystore.
3. `npm install && npm run build`
4. `sudo cp deploy/conjur3-mcp-gateway.service /etc/systemd/system/ &&
   sudo systemctl enable --now conjur3-mcp-gateway`
5. Front it with the included **Caddyfile** (auto-TLS, SSE-friendly). Docker
   image also provided.

## Scaling note
The eviction registry is in-process **and** broadcast over Redis pub/sub, so a
single VM works today and going multi-instance only needs **sticky sessions** at
the load balancer (the streaming connection must stay on one node). No code
change.

## Config (`.env`)
| var | default | meaning |
|-----|---------|---------|
| `PORT` | `8080` | gateway listen port (behind Caddy) |
| `UPSTREAM_MCP_URL` | `http://localhost:8765/mcp` | the conjur3-pilot MCP |
| `REDIS_URL` | `redis://localhost:6379` | sessions, eviction, cache, limits |
| `FIREBASE_PROJECT_ID` | `demo-conjur3` | Firestore project |
| `FIRESTORE_EMULATOR_HOST` | — | set for local emulator |
| `SESSION_TTL_SECONDS` | `90` | idle timeout that frees a seat |
| `RATE_LIMIT_PER_MIN` | `240` | per-key request cap |

> Future work (intentionally out of scope for this starter): isolating an
> upstream FreeCAD instance per session (the kernel is stateful), output
> watermarking, and impossible-travel anomaly blocking.
