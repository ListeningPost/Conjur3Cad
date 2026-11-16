# Conjur3 — Development & Production Runbook

Everything needed to run the whole product locally and ship it to production.

## Topology

```
                    ┌──────────────────────── Firebase (managed) ───────────────────────┐
   browser ───────▶ │  Hosting (Next.js)   Auth   Firestore   Cloud Functions   Stripe   │
                    │     conjur3.com                          (orgs/keys/seats)  ext.    │
                    └────────────────────────────────────────────────────────────────────┘
                                                  ▲ reads keys/orgs (Admin SDK)
   Claude Code ─Bearer seat key─▶ Caddy(TLS) ─▶ gateway ─┘ ─▶ mcp (conjur3-pilot)
   (user's LLM)    mcp.conjur3.com  │ 1 session/key (DRM) + relay      │ RPC
        │                          └──────── GCP VM · Compose · Redis ──│──────┘
        │                                              relay (wss) ◀────┘
        ▼                                                  │
   ┌─ user's machine ─────────────────────────────────────┼──────────┐
   │  FreeCAD + addon (RPC :9875) ◀── connector (dials out)┘          │
   └──────────────────────────────────────────────────────────────────┘
```

- **Firebase** — web app + identity + billing + the keys/orgs/seats source of truth.
- **GCP VM (no FreeCAD!)** — Caddy → `mcp-gateway` (key auth + single-session DRM + relay) → `mcp` (the hosted conjur3-pilot = your IP, pure Python). Redis for sessions.
- **User's machine** — FreeCAD + the addon + a tiny **connector** that dials out to the relay. The hosted MCP pilots their local FreeCAD through that tunnel; none of the MCP code ships to the client.

---

## 1. Prerequisites
- Node 20+, Docker + Compose, Java JRE (emulators), Firebase CLI (`npm i -g firebase-tools`).
- A **Blaze-plan** Firebase project (Functions + custom claims need it).
- A GCP Compute Engine VM with Docker, a service account, and a domain you control.

## 2. Local development (one command)

```bash
make install          # app + functions + gateway deps
make dev              # Redis + emulators + seed + conjur3-pilot + gateway + web
```
`make dev` brings up the whole stack and seeds runtime config only (no accounts). Then:
- Web app → http://localhost:3000 · Emulator UI → http://localhost:4000
- Gateway → http://localhost:8090/health · conjur3-pilot → http://127.0.0.1:8765/mcp
- **Sign up** in the app to create your account/org. While Stripe is off, keys
  are minted by **platform admins** only (emails in `PLATFORM_ADMIN_EMAILS`, verified email) —
  on the emulator, mark the account verified or use the Auth-emulator UI.

No local FreeCAD? `SKIP_FREECAD=1 make dev` (or run pieces in separate terminals:
`make redis`, `make emulators`, `make seed`, `make web`, `make gateway`, `make freecad`).
`make stop` kills everything; `make logs` tails `.dev-logs/`.

### Test the MCP DRM locally
As a platform admin, mint a key from `/platform`, then point any MCP client at
`http://localhost:8090/mcp` with `Authorization: Bearer <that key>`. A second
client on the same key evicts the first when `SINGLE_SESSION=true`.

---

## 3. Production — Firebase (web + identity + billing)

```bash
firebase login
firebase use --add            # select your Blaze project, alias "default"
firebase experiments:enable webframeworks
```
1. Put real web config in **`.env.production`** (copy `.env.production.example`):
   `NEXT_PUBLIC_FIREBASE_*`, `NEXT_PUBLIC_USE_EMULATORS=false`,
   `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY`, `NEXT_PUBLIC_STRIPE_SEAT_PRICE_ID`.
   (`.env.production` is gitignored; the `.example` is the tracked template.)
   **Platform admins:** copy `functions/.env.demo-conjur3.example` to
   `functions/.env.<projectId>` and set `PLATFORM_ADMIN_EMAILS` (comma-separated),
   and set the same list in `NEXT_PUBLIC_PLATFORM_ADMIN_EMAILS`. Nobody is a
   platform admin until you do; Functions mirror the list to `config/platform`
   for the Firestore rules on their next cold start.
2. **Stripe extension** (seat billing):
   ```bash
   firebase ext:install stripe/firestore-stripe-payments
   ```
   Configure the secret key + webhook signing secret, create a recurring
   per-seat **Price**, and copy its id into `NEXT_PUBLIC_STRIPE_SEAT_PRICE_ID`.
3. Deploy:
   ```bash
   FIREBASE_PROJECT=your-project-id ./scripts/deploy-firebase.sh
   # → Firestore rules+indexes, Cloud Functions, and the Next app (Hosting)
   ```

## 4. Production — GCP VM (the premium MCP)

**Provision once:**
- Attach a **service account** to the VM with roles *Datastore User* + *Firebase
  Authentication Viewer*. Admin SDK then uses ADC from the metadata server
  inside containers — no key file.
- Install Docker + Compose. Point an **A record** `mcp.conjur3.com` → VM IP.
- Edit `deploy/Caddyfile` (domain + email) and `deploy/.env`
  (`FIREBASE_PROJECT_ID` = your real project).

**Deploy:**
```bash
VM_HOST=ubuntu@<vm-ip> ./scripts/deploy-vps.sh
```
This vendors the conjur3-pilot source, rsyncs `deploy/` + `mcp-gateway/`, and
runs `docker compose -f docker-compose.prod.yml up -d --build`. Verify:
```bash
curl https://mcp.conjur3.com/health   # {"redis":"ok","upstream":"ok",…}
```

No FreeCAD runs on the VM — the `mcp` container is pure Python and reaches each
customer's FreeCAD over the relay.

## 4b. Customer setup (their machine)
Each customer (on their own machine, with their own AI client + model):
1. Install **FreeCAD** + the **conjur3-pilot addon** (RPC bridge on `:9875`).
2. Run the **connector** (dials out — no inbound ports):
   ```bash
   CONJUR3_KEY=CJ3-XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX \
   conjur3-connector --relay wss://mcp.conjur3.com --local http://127.0.0.1:9875
   ```
3. Add the hosted MCP to their client (e.g. Claude Code):
   ```bash
   claude mcp add conjur3 --transport http https://mcp.conjur3.com/mcp \
     --header "Authorization: Bearer CJ3-XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX"
   ```
Now their agent calls the hosted Conjur3 tools, which pilot their local FreeCAD
through the connector. Multiple sessions per key are allowed by default
(`SINGLE_SESSION=true` to enforce one).

## 4c. Autoscaling on Cloud Run (recommended over the single VM)
The MCP is autoscale-ready: the gateway is stateless per request (Redis-backed
validation middleware), and the relay is **decoupled over Redis pub/sub** —
each FreeCAD RPC is routed to the right connector *by seat*, so connectors and
requests can land on different instances. Deploy in your Firebase/GCP project:
```bash
PROJECT_ID=your-project-id REGION=us-central1 ./scripts/deploy-cloudrun.sh
```
The gateway sends **CORS** headers (`CORS_ORIGIN`, default `*`) so browser MCP
clients — e.g. **claude.ai custom connectors** — can reach `…/mcp` with the seat
key; lock `CORS_ORIGIN` to `https://claude.ai` for production. Claude Code (CLI)
connects via `claude mcp add --transport http … --header "Authorization: Bearer …"`
(see ONBOARDING.md).

`deploy/cloudrun/service.yaml` runs the gateway + conjur3-pilot as a
multi-container service, `minScale 1 / maxScale 10`. **Use a shared Redis**
(Upstash `rediss://` needs no VPC connector; Memorystore needs a Serverless VPC
connector) so the pub/sub backbone is common to the fleet. Front it with a
Firebase Hosting rewrite (or custom domain) for `mcp.conjur3.com`.

---

## 5. Environment reference
| Where | Key vars |
|-------|----------|
| Web app (`.env.local` / `.env.production`) | `NEXT_PUBLIC_FIREBASE_*`, `NEXT_PUBLIC_USE_EMULATORS`, `NEXT_PUBLIC_STRIPE_*` |
| Gateway (`deploy/.env`) | `FIREBASE_PROJECT_ID`, `SESSION_TTL_SECONDS`, `RATE_LIMIT_PER_MIN` |
| Compose-set | `PORT`, `REDIS_URL`, `UPSTREAM_MCP_URL` |

## 6. Operations
- **Logs:** `docker compose -f deploy/docker-compose.prod.yml logs -f gateway`
  (gateway emits JSON audit lines: `session.started/takeover/evicted`, `access.denied`).
- **Update:** re-run `deploy-vps.sh` (rebuilds + rolling restart) / `deploy-firebase.sh`.
- **Rollback:** Functions/Hosting keep versions in the Firebase console; the VM
  can `docker compose up -d` a previous image tag.
- **Scale out:** the relay is **Redis-decoupled** — each FreeCAD RPC is routed
  to the right connector by seat over Redis pub/sub, so any instance serves any
  seat. Horizontal autoscaling (Cloud Run `maxScale>1` or multiple VMs) needs
  only a **shared** Redis; no sticky sessions. FreeCAD runs on each customer's
  machine, so the server stays lightweight.

## 7. Cost notes
- **No FreeCAD on the server** (it runs on customers' machines via the relay),
  so the hosted tier is featherweight — gateway + Python MCP + Redis. A small VM
  or Cloud-Run-to-zero handles many users.
- Web app on **Firebase Hosting**: ~$0–10/mo at low/moderate traffic (SSR on
  Cloud Run, generous free tier), autoscales.
- Customers bring their own model, so **you pay $0 for inference**. Main cost
  drivers are Cloud Run/VM baseline, Redis, and screenshot egress.
