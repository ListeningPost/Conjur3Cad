"use client";
import { useState } from "react";
import Link from "next/link";
import sendReset from "@/firebase/auth/reset";
import { AuthShell } from "@/components/AuthShell";
import { Button } from "@/components/Button";
import { Field, Alert } from "@/components/ui";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    const { error: resetErr } = await sendReset(email.trim());
    setBusy(false);
    // Surface only malformed-input errors. Never reveal whether an account
    // exists — always show the same confirmation otherwise.
    if (
      resetErr &&
      String((resetErr as { code?: string })?.code ?? "").includes("invalid-email")
    ) {
      setError("Enter a valid email address.");
      return;
    }
    setSent(true);
  }

  return (
    <AuthShell
      kicker="Account recovery"
      title="Reset your password"
      subtitle={
        sent
          ? undefined
          : "Enter your email and we'll send you a link to set a new password."
      }
      footer={
        <>
          Remembered it?{" "}
          <Link href="/signin" className="text-mint hover:underline">
            Sign in
          </Link>
        </>
      }
    >
      {sent ? (
        <div className="space-y-4">
          <Alert tone="success">
            If an account exists for{" "}
            <span className="text-paper">{email}</span>, a password-reset link is
            on its way. Check your inbox (and spam).
          </Alert>
          <Button
            variant="outline"
            onClick={() => {
              setSent(false);
              setEmail("");
            }}
            className="w-full"
          >
            Use a different email
          </Button>
        </div>
      ) : (
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
          {error ? <Alert>{error}</Alert> : null}
          <Button type="submit" disabled={busy || !email.trim()} className="w-full">
            {busy ? "Sending…" : "Send reset link →"}
          </Button>
        </form>
      )}
    </AuthShell>
  );
}
