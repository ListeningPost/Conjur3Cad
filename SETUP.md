# Conjur3 — Setup & Operations

The Conjur3 team-access app: a Next.js 15 + Firebase application with
seat-based Stripe subscriptions, organization/admin/user roles, and license-key
seat claiming. Cloud Functions hold all trusted logic; an optional Redis layer
powers rate limiting and caching.

---

## 1. Prerequisites

| Tool | Why | Notes |
|------|-----|-------|
| Node.js 20+ | app + functions | `node -v` |
| Java JDK 11+ | **required** by the Firestore & Auth emulators | `sudo apt install default-jre` (Debian/Ubuntu) |
| Firebase CLI | emulators + deploy | `npm i -g firebase-tools` (or use `npx firebase`) |
| Docker | local Redis (optional) | only if you want the Redis layer locally |

> The Firebase **emulators will not start without a JRE.** Install Java first.

---

## 2. Install

```bash
npm install
npm --prefix functions install
cp .env.example .env.local      # already created for local dev
```

`.env.local` ships with emulator-friendly demo values
(`NEXT_PUBLIC_USE_EMULATORS=true`, project `demo-conjur3`). No real keys are
needed to run locally.

---

## 3. Run locally (emulator mode)

Three terminals (or background them):

```bash
# 1. Firebase emulators (auth, firestore, functions) — needs Java
firebase emulators:start

# 2. Next.js dev server
npm run dev

# 3. (optional) Redis for rate limiting + caching
npm run redis:up        # docker compose: redis + redis-commander UI :8081
```

- App: http://localhost:3000
- Emulator UI: http://localhost:4000
- Redis UI: http://localhost:8081

The web SDK auto-connects to the emulators because `NEXT_PUBLIC_USE_EMULATORS=true`.

### End-to-end test flow (no live Stripe required)

1. **Sign up** user A → redirected to the dashboard.
2. **Create org** (`/onboarding`) → A becomes the **owner**.
3. **Billing** (`/billing`) → in emulator mode use **"Seed N seats"** to mark
   the subscription active (this stands in for Stripe checkout).
4. **Team** (`/admin`) → **Mint keys** (one per seat). Copy a key code.
5. In a separate browser/profile, **sign up** user B → **Claim a key**
   (`/claim`) with the copied code → B joins as a **member**, a seat is consumed.
6. Back as A, in **Team**, **Make admin** / **Revoke** B → revoking frees the seat.
7. `GET /api/health` reports app + Redis status.

---

## 4. Going live

### 4a. Firebase project
```bash
firebase login
firebase use --add            # select/create your real project, alias "default"
# (or edit .firebaserc — currently "demo-conjur3")
```
Set `.env.local` (and your host's env) to the real web config from
Firebase console → Project settings, and `NEXT_PUBLIC_USE_EMULATORS=false`.

Cloud Functions and custom claims require the **Blaze** (pay-as-you-go) plan.

Deploy rules + functions:
```bash
firebase deploy --only firestore:rules,firestore:indexes,functions
```

### 4b. Stripe — seat-based subscriptions (the "plugin")
Install the official extension:
```bash
firebase ext:install stripe/firestore-stripe-payments
```
During configuration:
- Provide your Stripe **restricted/secret key** and set the **webhook signing secret**
  (the extension prints the webhook URL — add it in the Stripe dashboard).
- "Sync new users to Stripe customers" → optional; the owner becomes the customer.
- Collections: `customers`, `products` (matches `firestore.rules`).

Then in Stripe (test mode first):
- Create a **Product** with a **recurring per-seat Price** (e.g. "Conjur3 Seat").
- Copy the **price id** into `NEXT_PUBLIC_STRIPE_SEAT_PRICE_ID`, and the
  **publishable key** into `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY`.

The extension publishes products/prices into Firestore, writes
`customers/{uid}/subscriptions/*` from webhooks, and exposes the
`createPortalLink` callable used by `/billing`. Our `onSubscriptionWrite`
function translates the subscription `quantity` → the org's `seatLimit`.

### 4c. Redis (production)
Set `REDIS_URL` (or `UPSTASH_REDIS_REST_URL` + token) in the host env:
- **Upstash** — serverless-friendly, works behind serverless hosting. Recommended for Vercel/Cloud Run.
- **GCP Memorystore** — if hosting on GCP; reach it from the Next.js server over a VPC connector.
- The app **fails open**: with no Redis configured, rate limiting and caching are skipped, not broken.

### 4d. Hosting
`firebase.json` is configured for Firebase Hosting web frameworks:
```bash
firebase experiments:enable webframeworks   # if not already
firebase deploy --only hosting
```
(Or deploy the Next.js app to any Node host; keep Functions/Firestore on Firebase.)

---

## 5. Architecture map

| Concern | Where |
|---------|-------|
| Brand/design tokens | `src/app/globals.css` (`@theme`), fonts in `src/app/layout.tsx` |
| Auth + claims (role/orgId) | `src/context/AuthContext.tsx` |
| Route guards | `src/hooks/useRequireAuth.ts` |
| Callable wrappers | `src/lib/callables.ts` |
| Trusted server logic | `functions/src/*` (orgs, seat keys, members, billing sync) |
| Security rules | `firestore.rules` |
| Redis layer | `src/lib/{redis,rateLimit,cache}.ts`, `src/app/api/*` |

### Data model
- `users/{uid}` — profile mirror (`orgId`, `role`, `claimedKeyId`).
- `organizations/{orgId}` — `ownerUid`, `seatLimit`, `seatsUsed`, `status`.
- `organizations/{orgId}/members/{uid}` — `role` (owner|admin|member).
- `organizations/{orgId}/keys/{keyId}` — license keys (`available|claimed|revoked`).
- Custom claims `{ role, orgId }` are set only by Cloud Functions.

### Roles
- **Owner** (the "organization"): created the org, owns Stripe billing, full control.
- **Admin**: mints keys, manages members (member-level). Only the owner manages admins.
- **Member/User**: claims a key to occupy a seat and gain access.
