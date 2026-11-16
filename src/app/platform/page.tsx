"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { collection, onSnapshot } from "firebase/firestore";
import { db } from "@/firebase/config";
import { useAuthContext } from "@/context/AuthContext";
import { grantSeats, revokeKey, callableError } from "@/lib/callables";
import { AppShell, PageHeader } from "@/components/AppShell";
import { Button } from "@/components/Button";
import { Card, Stat, Chip, Alert, Spinner } from "@/components/ui";
import type { ApiKey, Organization } from "@/lib/types";

/** Cross-org super-admin console — grant seats / invalidate keys on ANY org. */
export default function PlatformPage() {
  const { user, platformAdmin, emailVerified, loading } = useAuthContext();
  const router = useRouter();

  const [orgs, setOrgs] = useState<Organization[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [seats, setSeats] = useState(5);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    if (loading) return;
    if (user && !emailVerified) router.replace("/verify-email");
    else if (!platformAdmin) router.replace("/dashboard");
  }, [loading, user, emailVerified, platformAdmin, router]);

  useEffect(() => {
    if (!platformAdmin) return;
    const unsub = onSnapshot(
      collection(db, "organizations"),
      (snap) => setOrgs(snap.docs.map((d) => ({ id: d.id, ...d.data() }) as Organization)),
      (e) => setError(e.message),
    );
    return () => unsub();
  }, [platformAdmin]);

  useEffect(() => {
    if (!selected) { setKeys([]); return; }
    const unsub = onSnapshot(
      collection(db, "organizations", selected, "keys"),
      (snap) => setKeys(snap.docs.map((d) => ({ id: d.id, ...d.data() }) as ApiKey)),
    );
    return () => unsub();
  }, [selected]);

  if (loading || !platformAdmin || (user && !emailVerified)) {
    return (
      <AppShell>
        <Spinner label="Loading" />
      </AppShell>
    );
  }

  async function run(fn: () => Promise<unknown>) {
    setError("");
    setNotice("");
    setBusy(true);
    try { await fn(); } catch (e) { setError(callableError(e)); } finally { setBusy(false); }
  }

  const org = orgs.find((o) => o.id === selected);

  return (
    <AppShell>
      <PageHeader
        kicker="Platform"
        title="Super-admin console"
        actions={
          <div className="flex items-center gap-4">
            <Link
              href="/platform/invites"
              className="font-mono text-xs uppercase tracking-wider text-mint hover:underline"
            >
              Seat vouchers →
            </Link>
            <Chip tone="amber">platform admin</Chip>
          </div>
        }
      />
      {error ? <div className="mb-6"><Alert>{error}</Alert></div> : null}
      {notice ? <div className="mb-6"><Alert tone="success">{notice}</Alert></div> : null}

      <div className="grid gap-5 lg:grid-cols-[20rem_1fr]">
        {/* Org list */}
        <Card className="overflow-hidden">
          <div className="border-b border-white/10 px-5 py-4 font-mono text-xs uppercase tracking-wider text-white/45">
            Organizations · {orgs.length}
          </div>
          <ul className="max-h-[28rem] divide-y divide-white/5 overflow-auto">
            {orgs.map((o) => (
              <li key={o.id}>
                <button
                  onClick={() => setSelected(o.id)}
                  className={`flex w-full items-center justify-between px-5 py-3 text-left transition-colors hover:bg-white/5 ${
                    selected === o.id ? "bg-white/10" : ""
                  }`}
                >
                  <span className="truncate text-sm text-paper">{o.name}</span>
                  <span className="ml-2 font-mono text-[0.6rem] uppercase tracking-wider text-white/40">
                    {o.seatsUsed ?? 0}/{o.seatLimit ?? 0} seats
                  </span>
                </button>
              </li>
            ))}
            {orgs.length === 0 && (
              <li className="px-5 py-8 text-center text-sm text-white/40">No organizations.</li>
            )}
          </ul>
        </Card>

        {/* Selected org management */}
        {!org ? (
          <Card className="flex items-center justify-center p-12 text-sm text-white/40">
            Select an organization to manage its seats and keys.
          </Card>
        ) : (
          <div className="space-y-5">
            <div className="grid gap-4 sm:grid-cols-3">
              <Stat label="Organization" value={<span className="text-lg">{org.name}</span>} />
              <Stat label="Seats" value={`${org.seatsUsed ?? 0} / ${org.seatLimit ?? 0}`} />
              <Stat label="Status" value={org.status} />
            </div>

            <Card className="p-7">
              <h2 className="display text-lg text-paper">Grant seats</h2>
              <p className="mt-2 text-sm text-white/60">
                Raise <span className="text-paper">{org.name}</span>&apos;s seat
                allotment. Members claim their own keys against it — no codes to
                hand out.
              </p>
              <div className="mt-5 flex flex-wrap items-end gap-3">
                <label className="block">
                  <span className="mb-1.5 block font-mono text-xs uppercase tracking-wider text-white/50">How many</span>
                  <input
                    type="number" min={1} max={1000} value={seats}
                    onChange={(e) => setSeats(Math.max(1, Number(e.target.value)))}
                    className="w-28 rounded-[var(--radius-tile)] border border-white/15 bg-ink px-3.5 py-2.5 text-paper focus:border-mint focus:outline-none"
                  />
                </label>
                <Button
                  disabled={busy}
                  onClick={() =>
                    run(async () => {
                      const res = await grantSeats({ orgId: org.id, seats });
                      setNotice(`Granted ${res.granted} seats — ${org.name} now has ${res.seatLimit}.`);
                    })
                  }
                >
                  {busy ? "Working…" : "Grant seats →"}
                </Button>
              </div>
            </Card>

            <Card className="p-7">
              <h2 className="display text-lg text-paper">Keys</h2>
              <p className="mt-2 text-sm text-white/60">
                Metadata only — plaintext keys are never stored, so there is
                nothing to reveal here.
              </p>
              {keys.length > 0 ? (
                <ul className="mt-5 space-y-2">
                  {keys.map((k) => (
                    <li key={k.id} className="flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-tile)] border border-white/10 bg-ink-3/50 px-4 py-2.5">
                      <span className="flex items-center gap-3">
                        <code className="font-mono text-sm tracking-widest text-paper">{k.prefix}…{k.last4}</code>
                        <Chip tone={k.status === "active" ? "mint" : "amber"}>{k.status}</Chip>
                        <span className="truncate text-xs text-white/45">{k.ownerEmail ?? k.ownerUid}</span>
                      </span>
                      <span className="flex items-center gap-3">
                        {k.status === "active" && (
                          <button disabled={busy} onClick={() => run(() => revokeKey({ orgId: org.id, keyId: k.id }))} className="font-mono text-[0.65rem] uppercase tracking-wider text-amber hover:underline disabled:opacity-50">Invalidate</button>
                        )}
                        <button disabled={busy} onClick={() => run(() => revokeKey({ orgId: org.id, keyId: k.id, remove: true }))} className="font-mono text-[0.65rem] uppercase tracking-wider text-white/40 hover:text-amber disabled:opacity-50">Remove</button>
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-4 text-xs text-white/40">No keys yet — members claim their own from their dashboards.</p>
              )}
            </Card>
          </div>
        )}
      </div>
    </AppShell>
  );
}
