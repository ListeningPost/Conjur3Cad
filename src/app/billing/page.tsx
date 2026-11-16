"use client";
import { useState } from "react";
import {
  addDoc,
  collection,
  onSnapshot,
  serverTimestamp,
} from "firebase/firestore";
import { httpsCallable } from "firebase/functions";
import { useRequireAuth } from "@/hooks/useRequireAuth";
import { useAuthContext } from "@/context/AuthContext";
import { useFlags } from "@/hooks/useFlags";
import { useOrg } from "@/hooks/useOrg";
import { auth, db, functions, useEmulators } from "@/firebase/config";
import { devSeedSubscription, callableError } from "@/lib/callables";
import { AppShell, PageHeader } from "@/components/AppShell";
import { Button } from "@/components/Button";
import { Card, Stat, Alert, Spinner, Chip } from "@/components/ui";

const SEAT_PRICE_ID = process.env.NEXT_PUBLIC_STRIPE_SEAT_PRICE_ID ?? "";

export default function BillingPage() {
  const { ready } = useRequireAuth({ minRole: "admin" });
  const { memberships } = useAuthContext();
  const { stripeEnabled } = useFlags();
  // Billing targets the first org the user administers (the common case is
  // exactly one owned org; multi-org billing UI can come with live Stripe).
  const orgId = memberships.find((m) => m.role === "admin")?.orgId ?? null;
  const { org, loading } = useOrg(orgId);

  const [seats, setSeats] = useState(5);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  if (!ready || loading) {
    return (
      <AppShell>
        <Spinner label="Loading" />
      </AppShell>
    );
  }

  if (!stripeEnabled) {
    return (
      <AppShell>
        <PageHeader kicker="Billing" title="Seats & subscription" />
        <Card className="p-7">
          <h2 className="display text-lg text-paper">Billing is paused</h2>
          <p className="mt-2 text-sm text-white/60">
            Paid subscriptions are temporarily disabled — your organization has
            full access at no charge for now. Seat purchasing will return here
            when billing is re-enabled.
          </p>
        </Card>
      </AppShell>
    );
  }

  // Live Stripe checkout via the firestore-stripe-payments extension.
  async function startCheckout() {
    setError("");
    if (!SEAT_PRICE_ID) {
      setError("No seat price configured (NEXT_PUBLIC_STRIPE_SEAT_PRICE_ID).");
      return;
    }
    setBusy(true);
    try {
      const uid = auth.currentUser!.uid;
      const ref = await addDoc(
        collection(db, "customers", uid, "checkout_sessions"),
        {
          price: SEAT_PRICE_ID,
          quantity: seats,
          mode: "subscription",
          success_url: `${window.location.origin}/billing?status=success`,
          cancel_url: `${window.location.origin}/billing?status=cancel`,
          created: serverTimestamp(),
        },
      );
      // The extension writes back `url` (or `error`) onto the session doc.
      const unsub = onSnapshot(ref, (snap) => {
        const data = snap.data() as { url?: string; error?: { message: string } };
        if (data?.error) {
          setError(data.error.message);
          setBusy(false);
          unsub();
        }
        if (data?.url) {
          unsub();
          window.location.assign(data.url);
        }
      });
    } catch (err) {
      setError(callableError(err));
      setBusy(false);
    }
  }

  async function openPortal() {
    setError("");
    setBusy(true);
    try {
      const fn = httpsCallable<
        { returnUrl: string },
        { url: string }
      >(functions, "ext-firestore-stripe-payments-createPortalLink");
      const { data } = await fn({ returnUrl: window.location.origin + "/billing" });
      window.location.assign(data.url);
    } catch (err) {
      setError(callableError(err));
      setBusy(false);
    }
  }

  async function seedDev() {
    setError("");
    setNotice("");
    setBusy(true);
    try {
      if (!orgId) throw new Error("No organization.");
      await devSeedSubscription({ orgId, seats });
      setNotice(`Seeded ${seats} seats. Subscription marked active.`);
    } catch (err) {
      setError(callableError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell>
      <PageHeader
        kicker="Billing"
        title="Seats & subscription"
        actions={<Chip tone={org?.status === "active" ? "mint" : "amber"}>{org?.status}</Chip>}
      />

      <div className="grid gap-4 sm:grid-cols-3">
        <Stat label="Seats purchased" value={org?.seatLimit ?? 0} />
        <Stat label="Seats used" value={org?.seatsUsed ?? 0} />
        <Stat
          label="Subscription"
          value={org?.stripeSubscriptionId ? "Linked" : "None"}
        />
      </div>

      {error ? (
        <div className="mt-6">
          <Alert>{error}</Alert>
        </div>
      ) : null}
      {notice ? (
        <div className="mt-6">
          <Alert tone="success">{notice}</Alert>
        </div>
      ) : null}

      <div className="mt-8 grid gap-5 md:grid-cols-2">
        <Card className="p-7">
          <h2 className="display text-lg text-paper">Seat-based plan</h2>
          <p className="mt-2 text-sm text-white/60">
            Each seat is one license key your engineers can claim. Adjust the
            quantity and check out via Stripe.
          </p>
          <label className="mt-5 block">
            <span className="mb-1.5 block font-mono text-xs uppercase tracking-wider text-white/50">
              Seats
            </span>
            <input
              type="number"
              min={1}
              max={1000}
              value={seats}
              onChange={(e) => setSeats(Math.max(1, Number(e.target.value)))}
              className="w-32 rounded-[var(--radius-tile)] border border-white/15 bg-ink px-3.5 py-2.5 text-paper focus:border-mint focus:outline-none"
            />
          </label>
          <div className="mt-5 flex flex-wrap gap-3">
            <Button onClick={startCheckout} disabled={busy}>
              {busy ? "Working…" : "Checkout with Stripe →"}
            </Button>
            <Button onClick={openPortal} variant="outline" disabled={busy}>
              Manage billing
            </Button>
          </div>
        </Card>

        {useEmulators && (
          <Card className="p-7">
            <div className="mb-2 flex items-center gap-2">
              <h2 className="display text-lg text-paper">Dev: seed seats</h2>
              <Chip tone="aqua">emulator</Chip>
            </div>
            <p className="mt-1 text-sm text-white/60">
              No live Stripe in the emulator. Seed an active subscription with
              the seat count above to exercise the full flow.
            </p>
            <Button onClick={seedDev} variant="outline" disabled={busy} className="mt-5">
              {busy ? "Seeding…" : `Seed ${seats} seats →`}
            </Button>
          </Card>
        )}
      </div>
    </AppShell>
  );
}
