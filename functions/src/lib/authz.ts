// Authorization helpers — membership-based (multi-org).
//
// A user may belong to any number of organizations. The source of truth for
// membership/role is the Firestore doc organizations/{orgId}/members/{uid};
// custom claims are NOT used (no setCustomUserClaims anywhere — one less prod
// IAM dependency, and roles take effect without a token refresh).
import { HttpsError, type CallableRequest } from "firebase-functions/v2/https";
import { db, normalizeRole, ROLE_RANK, type Role } from "./admin";
import { isPlatformAdmin } from "./platform";

/** Assert the request is authenticated and return its uid. */
export function requireAuth(req: CallableRequest): string {
  if (!req.auth?.uid) {
    throw new HttpsError("unauthenticated", "You must be signed in.");
  }
  return req.auth.uid;
}

/** Assert a signed-in, email-verified caller. Returns uid + email. */
export function requireVerified(req: CallableRequest): {
  uid: string;
  email: string | null;
} {
  const uid = requireAuth(req);
  const t = req.auth!.token as { email?: string; email_verified?: boolean };
  if (t.email_verified !== true) {
    throw new HttpsError("failed-precondition", "Please verify your email first.");
  }
  return { uid, email: t.email ?? null };
}

/** Read `orgId` off the request payload (required in the multi-org model). */
export function requireOrgId(req: CallableRequest): string {
  const data = (req as { data?: { orgId?: unknown } }).data;
  const orgId = typeof data?.orgId === "string" ? data.orgId : "";
  if (!orgId) throw new HttpsError("invalid-argument", "orgId required.");
  return orgId;
}

/** The caller's membership in `orgId`, or null when they're not a member. */
export async function getMembership(
  orgId: string,
  uid: string,
): Promise<{ role: Role } | null> {
  const snap = await db
    .collection("organizations")
    .doc(orgId)
    .collection("members")
    .doc(uid)
    .get();
  if (!snap.exists) return null;
  return { role: normalizeRole(snap.get("role")) };
}

/**
 * Assert the caller belongs to `orgId` with at least `minRole`.
 * Returns the caller's uid and role.
 */
export async function requireOrgRole(
  req: CallableRequest,
  orgId: string,
  minRole: Role,
): Promise<{ uid: string; role: Role }> {
  const uid = requireAuth(req);
  const membership = await getMembership(orgId, uid);
  if (!membership) {
    throw new HttpsError("permission-denied", "Not a member of this org.");
  }
  if (ROLE_RANK[membership.role] < ROLE_RANK[minRole]) {
    throw new HttpsError("permission-denied", `Requires ${minRole} privileges.`);
  }
  return { uid, role: membership.role };
}

/**
 * Authorize an admin-level action on `orgId`: org admin OR a Conjur3 platform
 * super-admin (who may act on any org). Returns the caller's uid and whether
 * they're acting as a platform admin.
 */
export async function requireOrgAdminOrPlatform(
  req: CallableRequest,
  orgId: string,
): Promise<{ uid: string; platform: boolean }> {
  const uid = requireAuth(req);
  if (isPlatformAdmin(req)) return { uid, platform: true };
  await requireOrgRole(req, orgId, "admin");
  return { uid, platform: false };
}
