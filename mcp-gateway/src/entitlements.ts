// Resolve a seat key (the customer's MCP API key) to an entitlement, against
// the same Firestore schema the web app + Cloud Functions write:
//   organizations/{orgId}                  (status: active | past_due | …)
//   organizations/{orgId}/keys/{keyId}      (hash, prefix, last4,
//                                            status: active | revoked, ownerUid)
//
// Keys are stored HASHED (SHA-256) — the presented plaintext is hashed and
// looked up by hash, so a database leak never leaks working keys. A key grants
// MCP access only if it is ACTIVE and its org subscription is ACTIVE. Results
// are cached in Redis briefly (keyed by hash — no plaintext at rest there
// either) to spare Firestore on every call.
import { createHash } from "crypto";
import { db } from "./firebase";
import { redis } from "./redis";
import { log } from "./logger";

export interface Entitlement {
  keyId: string;
  orgId: string;
  ownerUid: string | null;
}

// CJ3-<uuid> (128-bit). Case-insensitive; normalized to uppercase below.
const KEY_RE =
  /^CJ3-[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$/i;
const OK_TTL = 30; // seconds to cache a valid entitlement
const BAD_TTL = 10; // seconds to cache a rejection

function hashKey(code: string): string {
  return createHash("sha256").update(code).digest("hex");
}

export async function resolveEntitlement(
  rawKey: string,
): Promise<Entitlement | null> {
  // Strip optional =<agent> suffix (e.g. "CJ3-…=claude") before validating.
  const code = rawKey.trim().split("=")[0].toUpperCase();
  if (!KEY_RE.test(code)) return null;
  const hash = hashKey(code);

  const cacheKey = `ent:h:${hash}`;
  try {
    const hit = await redis.get(cacheKey);
    if (hit) return hit === "0" ? null : (JSON.parse(hit) as Entitlement);
  } catch {
    /* cache miss / redis down → fall through to Firestore */
  }

  let ent: Entitlement | null;
  try {
    ent = await lookup(hash);
  } catch (err) {
    // A Firestore error (e.g. a missing index, transient unavailability) must
    // never crash the gateway — deny this request without caching so it
    // recovers automatically once the backend is healthy.
    log.audit("entitlement.error", { message: (err as Error)?.message });
    return null;
  }
  try {
    await redis.set(
      cacheKey,
      ent ? JSON.stringify(ent) : "0",
      "EX",
      ent ? OK_TTL : BAD_TTL,
    );
  } catch {
    /* best effort */
  }
  return ent;
}

async function lookup(hash: string): Promise<Entitlement | null> {
  const snap = await db
    .collectionGroup("keys")
    .where("hash", "==", hash)
    .limit(1)
    .get();
  if (snap.empty) return null;

  const keyDoc = snap.docs[0];
  if (keyDoc.get("status") !== "active") return null;

  const orgRef = keyDoc.ref.parent.parent;
  if (!orgRef) return null;
  const org = await orgRef.get();
  if (!org.exists || org.get("status") !== "active") return null;

  log.audit("entitlement.ok", { keyId: keyDoc.id, orgId: orgRef.id });
  return {
    keyId: keyDoc.id,
    orgId: orgRef.id,
    ownerUid: (keyDoc.get("ownerUid") as string) ?? null,
  };
}

/** Invalidate a key's cache immediately (e.g., on rotate/revoke webhook). */
export async function invalidateEntitlement(code: string): Promise<void> {
  try {
    await redis.del(`ent:h:${hashKey(code.trim().toUpperCase())}`);
  } catch {
    /* best effort */
  }
}
