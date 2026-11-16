// Org join invites — links an ORG ADMIN creates to bring people into their
// existing organization. The link carries no secrets: redeeming it only makes
// the visitor a member; they then mint their own API key from the dashboard
// (claimMyKey), which consumes a seat.
//
//   orgInvites/{token}
//     orgId, orgName, label, invitedEmail (single-use email invites),
//     maxUses, usedCount, expiresAt, status, createdByUid/Email, createdAt
//   orgInvites/{token}/redemptions/{uid}
import { onCall, HttpsError } from "firebase-functions/v2/https";
import { FieldValue, Timestamp } from "firebase-admin/firestore";
import { randomUUID } from "crypto";
import { db } from "./lib/admin";
import {
  requireVerified,
  requireOrgId,
  requireOrgAdminOrPlatform,
} from "./lib/authz";

const APP_URL = process.env.APP_URL || "https://conjur3.web.app";
const MAX_USES = 500;
const MAX_EXPIRY_MS = 365 * 24 * 60 * 60 * 1000;
const DEFAULT_EXPIRY_MS = 14 * 24 * 60 * 60 * 1000;

export interface OrgInviteOptions {
  orgId: string;
  orgName: string;
  createdByUid: string;
  createdByEmail: string | null;
  label?: string | null;
  invitedEmail?: string | null;
  maxUses?: number;
  expiresAtMs?: number;
}

/** Shared creator — used by the callable below and by inviteMember (email). */
export async function createOrgInviteDoc(
  opts: OrgInviteOptions,
): Promise<{ token: string; url: string }> {
  const token = randomUUID().replace(/-/g, "");
  const expiresAtMs = opts.expiresAtMs ?? Date.now() + DEFAULT_EXPIRY_MS;
  await db.collection("orgInvites").doc(token).set({
    token,
    orgId: opts.orgId,
    orgName: opts.orgName,
    label: opts.label ?? null,
    invitedEmail: opts.invitedEmail?.toLowerCase() ?? null,
    maxUses: opts.maxUses ?? 1,
    usedCount: 0,
    expiresAt: Timestamp.fromMillis(expiresAtMs),
    status: "active",
    createdByUid: opts.createdByUid,
    createdByEmail: opts.createdByEmail,
    createdAt: FieldValue.serverTimestamp(),
  });
  return { token, url: `${APP_URL}/invite/${token}` };
}

/** Create a shareable join link for YOUR org. Org admins (or platform). */
export const createOrgInvite = onCall(async (req) => {
  const orgId = requireOrgId(req);
  const { uid } = await requireOrgAdminOrPlatform(req, orgId);

  const label = String(req.data?.label ?? "").trim().slice(0, 80);
  const maxUses = Math.floor(Number(req.data?.maxUses ?? 10));
  if (!Number.isFinite(maxUses) || maxUses < 1 || maxUses > MAX_USES) {
    throw new HttpsError("invalid-argument", `maxUses must be 1..${MAX_USES}.`);
  }
  let expiresAtMs: number | undefined;
  if (req.data?.expiresAtMs != null) {
    expiresAtMs = Number(req.data.expiresAtMs);
    const now = Date.now();
    if (!Number.isFinite(expiresAtMs) || expiresAtMs <= now) {
      throw new HttpsError("invalid-argument", "expiresAtMs must be in the future.");
    }
    if (expiresAtMs - now > MAX_EXPIRY_MS) {
      throw new HttpsError("invalid-argument", "Expiry is too far in the future.");
    }
  }

  const orgDoc = await db.collection("organizations").doc(orgId).get();
  if (!orgDoc.exists) throw new HttpsError("not-found", "Organization missing.");

  const { token, url } = await createOrgInviteDoc({
    orgId,
    orgName: (orgDoc.get("name") as string) ?? "your team",
    createdByUid: uid,
    createdByEmail: (req.auth?.token.email as string | undefined) ?? null,
    label: label || null,
    maxUses,
    expiresAtMs,
  });
  return { token, url };
});

/** Disable (or delete) an org invite. Admin of that org, or platform. */
export const revokeOrgInvite = onCall(async (req) => {
  const token = String(req.data?.token ?? "");
  if (!token) throw new HttpsError("invalid-argument", "token required.");
  const ref = db.collection("orgInvites").doc(token);
  const snap = await ref.get();
  if (!snap.exists) throw new HttpsError("not-found", "Invite not found.");
  await requireOrgAdminOrPlatform(req, snap.get("orgId") as string);

  if (req.data?.remove === true) {
    await db.recursiveDelete(ref);
    return { token, removed: true };
  }
  await ref.update({ status: "disabled" });
  return { token, removed: false };
});

/**
 * Public, unauthenticated validity check used by the /invite page before
 * signup. Returns only non-sensitive fields.
 */
export const getOrgInvite = onCall(async (req) => {
  const token = String(req.data?.token ?? "");
  if (!token) return { valid: false, reason: "missing" };
  const snap = await db.collection("orgInvites").doc(token).get();
  if (!snap.exists) return { valid: false, reason: "not_found" };

  const inv = snap.data()!;
  const expiresAtMs = (inv.expiresAt as Timestamp | undefined)?.toMillis() ?? 0;
  const remaining = (inv.maxUses as number) - (inv.usedCount as number);
  let reason: string | null = null;
  if (inv.status !== "active") reason = "disabled";
  else if (expiresAtMs <= Date.now()) reason = "expired";
  else if (remaining <= 0) reason = "exhausted";

  return {
    valid: reason === null,
    reason,
    orgName: (inv.orgName as string) ?? null,
    label: (inv.label as string | null) ?? null,
  };
});

/**
 * Redeem an org invite: the verified caller becomes a `user`-tier member of
 * the invite's org. No key is minted here — that's claimMyKey, from the
 * dashboard, and that's also when a seat is consumed.
 */
export const redeemOrgInvite = onCall(async (req) => {
  const { uid, email } = requireVerified(req);
  const token = String(req.data?.token ?? "");
  if (!token) throw new HttpsError("invalid-argument", "token required.");

  const inviteRef = db.collection("orgInvites").doc(token);
  const redemptionRef = inviteRef.collection("redemptions").doc(uid);

  const result = await db.runTransaction(async (tx) => {
    const inviteDoc = await tx.get(inviteRef);
    if (!inviteDoc.exists) throw new HttpsError("not-found", "Invite not found.");
    const inv = inviteDoc.data()!;

    const orgId = inv.orgId as string;
    const orgRef = db.collection("organizations").doc(orgId);
    const memberRef = orgRef.collection("members").doc(uid);
    const [orgDoc, memberDoc] = await Promise.all([
      tx.get(orgRef),
      tx.get(memberRef),
    ]);
    if (!orgDoc.exists) throw new HttpsError("not-found", "Organization gone.");

    // Already a member → nothing to consume; just point them home.
    if (memberDoc.exists) {
      return { orgId, orgName: orgDoc.get("name") as string, alreadyMember: true };
    }

    const expiresAtMs = (inv.expiresAt as Timestamp | undefined)?.toMillis() ?? 0;
    if (inv.status !== "active") {
      throw new HttpsError("failed-precondition", "This invite is no longer active.");
    }
    if (expiresAtMs <= Date.now()) {
      throw new HttpsError("failed-precondition", "This invite has expired.");
    }
    if ((inv.usedCount as number) >= (inv.maxUses as number)) {
      throw new HttpsError("failed-precondition", "This invite has been fully used.");
    }
    const invitedEmail = inv.invitedEmail as string | null;
    if (invitedEmail && invitedEmail !== (email ?? "").toLowerCase()) {
      throw new HttpsError(
        "permission-denied",
        "This invite was sent to a different email address.",
      );
    }

    tx.set(memberRef, {
      uid,
      email,
      role: "user",
      status: "active",
      keyId: null,
      joinedAt: FieldValue.serverTimestamp(),
    });
    tx.update(inviteRef, { usedCount: FieldValue.increment(1) });
    tx.set(redemptionRef, {
      uid,
      email,
      orgId,
      redeemedAt: FieldValue.serverTimestamp(),
    });

    return { orgId, orgName: orgDoc.get("name") as string, alreadyMember: false };
  });

  return result;
});
