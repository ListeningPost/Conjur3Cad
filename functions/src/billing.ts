// onSubscriptionWrite — mirror Stripe subscription state (managed by the
// stripe/firestore-stripe-payments extension) onto the owning organization.
//
// The extension writes to customers/{uid}/subscriptions/{subId}. The customer
// uid equals the org's billingCustomerUid (the owner). We translate the
// subscription's quantity into the org's seatLimit and its Stripe status into
// our coarse org status.
import { onDocumentWritten } from "firebase-functions/v2/firestore";
import { type DocumentData } from "firebase-admin/firestore";
import { db } from "./lib/admin";

const ACTIVE_STATES = new Set(["active", "trialing"]);
const PAST_DUE_STATES = new Set(["past_due", "unpaid", "incomplete"]);

function readQuantity(data: DocumentData): number {
  if (typeof data.quantity === "number") return data.quantity;
  const items = data.items;
  if (Array.isArray(items) && items.length > 0) {
    return items.reduce(
      (sum: number, it: { quantity?: number }) => sum + (it.quantity ?? 1),
      0,
    );
  }
  return 0;
}

export const onSubscriptionWrite = onDocumentWritten(
  "customers/{uid}/subscriptions/{subId}",
  async (event) => {
    const uid = event.params.uid;
    const after = event.data?.after;
    const data = after?.exists ? after.data() : undefined;

    // Find the org this customer owns the billing for.
    const orgSnap = await db
      .collection("organizations")
      .where("billingCustomerUid", "==", uid)
      .limit(1)
      .get();
    if (orgSnap.empty) return;
    const orgRef = orgSnap.docs[0].ref;

    if (!data) {
      // Subscription deleted.
      await orgRef.update({ status: "canceled", seatLimit: 0 });
      return;
    }

    const stripeStatus = String(data.status ?? "");
    let status: string;
    if (ACTIVE_STATES.has(stripeStatus)) status = "active";
    else if (PAST_DUE_STATES.has(stripeStatus)) status = "past_due";
    else status = "canceled";

    const seatLimit = status === "active" ? readQuantity(data) : 0;

    await orgRef.update({
      status,
      seatLimit,
      stripeSubscriptionId: event.params.subId,
    });
  },
);
