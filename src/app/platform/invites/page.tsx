"use client";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { collection, onSnapshot, orderBy, query } from "firebase/firestore";
import { db } from "@/firebase/config";
import { useAuthContext } from "@/context/AuthContext";
import {
  createGuidedInvite,
  disableGuidedInvite,
  callableError,
} from "@/lib/callables";
import { AppShell, PageHeader } from "@/components/AppShell";
import { Button } from "@/components/Button";
import { Card, Stat, Chip, Alert, Spinner, Field } from "@/components/ui";
import type { GuidedInvite } from "@/lib/types";

function defaultExpiryDate(): string {
  // 14 days out, as YYYY-MM-DD for <input type="date">.
  const ms = Date.now() + 14 * 24 * 60 * 60 * 1000;
  const d = new Date(ms);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

export default function GuidedInvitesPage() {
  const { user, platformAdmin, emailVerified, loading } = useAuthContext();
  const router = useRouter();

  const [invites, setInvites] = useState<GuidedInvite[]>([]);
  const [label, setLabel] = useState("");
  const [maxSignups, setMaxSignups] = useState(10);
  const [seats, setSeats] = useState(5);
  const [expiry, setExpiry] = useState(defaultExpiryDate());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [createdUrl, setCreatedUrl] = useState("");

  const origin = useMemo(
    () => (typeof window !== "undefined" ? window.location.origin : ""),
    [],
  );

  useEffect(() => {
    if (loading) return;
    if (user && !emailVerified) router.replace("/verify-email");
    else if (!platformAdmin) router.replace("/dashboard");
  }, [loading, user, emailVerified, platformAdmin, router]);

  useEffect(() => {
    if (!platformAdmin) return;
    const unsub = onSnapshot(
      query(collection(db, "guidedInvites"), orderBy("createdAt", "desc")),
      (snap) =>
        setInvites(snap.docs.map((d) => ({ id: d.id, ...d.data() }) as GuidedInvite)),
      (e) => setError(e.message),
    );
    return () => unsub();
  }, [platformAdmin]);

  if (loading || !platformAdmin || (user && !emailVerified)) {
    return (
      <AppShell>
        <Spinner label="Loading" />
      </AppShell>
    );
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setCreatedUrl("");
    // End-of-day local time for the chosen date.
    const expiresAtMs = new Date(`${expiry}T23:59:59`).getTime();
    if (!Number.isFinite(expiresAtMs) || expiresAtMs <= Date.now()) {
      setError("Pick an expiry date in the future.");
      return;
    }
    setBusy(true);
    try {
      const res = await createGuidedInvite({
        label: label.trim() || undefined,
        maxSignups,
        seats,
        expiresAtMs,
      });
      setCreatedUrl(res.url);
      setLabel("");
    } catch (err) {
      setError(callableError(err));
    } finally {
      setBusy(false);
    }
  }

  async function run(fn: () => Promise<unknown>) {
    setError("");
    setBusy(true);
    try {
      await fn();
    } catch (err) {
      setError(callableError(err));
    } finally {
      setBusy(false);
    }
  }

  const fmtDate = (ms?: number) =>
    ms ? new Date(ms).toLocaleDateString(undefined, { dateStyle: "medium" }) : "—";

  return (
    <AppShell>
      <PageHeader
        kicker="Platform"
        title="Seat vouchers"
        actions={
          <Link href="/platform" className="font-mono text-xs uppercase tracking-wider text-white/60 hover:text-paper">
            ← Console
          </Link>
        }
      />

      {error ? (
        <div className="mb-6">
          <Alert>{error}</Alert>
        </div>
      ) : null}

      {/* Create */}
      <Card className="p-7">
        <h2 className="display text-lg text-paper">Create a voucher link</h2>
        <p className="mt-2 text-sm text-white/60">
          One link can onboard a batch of people. Each person who redeems it
          adds the seats below to an organization they run — or starts a new
          one. Their members then claim their own API keys against those seats;
          no key codes are ever pre-minted or emailed.
        </p>
        <form onSubmit={handleCreate} className="mt-5 grid gap-4 sm:grid-cols-2">
          <Field
            label="Label (optional)"
            placeholder="Spring pilot cohort"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
          />
          <Field
            label="Expires on"
            type="date"
            value={expiry}
            onChange={(e) => setExpiry(e.target.value)}
          />
          <label className="block">
            <span className="mb-1.5 block font-mono text-xs uppercase tracking-wider text-white/50">
              Max sign-ups
            </span>
            <input
              type="number"
              min={1}
              max={1000}
              value={maxSignups}
              onChange={(e) => setMaxSignups(Math.max(1, Number(e.target.value)))}
              className="w-full rounded-[var(--radius-tile)] border border-white/15 bg-ink px-3.5 py-2.5 text-paper focus:border-mint focus:outline-none"
            />
          </label>
          <label className="block">
            <span className="mb-1.5 block font-mono text-xs uppercase tracking-wider text-white/50">
              Seats per redemption
            </span>
            <input
              type="number"
              min={1}
              max={500}
              value={seats}
              onChange={(e) => setSeats(Math.max(1, Number(e.target.value)))}
              className="w-full rounded-[var(--radius-tile)] border border-white/15 bg-ink px-3.5 py-2.5 text-paper focus:border-mint focus:outline-none"
            />
          </label>
          <div className="sm:col-span-2">
            <Button type="submit" disabled={busy}>
              {busy ? "Working…" : "Generate link →"}
            </Button>
          </div>
        </form>

        {createdUrl ? (
          <div className="mt-5">
            <Alert tone="success">
              <div className="flex flex-wrap items-center gap-3">
                <code className="break-all font-mono text-xs text-mint">{createdUrl}</code>
                <button
                  onClick={() => navigator.clipboard?.writeText(createdUrl)}
                  className="font-mono text-[0.65rem] uppercase tracking-wider text-white/70 hover:text-paper"
                >
                  Copy link
                </button>
              </div>
            </Alert>
          </div>
        ) : null}
      </Card>

      {/* Existing */}
      <Card className="mt-6 overflow-hidden">
        <div className="flex items-center justify-between border-b border-white/10 px-7 py-5">
          <h2 className="display text-lg text-paper">Active & past invites</h2>
          <Chip tone="neutral">{invites.length}</Chip>
        </div>
        <div className="divide-y divide-white/5">
          {invites.map((inv) => {
            const expMs = inv.expiresAt?.toMillis?.();
            const expired = !!expMs && expMs <= Date.now();
            const used = inv.usedCount ?? 0;
            const exhausted = used >= inv.maxSignups;
            const live = inv.status === "active" && !expired && !exhausted;
            const url = `${origin}/join/${inv.token}`;
            return (
              <div key={inv.id} className="px-7 py-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-paper">
                        {inv.label || "Untitled invite"}
                      </span>
                      <Chip tone={live ? "mint" : "amber"}>
                        {inv.status !== "active"
                          ? "disabled"
                          : expired
                            ? "expired"
                            : exhausted
                              ? "used up"
                              : "active"}
                      </Chip>
                    </div>
                    <div className="mt-1 font-mono text-[0.65rem] uppercase tracking-wider text-white/40">
                      {used}/{inv.maxSignups} used · {inv.seats ?? 0} seats each · expires {fmtDate(expMs)}
                    </div>
                  </div>
                  <div className="flex shrink-0 flex-wrap items-center gap-3">
                    <button
                      onClick={() => navigator.clipboard?.writeText(url)}
                      className="font-mono text-[0.65rem] uppercase tracking-wider text-white/60 hover:text-paper"
                    >
                      Copy link
                    </button>
                    {inv.status === "active" && (
                      <button
                        disabled={busy}
                        onClick={() => run(() => disableGuidedInvite({ id: inv.id }))}
                        className="font-mono text-[0.65rem] uppercase tracking-wider text-amber hover:underline disabled:opacity-50"
                      >
                        Disable
                      </button>
                    )}
                    <button
                      disabled={busy}
                      onClick={() => run(() => disableGuidedInvite({ id: inv.id, remove: true }))}
                      className="font-mono text-[0.65rem] uppercase tracking-wider text-white/40 hover:text-amber disabled:opacity-50"
                    >
                      Remove
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
          {invites.length === 0 && (
            <div className="px-7 py-8 text-center text-sm text-white/40">
              No invites yet — create one above.
            </div>
          )}
        </div>
      </Card>

      <div className="mt-4">
        <Stat label="Tip" value={<span className="text-sm text-white/60">Share a link with a batch of people; each adds the seats to an org they run (or a new one) and invites their team from there.</span>} />
      </div>
    </AppShell>
  );
}
