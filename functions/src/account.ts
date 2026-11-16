// deleteSelf — a user permanently deletes their own account.
//
// Multi-org aware: every membership is unwound.
//  - Org they OWN:        the organization is erased entirely (members, keys,
//                         invites pointing at it stay orphaned-but-dead; other
//                         members keep their accounts and other orgs).
//  - Org they're a member: their key is deleted (freeing the seat if active)
//                         and the membership removed.
// Then the profile doc and the Auth user are deleted.
import { onCall } from "firebase-functions/v2/https";
import { FieldValue } from "firebase-admin/firestore";
import { db, auth } from "./lib/admin";
import { requireAuth } from "./lib/authz";

export const deleteSelf = onCall(async (req) => {
  const uid = requireAuth(req);

  const memberships = await db
    .collectionGroup("members")
    .where("uid", "==", uid)
    .get();

  let orgsDeleted = 0;
  let orgsLeft = 0;

  for (const memberDoc of memberships.docs) {
    const orgRef = memberDoc.ref.parent.parent;
    if (!orgRef) continue;
    const orgSnap = await orgRef.get();
    if (!orgSnap.exists) {
      await memberDoc.ref.delete().catch(() => {});
      continue;
    }

    if (orgSnap.get("ownerUid") === uid) {
      // Owner → erase the org (members + keys subcollections and the doc).
      await db.recursiveDelete(orgRef);
      orgsDeleted++;
    } else {
      // Member → drop their key (freeing the seat if active) and leave.
      await db.runTransaction(async (tx) => {
        const m = await tx.get(memberDoc.ref);
        if (!m.exists) return;
        const keyId = m.get("keyId") as string | null;
        const keyDoc = keyId
          ? await tx.get(orgRef.collection("keys").doc(keyId))
          : null;
        if (keyDoc?.exists) {
          if (keyDoc.get("status") === "active") {
            tx.update(orgRef, { seatsUsed: FieldValue.increment(-1) });
          }
          tx.delete(keyDoc.ref);
        }
        tx.delete(m.ref);
      });
      orgsLeft++;
    }
  }

  // Remove the caller's own profile doc, then their Auth account.
  await db.collection("users").doc(uid).delete().catch(() => {});
  await auth.deleteUser(uid);

  return { deleted: true, orgsDeleted, orgsLeft };
});
