// revokeKey — an ADMIN invalidates (status="revoked") or removes (delete) any
// key in their org. The owner stays a member (they can claim a fresh key if
// seats allow); an active key being killed frees its seat. Org admins act on
// their org; platform super-admins on any org.
import { onCall, HttpsError } from "firebase-functions/v2/https";
import { FieldValue } from "firebase-admin/firestore";
import { db } from "./lib/admin";
import { requireOrgAdminOrPlatform, requireOrgId } from "./lib/authz";

export const revokeKey = onCall(async (req) => {
  const orgId = requireOrgId(req);
  await requireOrgAdminOrPlatform(req, orgId);

  const keyId = String(req.data?.keyId ?? "");
  const remove = req.data?.remove === true;
  if (!keyId) throw new HttpsError("invalid-argument", "keyId required.");

  const orgRef = db.collection("organizations").doc(orgId);
  const keyRef = orgRef.collection("keys").doc(keyId);

  const ownerUid = await db.runTransaction(async (tx) => {
    const key = await tx.get(keyRef);
    if (!key.exists) throw new HttpsError("not-found", "Key not found.");
    const owner = (key.get("ownerUid") as string) ?? null;
    const wasActive = key.get("status") === "active";

    // Read before any write (transaction ordering): does the owner's member
    // doc still exist? (They may have left the org already.)
    const memberRef = owner ? orgRef.collection("members").doc(owner) : null;
    const memberDoc = memberRef ? await tx.get(memberRef) : null;

    if (wasActive) {
      tx.update(orgRef, { seatsUsed: FieldValue.increment(-1) });
    }
    if (remove) {
      tx.delete(keyRef);
      if (memberRef && memberDoc?.exists && memberDoc.get("keyId") === keyId) {
        // Detach the pointer so the owner can claim a fresh key.
        tx.update(memberRef, { keyId: null });
      }
    } else {
      tx.update(keyRef, {
        status: "revoked",
        revokedAt: FieldValue.serverTimestamp(),
      });
    }
    return owner;
  });

  return { keyId, orgId, removed: remove, ownerUid };
});
