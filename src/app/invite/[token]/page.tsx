"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { doc, serverTimestamp, setDoc } from "firebase/firestore";
import signUp from "@/firebase/auth/signup";
import sendVerification from "@/firebase/auth/verify";
import { auth, db } from "@/firebase/config";
import { useAuthContext } from "@/context/AuthContext";
import { getOrgInvite, redeemOrgInvite, callableError } from "@/lib/callables";
import { AuthShell } from "@/components/AuthShell";
import { Button, ButtonLink } from "@/components/Button";
import { Field, Alert, Spinner } from "@/components/ui";

interface InviteInfo {
  valid: boolean;
  reason?: string | null;
  orgName?: string | null;
  label?: string | null;
}

const INVALID_MSG: Record<string, string> = {
  missing: "This invite link is incomplete.",
  not_found: "This invite link is invalid.",
  expired: "This invite has expired — ask your admin for a new one.",
  exhausted: "This invite has reached its use limit — ask your admin for a new one.",
  disabled: "This invite is no longer active.",
  error: "We couldn't check this invite. Try again later.",
};

/**
 * Org join invite: redeeming makes the visitor a member of the org. No key is
 * created here — they claim their own from the dashboard afterwards.
 */
export default function OrgInvitePage() {
  const params = useParams<{ token: string }>();
  const token = String(params?.token ?? "");
  const { user, emailVerified, loading, reloadUser } = useAuthContext();

  const [invite, setInvite] = useState<InviteInfo | null>(null);
  const [checkingInvite, setCheckingInvite] = useState(true);

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [cooldown, setCooldown] = useState(0);

  const [joined, setJoined] = useState<{ orgName: string; alreadyMember: boolean } | null>(null);
  const redeeming = useRef(false);

  // Validate the invite (public, pre-signup).
  useEffect(() => {
    let active = true;
    (async () => {
      if (!token) {
        setInvite({ valid: false, reason: "missing" });
        setCheckingInvite(false);
        return;
      }
      try {
        const res = await getOrgInvite({ token });
        if (active) setInvite(res);
      } catch {
        if (active) setInvite({ valid: false, reason: "error" });
      } finally {
        if (active) setCheckingInvite(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [token]);

  // Poll for email verification (link is clicked elsewhere).
  useEffect(() => {
    if (!user || emailVerified) return;
    const id = setInterval(() => void reloadUser(), 3000);
    const onFocus = () => void reloadUser();
    window.addEventListener("focus", onFocus);
    return () => {
      clearInterval(id);
      window.removeEventListener("focus", onFocus);
    };
  }, [user, emailVerified, reloadUser]);

  // Resend cooldown.
  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setTimeout(() => setCooldown((c) => c - 1), 1000);
    return () => clearTimeout(t);
  }, [cooldown]);

  const doRedeem = useCallback(async () => {
    if (redeeming.current) return;
    redeeming.current = true;
    setError("");
    try {
      // Ensure the ID token carries the verified-email claim before redeeming.
      await auth.currentUser?.getIdToken(true);
      const res = await redeemOrgInvite({ token });
      setJoined({ orgName: res.orgName, alreadyMember: res.alreadyMember });
    } catch (err) {
      setError(callableError(err));
      redeeming.current = false; // allow retry
    }
  }, [token]);

  // Auto-redeem once verified and signed in (joining is idempotent — if
  // they're already a member the server just says so).
  useEffect(() => {
    if (loading) return;
    if (user && emailVerified && !joined && invite?.valid) {
      void doRedeem();
    }
  }, [loading, user, emailVerified, joined, invite, doRedeem]);

  async function handleSignup(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (password.length < 6) {
      setError("Password must be at least 6 characters.");
      return;
    }
    setBusy(true);
    const { result, error: signupErr } = await signUp(email, password);
    if (signupErr || !result) {
      setError(
        String((signupErr as { code?: string })?.code ?? "").includes("in-use")
          ? "That email is already registered — sign in instead."
          : "Could not create your account.",
      );
      setBusy(false);
      return;
    }
    try {
      await setDoc(
        doc(db, "users", result.user.uid),
        { email, createdAt: serverTimestamp() },
        { merge: true },
      );
    } catch {
      /* non-fatal */
    }
    await sendVerification(result.user);
    setBusy(false);
    // Re-renders into the verify step (user is now signed in, unverified).
  }

  async function handleResend() {
    if (!user || cooldown > 0) return;
    setError("");
    setNotice("");
    const { error: sendErr } = await sendVerification(user);
    if (sendErr) {
      setError("Couldn't send the email just now — try again shortly.");
      return;
    }
    setNotice("Verification email sent. Check your inbox (and spam).");
    setCooldown(30);
  }

  // ---- Render states ------------------------------------------------------

  if (checkingInvite || loading) {
    return (
      <AuthShell title="Joining a team">
        <div className="flex justify-center py-4">
          <Spinner label="Loading" />
        </div>
      </AuthShell>
    );
  }

  if (!invite?.valid && !joined) {
    return (
      <AuthShell
        kicker="Invitation"
        title="This invite can't be used"
        footer={
          <>
            Want to start your own?{" "}
            <Link href="/signup" className="text-mint hover:underline">
              Sign up
            </Link>
          </>
        }
      >
        <Alert>{INVALID_MSG[invite?.reason ?? "error"] ?? INVALID_MSG.error}</Alert>
      </AuthShell>
    );
  }

  const orgName = invite?.orgName ?? "the team";

  if (joined) {
    return (
      <AuthShell
        kicker={joined.alreadyMember ? "Already a member" : "You're in"}
        title={`Welcome to ${joined.orgName}`}
        subtitle="One more step: claim your personal API key from your dashboard."
      >
        <div className="space-y-4">
          <Alert tone="info">
            Your key is created by you, shown to you once, and revocable by you —
            nobody else ever sees it.
          </Alert>
          <ButtonLink href="/dashboard" className="w-full">
            Claim your key →
          </ButtonLink>
        </div>
      </AuthShell>
    );
  }

  // Verified, signed-in → joining.
  if (user && emailVerified) {
    return (
      <AuthShell title={`Joining ${orgName}`}>
        <div className="space-y-4">
          <div className="flex justify-center py-2">
            <Spinner label="Joining" />
          </div>
          {error ? <Alert>{error}</Alert> : null}
          {error ? (
            <Button
              onClick={() => {
                redeeming.current = false;
                void doRedeem();
              }}
              className="w-full"
            >
              Try again
            </Button>
          ) : null}
        </div>
      </AuthShell>
    );
  }

  // Signed in but unverified → verify step.
  if (user && !emailVerified) {
    return (
      <AuthShell
        kicker="One more step"
        title="Verify your email"
        subtitle={`Confirm your address to finish joining ${orgName}.`}
      >
        <div className="space-y-4">
          <p className="text-sm text-white/70">
            We sent a verification link to{" "}
            <span className="text-paper">{user.email}</span>. This page continues
            automatically once you click it.
          </p>
          {notice ? <Alert tone="success">{notice}</Alert> : null}
          {error ? <Alert>{error}</Alert> : null}
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

  // Not signed in → sign-up.
  return (
    <AuthShell
      kicker={invite?.label ? `Invitation · ${invite.label}` : "You're invited"}
      title={`Join ${orgName}`}
      subtitle="Create your account to join the team. You'll claim your own API key right after."
      footer={
        <>
          Already have an account?{" "}
          <Link href={`/signin?redirect=${encodeURIComponent(`/invite/${token}`)}`} className="text-mint hover:underline">
            Sign in
          </Link>{" "}
          — you&apos;ll be returned here automatically.
        </>
      }
    >
      <form onSubmit={handleSignup} className="space-y-4">
        <Field
          label="Work email"
          type="email"
          required
          autoComplete="email"
          placeholder="engineer@shop.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <Field
          label="Password"
          type="password"
          required
          autoComplete="new-password"
          placeholder="At least 6 characters"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {error ? <Alert>{error}</Alert> : null}
        <Button type="submit" disabled={busy} className="w-full">
          {busy ? "Creating account…" : "Create account →"}
        </Button>
      </form>
    </AuthShell>
  );
}
