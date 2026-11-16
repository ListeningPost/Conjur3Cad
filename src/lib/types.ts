// Shared client-side Firestore document shapes.
//
// Two access tiers only: `admin` and `user`. The org's billing owner is tracked
// via Organization.ownerUid (an admin who can't be demoted/removed).
// Multi-org: a user may belong to any number of organizations; each membership
// is organizations/{orgId}/members/{uid}.
export type Role = "admin" | "user";
export type OrgStatus = "inactive" | "active" | "past_due" | "canceled";
export type KeyStatus = "active" | "revoked";

/** Map any historical role (owner/admin/member) to the two-tier model. */
export function normalizeRole(role: unknown): Role {
  return role === "admin" || role === "owner" ? "admin" : "user";
}

export interface Organization {
  id: string;
  name: string;
  slug: string;
  ownerUid: string;
  billingCustomerUid: string;
  stripeSubscriptionId: string | null;
  seatLimit: number;
  seatsUsed: number;
  status: OrgStatus;
}

/** One of the caller's org memberships (from the collection-group query). */
export interface Membership {
  orgId: string;
  role: Role;
}

export interface Member {
  uid: string;
  email: string | null;
  role: Role;
  status: string;
  keyId: string | null;
}

/**
 * An API key's metadata. The plaintext code is NEVER stored — only its hash
 * (not readable by clients in any useful way) and a display stub.
 */
export interface ApiKey {
  id: string;
  prefix: string;
  last4: string;
  status: KeyStatus;
  ownerUid: string;
  ownerEmail: string | null;
  createdAt?: { toMillis(): number } | null;
  rotatedAt?: { toMillis(): number } | null;
}

/** Platform seat voucher: each redemption grants `seats` seats. */
export interface GuidedInvite {
  id: string;
  token: string;
  label: string | null;
  maxSignups: number;
  usedCount: number;
  seats: number;
  expiresAt: { toMillis(): number } | null;
  status: "active" | "disabled";
  createdByEmail: string | null;
}

/** Org join link created by an org admin. */
export interface OrgInvite {
  id: string;
  token: string;
  orgId: string;
  orgName: string;
  label: string | null;
  invitedEmail: string | null;
  maxUses: number;
  usedCount: number;
  expiresAt: { toMillis(): number } | null;
  status: "active" | "disabled";
  createdByEmail: string | null;
  createdAt?: { toMillis(): number } | null;
}
