"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { doc, getDoc, serverTimestamp, setDoc } from "firebase/firestore";
import signUp from "@/firebase/auth/signup";
import sendVerification from "@/firebase/auth/verify";
import { auth, db } from "@/firebase/config";
import { useAuthContext } from "@/context/AuthContext";
import {
  getGuidedInvite,
  redeemGuidedInvite,
  callableError,
} from "@/lib/callables";
import { AuthShell } from "@/components/AuthShell";
import { Button, ButtonLink } from "@/components/Button";
import { Field, Alert, Spinner } from "@/components/ui";

interface InviteInfo {
  valid: boolean;
  reason?: string | null;
  label?: string | null;
  seats?: number;
  remaining?: number;
  expiresAtMs?: number;
}

const INVALID_MSG: Record<string, string> = {
  missing: "This invite link is incomplete.",
  not_found: "This invite link is invalid.",
  expired: "This invite has expired.",
  exhausted: "This invite has reached its sign-up limit.",
  disabled: "This invite is no longer active.",
  error: "We couldn't check this invite. Try again later.",
};

export default function JoinPage() {
  const params = useParams<{ token: string }>();
  const token = String(params?.token ?? "");
  const { user, emailVerified, memberships, membershipsLoading, loading, reloadUser } =
    useAuthContext();

  const [invite, setInvite] = useState<InviteInfo | null>(null);
  const [checkingInvite, setCheckingInvite] = useState(true);

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [orgName, setOrgName] = useState("");
  const [attachOrgId, setAttachOrgId] = useState("");
  const [adminOrgs, setAdminOrgs] = useState<{ id: string; name: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [cooldown, setCooldown] = useState(0);

  const [done, setDone] = useState<{
    orgName: string;
    seats: number;
    mode: "create" | "attach";
  } | null>(null);

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
        const res = await getGuidedInvite({ token });
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

  // Names of the orgs the caller administers — the "add seats to…" dropdown.
  useEffect(() => {
    let active = true;
    const adminIds = memberships.filter((m) => m.role === "admin").map((m) => m.orgId);
    if (adminIds.length === 0) {
      setAdminOrgs([]);
      return;
    }
    Promise.all(
      adminIds.map(async (id) => {
        try {
          const snap = await getDoc(doc(db, "organizations", id));
          return { id, name: (snap.get("name") as string) ?? id };
        } catch {
          return { id, name: id };
        }
      }),
    ).then((orgs) => {
      if (active) {
        setAdminOrgs(orgs);
        setAttachOrgId((cur) => cur || orgs[0]?.id || "");
      }
    });
    return () => {
      active = false;
    };
  }, [memberships]);

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

  async function redeem(mode: "create" | "attach") {
    setError("");
    setBusy(true);
    try {
      // Ensure the ID token carries the verified-email claim before redeeming.
      await auth.currentUser?.getIdToken(true);
      const res = await redeemGuidedInvite({
        token,
        mode,
        orgName: mode === "create" ? orgName.trim() || undefined : undefined,
        orgId: mode === "attach" ? attachOrgId : undefined,
      });
      setDone({ orgName: res.orgName, seats: res.seats, mode: res.mode });
    } catch (err) {
      setError(callableError(err));
    } finally {
      setBusy(false);
    }
  }

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
      <AuthShell title="Joining Conjur3">
        <div className="flex justify-center py-4">
          <Spinner label="Loading" />
        </div>
      </AuthShell>
    );
  }

  if (!invite?.valid && !done) {
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

  const seats = invite?.seats ?? 0;

  // Redeemed — done. No keys are shown here: members each mint their own.
  if (done) {
    return (
      <AuthShell
        kicker="You're in"
        title={
          done.mode === "attach"
            ? `${done.seats} seats added to ${done.orgName}`
            : `Welcome to ${done.orgName}`
        }
        subtitle={
          done.mode === "attach"
            ? "Your team can claim that many more API keys."
            : `Your workspace is ready with ${done.seats} seats and you're its admin.`
        }
      >
        <div className="space-y-4">
          <Alert tone="info">
            Next: claim your own API key from the dashboard (shown to you once),
            and share invite links with your team from the Team console — each
            person mints their own key.
          </Alert>
          <ButtonLink href="/dashboard" className="w-full">
            Go to dashboard →
          </ButtonLink>
        </div>
      </AuthShell>
    );
  }

  // Verified, signed in → choose where the seats go.
  if (user && emailVerified) {
    if (membershipsLoading) {
      return (
        <AuthShell title="Joining Conjur3">
          <div className="flex justify-center py-4">
            <Spinner label="Loading" />
          </div>
        </AuthShell>
      );
    }
    return (
      <AuthShell
        kicker={invite?.label ? `Invitation · ${invite.label}` : "You're invited"}
        title={`This invite is worth ${seats} seat${seats === 1 ? "" : "s"}`}
        subtitle={
          adminOrgs.length > 0
            ? "Add them to an organization you run, or start a new one."
            : "Create your workspace — you'll be its admin."
        }
      >
        <div className="space-y-6">
          {error ? <Alert>{error}</Alert> : null}

          {adminOrgs.length > 0 && (
            <div className="space-y-3">
              <label className="block">
                <span className="mb-1.5 block font-mono text-xs uppercase tracking-wider text-white/50">
                  Add seats to
                </span>
                <select
                  value={attachOrgId}
                  onChange={(e) => setAttachOrgId(e.target.value)}
                  className="w-full rounded-[var(--radius-tile)] border border-white/15 bg-ink px-3.5 py-2.5 text-paper focus:border-mint focus:outline-none"
                >
                  {adminOrgs.map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.name}
                    </option>
                  ))}
                </select>
              </label>
              <Button
                disabled={busy || !attachOrgId}
                onClick={() => redeem("attach")}
                className="w-full"
              >
                {busy ? "Working…" : `Add ${seats} seat${seats === 1 ? "" : "s"} →`}
              </Button>
              <div className="text-center font-mono text-[0.65rem] uppercase tracking-wider text-white/35">
                — or —
              </div>
            </div>
          )}

          <div className="space-y-3">
            <Field
              label={adminOrgs.length > 0 ? "New organization name" : "Organization name (optional)"}
              placeholder="Acme Precision Machining"
              value={orgName}
              onChange={(e) => setOrgName(e.target.value)}
            />
            <Button
              variant={adminOrgs.length > 0 ? "outline" : "primary"}
              disabled={busy}
              onClick={() => redeem("create")}
              className="w-full"
            >
              {busy
                ? "Working…"
                : `Create a new org with ${seats} seat${seats === 1 ? "" : "s"} →`}
            </Button>
          </div>
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
        subtitle="Confirm your address to finish joining."
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

  // Not signed in → guided sign-up.
  return (
    <AuthShell
      kicker={invite?.label ? `Invitation · ${invite.label}` : "You're invited"}
      title="Create your Conjur3 account"
      subtitle={`This invite is worth ${seats} seat${seats === 1 ? "" : "s"} — add them to your organization (or a new one) after you sign up.`}
      footer={
        <>
          Already have an account?{" "}
          <Link href={`/signin?redirect=${encodeURIComponent(`/join/${token}`)}`} className="text-mint hover:underline">
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
