"use client";
import { useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import signIn from "@/firebase/auth/signIn";
import { AuthShell } from "@/components/AuthShell";
import { Button } from "@/components/Button";
import { Field, Alert } from "@/components/ui";

export default function SignInPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const router = useRouter();
  const searchParams = useSearchParams();
  const redirect = searchParams.get("redirect") ?? "/dashboard";

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    const { result, error } = await signIn(email, password);
    if (error || !result) {
      const code = (error as { code?: string })?.code;
      if (code === "auth/too-many-requests") {
        setError(
          "Too many failed attempts — this account is temporarily locked. Reset your password to regain access immediately.",
        );
      } else {
        setError("Invalid email or password.");
      }
      setBusy(false);
      return;
    }
    // Unverified accounts must confirm their email before reaching the app.
    // Preserve the redirect so invite links work after email verification too.
    router.push(result.user.emailVerified ? redirect : `/verify-email?redirect=${encodeURIComponent(redirect)}`);
  }

  return (
    <AuthShell
      kicker="Team access"
      title="Sign in"
      subtitle="Access your Conjur3 organization and seat."
      footer={
        <>
          No account?{" "}
          <Link href="/signup" className="text-mint hover:underline">
            Get access
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
          autoComplete="current-password"
          placeholder="••••••••"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <div className="text-right">
          <Link
            href="/forgot-password"
            className="text-xs text-white/50 hover:text-mint"
          >
            Forgot password?
          </Link>
        </div>
        {error ? <Alert>{error}</Alert> : null}
        <Button type="submit" disabled={busy} className="w-full">
          {busy ? "Signing in…" : "Sign in →"}
        </Button>
      </form>
    </AuthShell>
  );
}
