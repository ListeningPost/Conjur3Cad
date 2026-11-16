// Platform super-admins — operators of this deployment who can distribute /
// invalidate / remove license keys (and act as admins) regardless of org
// membership.
//
// The allowlist is deployment config, not source: set PLATFORM_ADMIN_EMAILS
// (comma-separated) in functions/.env.<projectId>. It is a security boundary.
// A caller qualifies only with a matching, VERIFIED email — otherwise anyone
// could register one of these addresses with a password and self-grant. Use
// SSO / verified email for these accounts.
//
// Firestore rules cannot read env, so the list is mirrored to
// config/platform.admins (see syncPlatformAdmins) for firestore.rules to check.
// The web client's NEXT_PUBLIC_PLATFORM_ADMIN_EMAILS is UI gating only.
import { type CallableRequest } from "firebase-functions/v2/https";
import { db } from "./admin";

export function parseAdminEmails(raw: string | undefined): string[] {
  return [
    ...new Set(
      (raw ?? "")
        .split(",")
        .map((e) => e.trim().toLowerCase())
        .filter(Boolean),
    ),
  ].sort();
}

export const PLATFORM_ADMINS = new Set<string>(
  parseAdminEmails(process.env.PLATFORM_ADMIN_EMAILS),
);

export function isPlatformAdmin(req: CallableRequest): boolean {
  const t = req.auth?.token as
    | { email?: string; email_verified?: boolean }
    | undefined;
  const email = t?.email?.toLowerCase();
  return !!email && t?.email_verified === true && PLATFORM_ADMINS.has(email);
}

/**
 * Mirror the env allowlist into config/platform so firestore.rules sees the
 * same list. Runs once per function instance; writes only when it differs.
 */
let synced: Promise<void> | null = null;
export function syncPlatformAdmins(): Promise<void> {
  synced ??= (async () => {
    const admins = [...PLATFORM_ADMINS];
    try {
      const ref = db.doc("config/platform");
      const current = (await ref.get()).data()?.admins;
      const same =
        Array.isArray(current) &&
        current.length === admins.length &&
        admins.every((e, i) => current[i] === e);
      if (!same) await ref.set({ admins });
    } catch (e) {
      synced = null; // retry on the next call
      console.error("syncPlatformAdmins failed:", e);
    }
  })();
  return synced;
}
