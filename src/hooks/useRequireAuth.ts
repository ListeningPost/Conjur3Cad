"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuthContext, type Role } from "@/context/AuthContext";

/**
 * Client-side route guard (multi-org).
 *  - Unauthenticated users are sent to /signin.
 *  - Signed-in but unverified users are sent to /verify-email (unless
 *    `allowUnverified` is set — used by the verify-email page itself).
 *  - `minRole: "admin"` requires being an admin of AT LEAST ONE org (pages
 *    then scope to a chosen org); platform admins always qualify.
 *
 * Returns { ready } — true once the user is confirmed allowed to view the page.
 */
export function useRequireAuth(opts: {
  minRole?: Role;
  fallback?: string;
  allowUnverified?: boolean;
} = {}) {
  const { minRole, fallback = "/dashboard", allowUnverified = false } = opts;
  const {
    user,
    memberships,
    membershipsLoading,
    platformAdmin,
    emailVerified,
    loading,
  } = useAuthContext();
  const router = useRouter();

  const verifiedOk = allowUnverified || emailVerified;
  const isAdminSomewhere = memberships.some((m) => m.role === "admin");
  // Platform super-admins satisfy any role requirement.
  const roleOk =
    !minRole ||
    platformAdmin ||
    (minRole === "admin" ? isAdminSomewhere : memberships.length > 0);
  const settled = !loading && (!minRole || !membershipsLoading);
  const allowed = !!user && verifiedOk && roleOk;

  useEffect(() => {
    if (!settled) return;
    if (!user) {
      router.replace("/signin");
    } else if (!verifiedOk) {
      router.replace("/verify-email");
    } else if (!roleOk) {
      router.replace(fallback);
    }
  }, [settled, user, verifiedOk, roleOk, fallback, router]);

  return { ready: settled && allowed, user };
}
