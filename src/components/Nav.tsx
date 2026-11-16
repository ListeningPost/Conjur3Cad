"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuthContext } from "@/context/AuthContext";
import { useFlags } from "@/hooks/useFlags";
import { Logo } from "@/components/Logo";
import { buttonClasses } from "@/components/Button";
import { GitHubNavLink } from "@/components/GitHubLink";

/**
 * Top navigation. Auth-aware: shows app links + sign-out when signed in,
 * sign-in / get-access CTAs otherwise.
 */
export function Nav() {
  const { user, memberships, platformAdmin, logout } = useAuthContext();
  const { stripeEnabled } = useFlags();
  const router = useRouter();
  const adminSomewhere = memberships.some((m) => m.role === "admin");
  const isAdmin = adminSomewhere || platformAdmin;

  const link = "font-mono text-xs uppercase tracking-wider text-white/70 hover:text-paper transition-colors";

  async function handleLogout() {
    await logout();
    router.push("/");
  }

  return (
    <header className="sticky top-0 z-40 border-b border-white/10 bg-ink/80 backdrop-blur">
      <nav className="mx-auto flex h-16 max-w-6xl items-center justify-between px-5">
        <Logo />
        <div className="flex items-center gap-5">
          <GitHubNavLink />
          {user ? (
            <>
              <Link href="/dashboard" className={link}>
                Dashboard
              </Link>
              {isAdmin && (
                <Link href="/admin" className={link}>
                  Team
                </Link>
              )}
              {platformAdmin && (
                <Link href="/platform" className={link}>
                  Platform
                </Link>
              )}
              {adminSomewhere && stripeEnabled && (
                <Link href="/billing" className={link}>
                  Billing
                </Link>
              )}
              <Link href="/account" className={link}>
                Account
              </Link>
              <button onClick={handleLogout} className={link}>
                Sign out
              </button>
            </>
          ) : (
            <>
              <Link href="/signin" className={link}>
                Sign in
              </Link>
              <Link href="/signup" className={buttonClasses("primary", "sm")}>
                Get access →
              </Link>
            </>
          )}
        </div>
      </nav>
    </header>
  );
}
