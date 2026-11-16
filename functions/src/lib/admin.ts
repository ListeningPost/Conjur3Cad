// Shared Firebase Admin SDK singletons and domain types for Conjur3 functions.
import { initializeApp, getApps, getApp } from "firebase-admin/app";
import { getFirestore } from "firebase-admin/firestore";
import { getAuth } from "firebase-admin/auth";

const app = getApps().length === 0 ? initializeApp() : getApp();

export const db = getFirestore(app);
export const auth = getAuth(app);

/**
 * Org access tiers. Just two: `admin` (can manage the org, its members, keys,
 * and invites) and `user` (a regular seat holder). The org's billing owner is
 * tracked separately via `organizations/{id}.ownerUid` — the owner is an admin
 * who additionally cannot be demoted or removed.
 */
export type Role = "admin" | "user";

export const ROLE_RANK: Record<Role, number> = {
  admin: 2,
  user: 1,
};

/**
 * Normalize any historical role value to the two-tier model. Earlier data used
 * owner/admin/member; owner→admin, member→user. Safe to call on already-current
 * values.
 */
export function normalizeRole(role: unknown): Role {
  return role === "admin" || role === "owner" ? "admin" : "user";
}

/** Custom claims attached to a user's ID token. */
export interface Claims {
  role: Role;
  orgId: string;
}

/** True when running against the local emulator suite. */
export const isEmulator = process.env.FUNCTIONS_EMULATOR === "true";
