// Self-service API keys — each member mints, rotates, revokes, and deletes
// their OWN key. There is no pool of pre-minted codes: a key is born already
// owned by its claimer, the plaintext is returned exactly once, and Firestore
// keeps only its SHA-256 hash plus a display stub (prefix/last4).
//
// Seats: a member holding an ACTIVE key consumes one seat. seatLimit is raised
// by voucher (guided invite) redemptions, platform grants, or Stripe.
import { onCall, HttpsError } from "firebase-functions/v2/https";
import { FieldValue } from "firebase-admin/firestore";
import { db } from "./lib/admin";
import { requireVerified, requireOrgId } from "./lib/authz";
import { getFlags } from "./lib/flags";
import { generateKeyCode, hashKeyCode, keyDisplay } from "./lib/keys";

function orgRefOf(orgId: string) {
  return db.collection("organizations").doc(orgId);
}

/**
 * Claim your seat in `orgId`: mints a fresh key owned by the caller and
 * returns the plaintext code ONCE. Allowed when the caller is a member and
 * doesn't already hold an active key in this org.
 */
export const claimMyKey = onCall(async (req) => {
  const { uid, email } = requireVerified(req);
  const orgId = requireOrgId(req);
  const { stripeEnabled } = await getFlags();

  const orgRef = orgRefOf(orgId);
  const memberRef = orgRef.collection("members").doc(uid);
  const newKeyRef = orgRef.collection("keys").doc();

  const code = generateKeyCode();
  const { prefix, last4 } = keyDisplay(code);

  const orgName = await db.runTransaction(async (tx) => {
    const [orgDoc, memberDoc] = await Promise.all([
      tx.get(orgRef),
      tx.get(memberRef),
    ]);
    if (!orgDoc.exists) throw new HttpsError("not-found", "Organization missing.");
    if (!memberDoc.exists) {
      throw new HttpsError("permission-denied", "Not a member of this org.");
    }

    // One active key per member per org.
    const currentKeyId = memberDoc.get("keyId") as string | null;
    if (currentKeyId) {
      const current = await tx.get(orgRef.collection("keys").doc(currentKeyId));
      if (current.exists && current.get("status") === "active") {
        throw new HttpsError(
          "failed-precondition",
          "You already have an active key in this organization. Recreate it instead.",
        );
      }
    }

    if (stripeEnabled && orgDoc.get("status") !== "active") {
      throw new HttpsError(
        "failed-precondition",
        "Organization subscription is not active.",
      );
    }
    const seatLimit = (orgDoc.get("seatLimit") as number) ?? 0;
    const seatsUsed = (orgDoc.get("seatsUsed") as number) ?? 0;
    if (seatsUsed >= seatLimit) {
      throw new HttpsError(
        "resource-exhausted",
        "No seats remaining in this organization. Ask your admin for more seats.",
      );
    }

    tx.set(newKeyRef, {
      hash: hashKeyCode(code),
      prefix,
      last4,
      status: "active",
      ownerUid: uid,
      ownerEmail: email,
      createdAt: FieldValue.serverTimestamp(),
      rotatedAt: null,
    });
    tx.update(memberRef, { keyId: newKeyRef.id });
    tx.update(orgRef, { seatsUsed: FieldValue.increment(1) });

    return orgDoc.get("name") as string;
  });

  // The ONLY time the plaintext leaves the server.
  return { code, keyId: newKeyRef.id, prefix, last4, orgId, orgName };
});

/**
 * Recreate (rotate) your key in `orgId`: the old code stops working and a new
 * one is returned ONCE. Same seat — no usage change.
 */
export const rotateMyKey = onCall(async (req) => {
  const { uid } = requireVerified(req);
  const orgId = requireOrgId(req);

  const orgRef = orgRefOf(orgId);
  const memberRef = orgRef.collection("members").doc(uid);

  const code = generateKeyCode();
  const { prefix, last4 } = keyDisplay(code);

  const keyId = await db.runTransaction(async (tx) => {
    const memberDoc = await tx.get(memberRef);
    if (!memberDoc.exists) {
      throw new HttpsError("permission-denied", "Not a member of this org.");
    }
    const currentKeyId = memberDoc.get("keyId") as string | null;
    if (!currentKeyId) {
      throw new HttpsError("failed-precondition", "You have no key to recreate.");
    }
    const keyRef = orgRef.collection("keys").doc(currentKeyId);
    const keyDoc = await tx.get(keyRef);
    if (!keyDoc.exists || keyDoc.get("status") !== "active") {
      throw new HttpsError(
        "failed-precondition",
        "Your key is not active — claim a new one instead.",
      );
    }

    tx.update(keyRef, {
      hash: hashKeyCode(code),
      prefix,
      last4,
      rotatedAt: FieldValue.serverTimestamp(),
    });
    return currentKeyId;
  });

  return { code, keyId, prefix, last4, orgId };
});

/**
 * Invalidate your key in `orgId`. It stops working immediately (within the
 * gateway's short cache window); the record is kept, the seat is freed.
 */
export const revokeMyKey = onCall(async (req) => {
  const { uid } = requireVerified(req);
  const orgId = requireOrgId(req);

  const orgRef = orgRefOf(orgId);
  const memberRef = orgRef.collection("members").doc(uid);

  const keyId = await db.runTransaction(async (tx) => {
    const memberDoc = await tx.get(memberRef);
    if (!memberDoc.exists) {
      throw new HttpsError("permission-denied", "Not a member of this org.");
    }
    const currentKeyId = memberDoc.get("keyId") as string | null;
    if (!currentKeyId) {
      throw new HttpsError("failed-precondition", "You have no key to invalidate.");
    }
    const keyRef = orgRef.collection("keys").doc(currentKeyId);
    const keyDoc = await tx.get(keyRef);
    if (!keyDoc.exists || keyDoc.get("status") !== "active") {
      throw new HttpsError("failed-precondition", "Your key is already inactive.");
    }

    tx.update(keyRef, {
      status: "revoked",
      revokedAt: FieldValue.serverTimestamp(),
    });
    tx.update(orgRef, { seatsUsed: FieldValue.increment(-1) });
    return currentKeyId;
  });

  return { keyId, orgId, revoked: true };
});

/** Delete your key record in `orgId` entirely (frees the seat if active). */
export const deleteMyKey = onCall(async (req) => {
  const { uid } = requireVerified(req);
  const orgId = requireOrgId(req);

  const orgRef = orgRefOf(orgId);
  const memberRef = orgRef.collection("members").doc(uid);

  const keyId = await db.runTransaction(async (tx) => {
    const memberDoc = await tx.get(memberRef);
    if (!memberDoc.exists) {
      throw new HttpsError("permission-denied", "Not a member of this org.");
    }
    const currentKeyId = memberDoc.get("keyId") as string | null;
    if (!currentKeyId) {
      throw new HttpsError("failed-precondition", "You have no key to delete.");
    }
    const keyRef = orgRef.collection("keys").doc(currentKeyId);
    const keyDoc = await tx.get(keyRef);
    if (keyDoc.exists && keyDoc.get("status") === "active") {
      tx.update(orgRef, { seatsUsed: FieldValue.increment(-1) });
    }
    tx.delete(keyRef);
    tx.update(memberRef, { keyId: null });
    return currentKeyId;
  });

  return { keyId, orgId, deleted: true };
});
