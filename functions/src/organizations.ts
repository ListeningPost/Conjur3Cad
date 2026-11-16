// createOrganization — turns the caller into the owner of a fresh org.
// grantSeats — platform super-admins top up any org's seat allotment.
//
// Multi-org: a user may create/belong to any number of organizations.
import { onCall, HttpsError } from "firebase-functions/v2/https";
import { FieldValue } from "firebase-admin/firestore";
import { db } from "./lib/admin";
import { requireAuth, requireVerified, requireOrgId } from "./lib/authz";
import { isPlatformAdmin } from "./lib/platform";

function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 32);
}

export const createOrganization = onCall(async (req) => {
  const { uid, email } = requireVerified(req);

  const name = String(req.data?.name ?? "").trim();
  if (name.length < 2 || name.length > 80) {
    throw new HttpsError("invalid-argument", "Organization name is required.");
  }

  const orgRef = db.collection("organizations").doc();
  const slug = `${slugify(name) || "org"}-${orgRef.id.slice(0, 5).toLowerCase()}`;

  const batch = db.batch();
  batch.set(orgRef, {
    name,
    slug,
    ownerUid: uid,
    billingCustomerUid: uid, // owner is the Stripe customer
    stripeSubscriptionId: null,
    seatLimit: 0, // raised by subscription, voucher, or platform grant
    seatsUsed: 0,
    status: "inactive", // inactive | active | past_due | canceled
    createdAt: FieldValue.serverTimestamp(),
  });
  batch.set(orgRef.collection("members").doc(uid), {
    uid,
    email,
    role: "admin", // creator is an admin; ownerUid marks them as billing owner
    status: "active",
    keyId: null,
    joinedAt: FieldValue.serverTimestamp(),
  });
  batch.set(
    db.collection("users").doc(uid),
    { email, updatedAt: FieldValue.serverTimestamp() },
    { merge: true },
  );
  await batch.commit();

  return { orgId: orgRef.id, slug };
});

/** Add seats to (or activate) any org. Platform super-admins only. */
export const grantSeats = onCall(async (req) => {
  requireAuth(req);
  if (!isPlatformAdmin(req)) {
    throw new HttpsError("permission-denied", "Platform admins only.");
  }
  const orgId = requireOrgId(req);
  const seats = Math.floor(Number(req.data?.seats ?? 0));
  if (!Number.isFinite(seats) || seats < 1 || seats > 1000) {
    throw new HttpsError("invalid-argument", "seats must be 1..1000.");
  }

  const orgRef = db.collection("organizations").doc(orgId);
  const seatLimit = await db.runTransaction(async (tx) => {
    const orgDoc = await tx.get(orgRef);
    if (!orgDoc.exists) throw new HttpsError("not-found", "Organization missing.");
    tx.update(orgRef, {
      seatLimit: FieldValue.increment(seats),
      ...(orgDoc.get("status") === "inactive" ? { status: "active" } : {}),
    });
    return ((orgDoc.get("seatLimit") as number) ?? 0) + seats;
  });

  return { orgId, granted: seats, seatLimit };
});
