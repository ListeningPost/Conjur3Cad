"use client";
import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { doc, setDoc, serverTimestamp } from "firebase/firestore";
import signUp from "@/firebase/auth/signup";
import sendVerification from "@/firebase/auth/verify";
import { db } from "@/firebase/config";
import { AuthShell } from "@/components/AuthShell";
import { Button } from "@/components/Button";
import { Field, Alert } from "@/components/ui";

export default function SignUpPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const router = useRouter();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (password.length < 6) {
      setError("Password must be at least 6 characters.");
      return;
    }
    setBusy(true);
    const { result, error } = await signUp(email, password);
    if (error || !result) {
      setError(
        String((error as { code?: string })?.code ?? "").includes("in-use")
          ? "That email is already registered."
          : "Could not create your account.",
      );
      setBusy(false);
      return;
    }

    // Seed a minimal profile doc (rules forbid role/orgId here — those are set
    // server-side when the user creates or joins an org).
    try {
      await setDoc(
        doc(db, "users", result.user.uid),
        { email, createdAt: serverTimestamp() },
        { merge: true },
      );
    } catch {
      /* non-fatal: the profile is also written on org create/claim */
    }

    // Email a verification link, then hand off to the verify-email gate. The
    // account exists and is signed in, but stays unverified until confirmed.
    await sendVerification(result.user);
    router.push("/verify-email");
  }

  return (
    <AuthShell
      kicker="Team access"
      title="Get access"
      subtitle="Create your account — we'll email you a link to verify it, then you can start an organization or claim a seat key."
      footer={
        <>
          Already have an account?{" "}
          <Link href="/signin" className="text-mint hover:underline">
            Sign in
          </Link>
        </>
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <Field
          label="Email"
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
