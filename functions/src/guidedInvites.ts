// Guided sign-up invites ("seat vouchers").
//
// A platform super-admin generates a shareable link worth `seats` seats per
// redemption (one batch can cover many redemptions via `maxSignups`, and
// expires at `expiresAt`). Each person who redeems it chooses to either ADD
// those seats to an organization they already administer, or CREATE a new
// organization with that seat allotment and themselves as admin/owner.
//
// No keys are pre-minted — members mint their own (claimMyKey) against the
// org's seat count, so no secret ever sits unclaimed in the database.
import { onCall, HttpsError } from "firebase-functions/v2/https";
import { FieldValue, Timestamp } from "firebase-admin/firestore";
import { randomUUID } from "crypto";
import { db, normalizeRole } from "./lib/admin";
import { requireAuth, requireVerified } from "./lib/authz";
import { isPlatformAdmin } from "./lib/platform";
import { sendEmail, emailLayout } from "./lib/email";

const APP_URL = process.env.APP_URL || "https://conjur3.web.app";
const MAX_SIGNUPS = 1000;
const MAX_SEATS = 500;
const MAX_EXPIRY_MS = 365 * 24 * 60 * 60 * 1000;

function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 32);
}

/** Create a guided-signup invite. Platform super-admins only. */
export const createGuidedInvite = onCall(async (req) => {
  requireAuth(req);
  if (!isPlatformAdmin(req)) {
    throw new HttpsError("permission-denied", "Platform admins only.");
  }

  const label = String(req.data?.label ?? "").trim().slice(0, 80);
  const maxSignups = Math.floor(Number(req.data?.maxSignups ?? 1));
  const seats = Math.floor(Number(req.data?.seats ?? 5));
  const expiresAtMs = Number(req.data?.expiresAtMs);

  if (!Number.isFinite(maxSignups) || maxSignups < 1 || maxSignups > MAX_SIGNUPS) {
    throw new HttpsError("invalid-argument", `maxSignups must be 1..${MAX_SIGNUPS}.`);
  }
  if (!Number.isFinite(seats) || seats < 1 || seats > MAX_SEATS) {
    throw new HttpsError("invalid-argument", `seats must be 1..${MAX_SEATS}.`);
  }
  const now = Date.now();
  if (!Number.isFinite(expiresAtMs) || expiresAtMs <= now) {
    throw new HttpsError("invalid-argument", "expiresAtMs must be in the future.");
  }
  if (expiresAtMs - now > MAX_EXPIRY_MS) {
    throw new HttpsError("invalid-argument", "Expiry is too far in the future.");
  }

  const token = randomUUID().replace(/-/g, "");
  const ref = db.collection("guidedInvites").doc(token);
  await ref.set({
    token,
    label: label || null,
    maxSignups,
    usedCount: 0,
    seats,
    expiresAt: Timestamp.fromMillis(expiresAtMs),
    status: "active",
    createdByUid: req.auth!.uid,
    createdByEmail: (req.auth?.token.email as string | undefined) ?? null,
    createdAt: FieldValue.serverTimestamp(),
  });

  return { id: token, token, url: `${APP_URL}/join/${token}` };
});

/** Disable (or delete) a guided invite. Platform super-admins only. */
export const disableGuidedInvite = onCall(async (req) => {
  requireAuth(req);
  if (!isPlatformAdmin(req)) {
    throw new HttpsError("permission-denied", "Platform admins only.");
  }
  const id = String(req.data?.id ?? "");
  if (!id) throw new HttpsError("invalid-argument", "id required.");
  const ref = db.collection("guidedInvites").doc(id);
  if (req.data?.remove === true) {
    await db.recursiveDelete(ref);
    return { id, removed: true };
  }
  await ref.update({ status: "disabled" });
  return { id, removed: false };
});

/**
 * Public, unauthenticated validity check used by the /join page before signup.
 * Returns only non-sensitive fields.
 */
export const getGuidedInvite = onCall(async (req) => {
  const token = String(req.data?.token ?? "");
  if (!token) return { valid: false, reason: "missing" };
  const snap = await db.collection("guidedInvites").doc(token).get();
  if (!snap.exists) return { valid: false, reason: "not_found" };

  const inv = snap.data()!;
  const expiresAtMs = (inv.expiresAt as Timestamp | undefined)?.toMillis() ?? 0;
  const remaining = (inv.maxSignups as number) - (inv.usedCount as number);
  let reason: string | null = null;
  if (inv.status !== "active") reason = "disabled";
  else if (expiresAtMs <= Date.now()) reason = "expired";
  else if (remaining <= 0) reason = "exhausted";

  return {
    valid: reason === null,
    reason,
    label: (inv.label as string | null) ?? null,
    seats: (inv.seats as number) ?? (inv.keysPerSignup as number) ?? 0,
    remaining: Math.max(0, remaining),
    expiresAtMs,
  };
});

/**
 * Redeem a seat voucher. Two modes:
 *   { token, mode: "create", orgName? }  → new org with `seats` seats, caller
 *                                          is admin/owner.
 *   { token, mode: "attach", orgId }     → +`seats` seats on an org the caller
 *                                          already administers.
 * Requires a signed-in, verified user. One redemption per user per invite.
 */
export const redeemGuidedInvite = onCall(async (req) => {
  const { uid, email } = requireVerified(req);

  const inviteToken = String(req.data?.token ?? "");
  if (!inviteToken) throw new HttpsError("invalid-argument", "token required.");
  const mode = req.data?.mode === "attach" ? "attach" : "create";
  const rawName = String(req.data?.orgName ?? "").trim();
  const attachOrgId = String(req.data?.orgId ?? "");
  if (mode === "attach" && !attachOrgId) {
    throw new HttpsError("invalid-argument", "orgId required to add seats.");
  }

  const inviteRef = db.collection("guidedInvites").doc(inviteToken);
  const redemptionRef = inviteRef.collection("redemptions").doc(uid);
  const newOrgRef = db.collection("organizations").doc();

  const result = await db.runTransaction(async (tx) => {
    const inviteDoc = await tx.get(inviteRef);
    if (!inviteDoc.exists) throw new HttpsError("not-found", "Invite not found.");
    const inv = inviteDoc.data()!;

    const expiresAtMs = (inv.expiresAt as Timestamp | undefined)?.toMillis() ?? 0;
    if (inv.status !== "active") {
      throw new HttpsError("failed-precondition", "This invite is no longer active.");
    }
    if (expiresAtMs <= Date.now()) {
      throw new HttpsError("failed-precondition", "This invite has expired.");
    }
    if ((inv.usedCount as number) >= (inv.maxSignups as number)) {
      throw new HttpsError("failed-precondition", "This invite has been fully used.");
    }
    const already = await tx.get(redemptionRef);
    if (already.exists) {
      throw new HttpsError("failed-precondition", "You've already used this invite.");
    }

    const seats = (inv.seats as number) ?? (inv.keysPerSignup as number) ?? 0;
    if (seats < 1) {
      throw new HttpsError("failed-precondition", "This invite grants no seats.");
    }

    let orgId: string;
    let orgName: string;

    if (mode === "attach") {
      const orgRef = db.collection("organizations").doc(attachOrgId);
      const memberRef = orgRef.collection("members").doc(uid);
      const [orgDoc, memberDoc] = await Promise.all([
        tx.get(orgRef),
        tx.get(memberRef),
      ]);
      if (!orgDoc.exists) throw new HttpsError("not-found", "Organization missing.");
      if (!memberDoc.exists || normalizeRole(memberDoc.get("role")) !== "admin") {
        throw new HttpsError(
          "permission-denied",
          "You can only add seats to an organization you administer.",
        );
      }
      tx.update(orgRef, {
        seatLimit: FieldValue.increment(seats),
        // Comped seats make the org usable even if billing never ran.
        ...(orgDoc.get("status") === "inactive" ? { status: "active" } : {}),
      });
      orgId = orgRef.id;
      orgName = orgDoc.get("name") as string;
    } else {
      orgName =
        rawName.length >= 2
          ? rawName.slice(0, 80)
          : (email ? `${email.split("@")[0]}'s workspace` : "My workspace");
      const slug = `${slugify(orgName) || "org"}-${newOrgRef.id.slice(0, 5).toLowerCase()}`;

      tx.set(newOrgRef, {
        name: orgName,
        slug,
        ownerUid: uid,
        billingCustomerUid: uid,
        stripeSubscriptionId: null,
        seatLimit: seats,
        seatsUsed: 0,
        status: "active",
        source: "guided_invite",
        inviteToken,
        createdAt: FieldValue.serverTimestamp(),
      });
      tx.set(newOrgRef.collection("members").doc(uid), {
        uid,
        email,
        role: "admin",
        status: "active",
        keyId: null,
        joinedAt: FieldValue.serverTimestamp(),
      });
      orgId = newOrgRef.id;
    }

    tx.update(inviteRef, { usedCount: FieldValue.increment(1) });
    tx.set(redemptionRef, {
      uid,
      email,
      orgId,
      mode,
      seats,
      redeemedAt: FieldValue.serverTimestamp(),
    });

    return { orgId, orgName, seats, mode };
  });

  // Best-effort welcome email — a pointer to the dashboard, never a secret.
  if (email) {
    await sendEmail({
      to: email,
      subject:
        result.mode === "attach"
          ? `${result.seats} seats added to "${result.orgName}" on Conjur3`
          : `Your Conjur3 workspace "${result.orgName}" is ready`,
      html: emailLayout(
        result.mode === "attach" ? "Seats added" : "Welcome to Conjur3",
        `<p style="color:rgba(255,255,255,.7);font-size:14px;line-height:1.6">${
          result.mode === "attach"
            ? `<b>${result.seats}</b> seats were added to <b>${result.orgName}</b>.`
            : `Your workspace <b>${result.orgName}</b> is set up with <b>${result.seats}</b> seats and you're its admin.`
        } Invite your team from the console — each person creates their own API key from their dashboard (shown once, stored hashed, revocable any time).</p>
         <p style="margin-top:20px"><a href="${APP_URL}/dashboard" style="background:#3ee6b0;color:#0b0f14;text-decoration:none;font-weight:600;padding:12px 20px;border-radius:999px;display:inline-block">Open your dashboard →</a></p>`,
      ),
    });
  }

  return result;
});
