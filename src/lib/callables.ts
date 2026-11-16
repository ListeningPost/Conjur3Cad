// Typed wrappers around the Conjur3 Cloud Functions callables.
import { httpsCallable } from "firebase/functions";
import { functions } from "@/firebase/config";

function callable<Req, Res>(name: string) {
  const fn = httpsCallable<Req, Res>(functions, name);
  return async (data: Req): Promise<Res> => (await fn(data)).data;
}

export const createOrganization = callable<
  { name: string },
  { orgId: string; slug: string }
>("createOrganization");

// ---- Self-service API keys (per member, per org) --------------------------
// The plaintext `code` in these responses is shown ONCE and never retrievable
// again — the server keeps only a hash.
export const claimMyKey = callable<
  { orgId: string },
  { code: string; keyId: string; prefix: string; last4: string; orgId: string; orgName: string }
>("claimMyKey");

export const rotateMyKey = callable<
  { orgId: string },
  { code: string; keyId: string; prefix: string; last4: string; orgId: string }
>("rotateMyKey");

export const revokeMyKey = callable<
  { orgId: string },
  { keyId: string; orgId: string; revoked: boolean }
>("revokeMyKey");

export const deleteMyKey = callable<
  { orgId: string },
  { keyId: string; orgId: string; deleted: boolean }
>("deleteMyKey");

// Admin: invalidate/remove any key in the org.
export const revokeKey = callable<
  { orgId: string; keyId: string; remove?: boolean },
  { keyId: string; orgId: string; removed: boolean; ownerUid: string | null }
>("revokeKey");

// ---- Members ---------------------------------------------------------------
export const setMemberRole = callable<
  { orgId: string; uid: string; role: "admin" | "user" },
  { uid: string; role: string }
>("setMemberRole");

export const revokeMember = callable<
  { orgId: string; uid: string },
  { uid: string; revoked: boolean }
>("revokeMember");

export const inviteMember = callable<
  { orgId: string; email: string },
  { token: string; url: string; email: string; emailed: boolean }
>("inviteMember");

export const deleteSelf = callable<
  Record<string, never>,
  { deleted: boolean; orgsDeleted: number; orgsLeft: number }
>("deleteSelf");

// ---- Org join invites (admin-created links) --------------------------------
export const createOrgInvite = callable<
  { orgId: string; label?: string; maxUses?: number; expiresAtMs?: number },
  { token: string; url: string }
>("createOrgInvite");

export const revokeOrgInvite = callable<
  { token: string; remove?: boolean },
  { token: string; removed: boolean }
>("revokeOrgInvite");

export const getOrgInvite = callable<
  { token: string },
  {
    valid: boolean;
    reason?: string | null;
    orgName?: string | null;
    label?: string | null;
  }
>("getOrgInvite");

export const redeemOrgInvite = callable<
  { token: string },
  { orgId: string; orgName: string; alreadyMember: boolean }
>("redeemOrgInvite");

// ---- Guided sign-up invites (platform seat vouchers) ------------------------
export const createGuidedInvite = callable<
  { label?: string; maxSignups: number; seats?: number; expiresAtMs: number },
  { id: string; token: string; url: string }
>("createGuidedInvite");

export const disableGuidedInvite = callable<
  { id: string; remove?: boolean },
  { id: string; removed: boolean }
>("disableGuidedInvite");

export const getGuidedInvite = callable<
  { token: string },
  {
    valid: boolean;
    reason?: string | null;
    label?: string | null;
    seats?: number;
    remaining?: number;
    expiresAtMs?: number;
  }
>("getGuidedInvite");

export const redeemGuidedInvite = callable<
  { token: string; mode: "create" | "attach"; orgName?: string; orgId?: string },
  { orgId: string; orgName: string; seats: number; mode: "create" | "attach" }
>("redeemGuidedInvite");

// ---- Platform --------------------------------------------------------------
export const grantSeats = callable<
  { orgId: string; seats: number },
  { orgId: string; granted: number; seatLimit: number }
>("grantSeats");

// Emulator-only seat seeding (no live Stripe required).
export const devSeedSubscription = callable<
  { orgId: string; seats: number },
  { orgId: string; seatLimit: number }
>("devSeedSubscription");

/** Normalize a Firebase callable error into a human string. */
export function callableError(e: unknown): string {
  if (e && typeof e === "object" && "message" in e) {
    return String((e as { message: unknown }).message);
  }
  return "Something went wrong. Please try again.";
}
