// devSeedSubscription — EMULATOR ONLY. Simulates a successful seat purchase so
// the full org → seats → claim flow can be exercised without live Stripe.
// Writes a fake subscription doc (driving onSubscriptionWrite) AND updates the
// org directly for determinism.
import { onCall, HttpsError } from "firebase-functions/v2/https";
import { FieldValue } from "firebase-admin/firestore";
import { db, isEmulator } from "./lib/admin";
import { requireOrgId, requireOrgRole } from "./lib/authz";

export const devSeedSubscription = onCall(async (req) => {
  if (!isEmulator) {
    throw new HttpsError("permission-denied", "Emulator only.");
  }
  const orgId = requireOrgId(req);
  const { uid } = await requireOrgRole(req, orgId, "admin");

  const seats = Math.floor(Number(req.data?.seats ?? 5));
  if (!Number.isFinite(seats) || seats < 1 || seats > 1000) {
    throw new HttpsError("invalid-argument", "seats must be 1..1000.");
  }

  // Fake subscription doc as the Stripe extension would write it.
  await db
    .collection("customers")
    .doc(uid)
    .collection("subscriptions")
    .doc("sub_dev_seed")
    .set({
      status: "active",
      quantity: seats,
      items: [{ quantity: seats, price: { id: "price_seat_dev" } }],
      created: FieldValue.serverTimestamp(),
    });

  // Direct update too (the trigger may lag in the emulator).
  await db.collection("organizations").doc(orgId).update({
    status: "active",
    seatLimit: seats,
    stripeSubscriptionId: "sub_dev_seed",
  });

  return { orgId, seatLimit: seats };
});
