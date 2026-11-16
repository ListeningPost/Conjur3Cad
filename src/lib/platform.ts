// Platform super-admins (operators of this deployment) — UI gating only. The
// authoritative checks live server-side: functions/src/lib/platform.ts (which
// also requires a verified email) and firestore.rules. Set
// NEXT_PUBLIC_PLATFORM_ADMIN_EMAILS (comma-separated) to the same list as the
// functions' PLATFORM_ADMIN_EMAILS.
export const PLATFORM_ADMINS = (
  process.env.NEXT_PUBLIC_PLATFORM_ADMIN_EMAILS ?? ""
)
  .split(",")
  .map((e) => e.trim().toLowerCase())
  .filter(Boolean);

export function isPlatformAdmin(email?: string | null): boolean {
  return !!email && PLATFORM_ADMINS.includes(email.toLowerCase());
}
