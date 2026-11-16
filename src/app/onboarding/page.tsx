"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { useRequireAuth } from "@/hooks/useRequireAuth";
import { useFlags } from "@/hooks/useFlags";
import { createOrganization, callableError } from "@/lib/callables";
import { AuthShell } from "@/components/AuthShell";
import { Button } from "@/components/Button";
import { Field, Alert, Spinner } from "@/components/ui";

export default function OnboardingPage() {
  const { ready } = useRequireAuth();
  const { stripeEnabled } = useFlags();
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const router = useRouter();

  if (!ready) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Spinner label="Loading" />
      </div>
    );
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await createOrganization({ name: name.trim() });
      // With billing paused there's nothing to set up — go straight to the app.
      router.push(stripeEnabled ? "/billing" : "/dashboard");
    } catch (err) {
      setError(callableError(err));
      setBusy(false);
    }
  }

  return (
    <AuthShell
      kicker="New organization"
      title="Create your org"
      subtitle="You'll be the org admin — you manage seats, invites, and your team. You can belong to several organizations at once."
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <Field
          label="Organization name"
          required
          placeholder="Acme Precision Machining"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        {error ? <Alert>{error}</Alert> : null}
        <Button type="submit" disabled={busy || name.trim().length < 2} className="w-full">
          {busy ? "Creating…" : "Create organization →"}
        </Button>
      </form>
    </AuthShell>
  );
}
