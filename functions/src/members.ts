// Org member management — invite (by email → join link), promote/demote, and
// remove.
//
// Two tiers only: `admin` and `user`. Any admin (or a platform super-admin) may
// manage members. The org's billing owner (organizations/{id}.ownerUid) is
// protected: they're always an admin and can't be demoted or removed.
import { onCall, HttpsError } from "firebase-functions/v2/https";
import { FieldValue } from "firebase-admin/firestore";
import { db, type Role } from "./lib/admin";
import { requireOrgAdminOrPlatform, requireOrgId } from "./lib/authz";
import { createOrgInviteDoc } from "./orgInvites";
import { sendEmail, emailLayout } from "./lib/email";

/** Change a member's tier between `admin` and `user`. */
export const setMemberRole = onCall(async (req) => {
  const orgId = requireOrgId(req);
  await requireOrgAdminOrPlatform(req, orgId);

  const targetUid = String(req.data?.uid ?? "");
  const role = String(req.data?.role ?? "") as Role;
  if (!targetUid) throw new HttpsError("invalid-argument", "uid required.");
  if (role !== "admin" && role !== "user") {
    throw new HttpsError("invalid-argument", "role must be admin or user.");
  }

  const orgRef = db.collection("organizations").doc(orgId);
  const memberRef = orgRef.collection("members").doc(targetUid);
  const [orgDoc, member] = await Promise.all([orgRef.get(), memberRef.get()]);
  if (!member.exists) throw new HttpsError("not-found", "Member not found.");
  if (orgDoc.get("ownerUid") === targetUid) {
    throw new HttpsError("failed-precondition", "The org owner is always an admin.");
  }

  await memberRef.update({ role });
  return { uid: targetUid, role };
});

/**
 * Remove a member from the org. Their key (if any) is deleted and, when it was
 * active, the seat is freed. Their account and other org memberships survive.
 */
export const revokeMember = onCall(async (req) => {
  const orgId = requireOrgId(req);
  const { uid: callerUid } = await requireOrgAdminOrPlatform(req, orgId);

  const targetUid = String(req.data?.uid ?? "");
  if (!targetUid) throw new HttpsError("invalid-argument", "uid required.");
  if (targetUid === callerUid) {
    throw new HttpsError("failed-precondition", "You cannot remove yourself.");
  }

  const orgRef = db.collection("organizations").doc(orgId);
  const memberRef = orgRef.collection("members").doc(targetUid);

  await db.runTransaction(async (tx) => {
    const [orgDoc, member] = await Promise.all([
      tx.get(orgRef),
      tx.get(memberRef),
    ]);
    if (!member.exists) throw new HttpsError("not-found", "Member not found.");
    if (orgDoc.get("ownerUid") === targetUid) {
      throw new HttpsError("failed-precondition", "Cannot remove the org owner.");
    }

    const keyId = member.get("keyId") as string | null;
    const keyDoc = keyId
      ? await tx.get(orgRef.collection("keys").doc(keyId))
      : null;

    if (keyDoc?.exists) {
      if (keyDoc.get("status") === "active") {
        tx.update(orgRef, { seatsUsed: FieldValue.increment(-1) });
      }
      tx.delete(keyDoc.ref);
    }
    tx.delete(memberRef);
  });

  return { uid: targetUid, revoked: true };
});

/**
 * Invite a person into THIS org by email: creates a single-use join link tied
 * to their address and emails it. No key code is ever sent — once they join,
 * they mint their own key from the dashboard.
 */
export const inviteMember = onCall(async (req) => {
  const orgId = requireOrgId(req);
  const { uid } = await requireOrgAdminOrPlatform(req, orgId);

  const email = String(req.data?.email ?? "").trim().toLowerCase();
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    throw new HttpsError("invalid-argument", "A valid email is required.");
  }

  const orgDoc = await db.collection("organizations").doc(orgId).get();
  if (!orgDoc.exists) throw new HttpsError("not-found", "Organization missing.");
  const orgName = (orgDoc.get("name") as string) ?? "your team";

  const { token, url } = await createOrgInviteDoc({
    orgId,
    orgName,
    createdByUid: uid,
    createdByEmail: (req.auth?.token.email as string | undefined) ?? null,
    label: `Email invite · ${email}`,
    invitedEmail: email,
    maxUses: 1,
  });

  const sent = await sendEmail({
    to: email,
    subject: `You've been invited to ${orgName} on Conjur3`,
    html: emailLayout(
      `Join ${orgName} on Conjur3`,
      `<p style="color:rgba(255,255,255,.7);font-size:14px;line-height:1.6">You've been invited to join <b>${orgName}</b>. Open the link below, sign in or create your account, and you're in. You'll then create your own API key from your dashboard — it's shown to you once and to no one else.</p>
       <p style="margin-top:20px"><a href="${url}" style="background:#3ee6b0;color:#0b0f14;text-decoration:none;font-weight:600;padding:12px 20px;border-radius:999px;display:inline-block">Join ${orgName} →</a></p>
       <p style="color:rgba(255,255,255,.45);font-size:12px;margin-top:16px">This link is for ${email} and can only be used once. If it expires, ask your admin for a new one.</p>`,
    ),
  });

  return { token, url, email, emailed: sent.ok };
});
