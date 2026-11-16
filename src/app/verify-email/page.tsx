"use client";
import { useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { auth } from "@/firebase/config";
import { useAuthContext } from "@/context/AuthContext";
import sendVerification from "@/firebase/auth/verify";
import { AuthShell } from "@/components/AuthShell";
import { Button } from "@/components/Button";
import { Alert, Spinner } from "@/components/ui";

const RESEND_COOLDOWN = 30; // seconds
const POLL_INTERVAL = 3000; // ms

export default function VerifyEmailPage() {
  const { user, emailVerified, loading, reloadUser, logout } = useAuthContext();
  const router = useRouter();
  const searchParams = useSearchParams();
  const redirect = searchParams.get("redirect") ?? "/dashboard";

  const [cooldown, setCooldown] = useState(0);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [checking, setChecking] = useState(false);

  // Route guard: not signed in → /signin; already verified → redirect target.
  useEffect(() => {
    if (loading) return;
    if (!user) router.replace("/signin");
    else if (emailVerified) router.replace(redirect);
  }, [loading, user, emailVerified, router, redirect]);

  // Auto-detect verification: the user clicks the link in their inbox (often a
  // different tab/device), so poll and re-check on tab focus.
  useEffect(() => {
    if (!user || emailVerified) return;
    const id = setInterval(() => {
      void reloadUser();
    }, POLL_INTERVAL);
    const onFocus = () => void reloadUser();
    window.addEventListener("focus", onFocus);
    return () => {
      clearInterval(id);
      window.removeEventListener("focus", onFocus);
    };
  }, [user, emailVerified, reloadUser]);

  // Resend cooldown ticker.
  useEffect(() => {
    if (cooldown <= 0) return;
    const id = setTimeout(() => setCooldown((c) => c - 1), 1000);
    return () => clearTimeout(id);
  }, [cooldown]);

  const handleResend = useCallback(async () => {
    if (!user || cooldown > 0) return;
    setError("");
    setNotice("");
    const { error: sendErr } = await sendVerification(user);
    if (sendErr) {
      setError("Couldn't send the email just now — try again in a moment.");
      return;
    }
    setNotice("Verification email sent. Check your inbox (and spam folder).");
    setCooldown(RESEND_COOLDOWN);
  }, [user, cooldown]);

  const handleCheck = useCallback(async () => {
    setChecking(true);
    setError("");
    setNotice("");
    await reloadUser();
    setChecking(false);
    // Read the live flag straight off the SDK — context state updates async.
    if (auth.currentUser?.emailVerified) {
      router.replace(redirect);
    } else {
      setError("Not verified yet — click the link in your email, then check again.");
    }
  }, [reloadUser, router, redirect]);

  // While auth resolves or we're about to redirect, show a spinner.
  if (loading || !user || emailVerified) {
    return (
      <AuthShell title="Verify your email">
        <div className="flex justify-center py-4">
          <Spinner label="Loading" />
        </div>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      kicker="One more step"
      title="Verify your email"
      subtitle="We need to confirm your address before you can access Conjur3."
      footer={
        <>
          Wrong account?{" "}
          <button
            onClick={() => logout()}
            className="text-mint hover:underline"
          >
            Sign out
          </button>
        </>
      }
    >
      <div className="space-y-4">
        <p className="text-sm text-white/70">
          We sent a verification link to{" "}
          <span className="text-paper">{user.email}</span>. Open it to activate
          your account — this page continues automatically once you do.
        </p>

        {notice ? <Alert tone="success">{notice}</Alert> : null}
        {error ? <Alert>{error}</Alert> : null}

        <Button onClick={handleCheck} disabled={checking} className="w-full">
          {checking ? "Checking…" : "I've verified — continue →"}
        </Button>

        <Button
          variant="outline"
          onClick={handleResend}
          disabled={cooldown > 0}
          className="w-full"
        >
          {cooldown > 0 ? `Resend in ${cooldown}s` : "Resend email"}
        </Button>
      </div>
    </AuthShell>
  );
}
