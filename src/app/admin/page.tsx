"use client";
import { Suspense, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  collection,
  doc,
  getDoc,
  onSnapshot,
  orderBy,
  query,
  where,
} from "firebase/firestore";
import { db } from "@/firebase/config";
import { useRequireAuth } from "@/hooks/useRequireAuth";
import { useAuthContext } from "@/context/AuthContext";
import { useOrg } from "@/hooks/useOrg";
import {
  setMemberRole,
  revokeMember,
  revokeKey,
  inviteMember,
  createOrgInvite,
  revokeOrgInvite,
  callableError,
} from "@/lib/callables";
import { AppShell, PageHeader } from "@/components/AppShell";
import { Button } from "@/components/Button";
import { Card, Stat, Chip, Alert, Spinner, Field } from "@/components/ui";
import {
  normalizeRole,
  type ApiKey,
  type Member,
  type OrgInvite,
} from "@/lib/types";

function defaultExpiryDate(): string {
  const ms = Date.now() + 14 * 24 * 60 * 60 * 1000;
  const d = new Date(ms);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function AdminConsole() {
  const { ready } = useRequireAuth({ minRole: "admin" });
  const { user, memberships, platformAdmin } = useAuthContext();
  const router = useRouter();
  const searchParams = useSearchParams();

  const adminOrgIds = useMemo(
    () => memberships.filter((m) => m.role === "admin").map((m) => m.orgId),
    [memberships],
  );
  const requested = searchParams.get("org");
  const orgId =
    requested && (platformAdmin || adminOrgIds.includes(requested))
      ? requested
      : adminOrgIds[0] ?? null;

  const { org, loading } = useOrg(orgId);
  const [orgNames, setOrgNames] = useState<Record<string, string>>({});
  const [members, setMembers] = useState<Member[]>([]);
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [invites, setInvites] = useState<OrgInvite[]>([]);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteNote, setInviteNote] = useState("");
  const [linkLabel, setLinkLabel] = useState("");
  const [linkUses, setLinkUses] = useState(10);
  const [linkExpiry, setLinkExpiry] = useState(defaultExpiryDate());
  const [createdUrl, setCreatedUrl] = useState("");

  const origin = useMemo(
    () => (typeof window !== "undefined" ? window.location.origin : ""),
    [],
  );

  // Names for the org switcher.
  useEffect(() => {
    let active = true;
    Promise.all(
      adminOrgIds.map(async (id) => {
        try {
          const snap = await getDoc(doc(db, "organizations", id));
          return [id, (snap.get("name") as string) ?? id] as const;
        } catch {
          return [id, id] as const;
        }
      }),
    ).then((pairs) => {
      if (active) setOrgNames(Object.fromEntries(pairs));
    });
    return () => {
      active = false;
    };
  }, [adminOrgIds]);

  useEffect(() => {
    if (!orgId) return;
    const unsubM = onSnapshot(
      query(collection(db, "organizations", orgId, "members"), orderBy("joinedAt", "asc")),
      (snap) => setMembers(snap.docs.map((d) => ({ uid: d.id, ...d.data() }) as Member)),
    );
    const unsubK = onSnapshot(
      collection(db, "organizations", orgId, "keys"),
      (snap) => setKeys(snap.docs.map((d) => ({ id: d.id, ...d.data() }) as ApiKey)),
    );
    const unsubI = onSnapshot(
      query(
        collection(db, "orgInvites"),
        where("orgId", "==", orgId),
        orderBy("createdAt", "desc"),
      ),
      (snap) => setInvites(snap.docs.map((d) => ({ id: d.id, ...d.data() }) as OrgInvite)),
    );
    return () => {
      unsubM();
      unsubK();
      unsubI();
    };
  }, [orgId]);

  if (!ready || (orgId && loading)) {
    return (
      <AppShell>
        <Spinner label="Loading" />
      </AppShell>
    );
  }

  if (!orgId) {
    return (
      <AppShell>
        <PageHeader kicker="Team console" title="No organization" />
        <p className="text-white/60">You don&apos;t administer any organization yet.</p>
      </AppShell>
    );
  }

  const ownerUid = org?.ownerUid;
  const keysById = new Map(keys.map((k) => [k.id, k]));
  const activeKeyCount = keys.filter((k) => k.status === "active").length;
  const seatsFree = Math.max(0, (org?.seatLimit ?? 0) - (org?.seatsUsed ?? 0));

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

  async function handleCreateLink(e: React.FormEvent) {
    e.preventDefault();
    setCreatedUrl("");
    const expiresAtMs = new Date(`${linkExpiry}T23:59:59`).getTime();
    if (!Number.isFinite(expiresAtMs) || expiresAtMs <= Date.now()) {
      setError("Pick an expiry date in the future.");
      return;
    }
    await run(async () => {
      const res = await createOrgInvite({
        orgId: orgId!,
        label: linkLabel.trim() || undefined,
        maxUses: linkUses,
        expiresAtMs,
      });
      setCreatedUrl(res.url);
      setLinkLabel("");
    });
  }

  async function handleInvite(e: React.FormEvent) {
    e.preventDefault();
    const email = inviteEmail.trim();
    if (!email) return;
    setInviteNote("");
    await run(async () => {
      const res = await inviteMember({ orgId: orgId!, email });
      setInviteNote(
        res.emailed
          ? `Invite emailed to ${res.email}.`
          : `Invite created for ${res.email} — email wasn't sent, share this link: ${res.url}`,
      );
      setInviteEmail("");
    });
  }

  const fmtDate = (ms?: number) =>
    ms ? new Date(ms).toLocaleDateString(undefined, { dateStyle: "medium" }) : "—";

  return (
    <AppShell>
      <PageHeader
        kicker="Team console"
        title={org?.name ?? "Team"}
        actions={
          <div className="flex items-center gap-3">
            {adminOrgIds.length > 1 && (
              <select
                value={orgId}
                onChange={(e) => router.replace(`/admin?org=${e.target.value}`)}
                className="rounded-[var(--radius-tile)] border border-white/15 bg-ink px-3 py-2 text-sm text-paper focus:border-mint focus:outline-none"
              >
                {adminOrgIds.map((id) => (
                  <option key={id} value={id}>
                    {orgNames[id] ?? id}
                  </option>
                ))}
              </select>
            )}
            {platformAdmin ? <Chip tone="amber">platform admin</Chip> : undefined}
          </div>
        }
      />

      <div className="grid gap-4 sm:grid-cols-3">
        <Stat label="Seats" value={`${org?.seatsUsed ?? 0} / ${org?.seatLimit ?? 0}`} />
        <Stat label="Active keys" value={activeKeyCount} />
        <Stat label="Members" value={members.length} />
      </div>

      {error ? (
        <div className="mt-6">
          <Alert>{error}</Alert>
        </div>
      ) : null}

      {/* Invite links */}
      <Card className="mt-8 p-7">
        <h2 className="display text-lg text-paper">Invite links</h2>
        <p className="mt-2 text-sm text-white/60">
          Share a link to bring people into <span className="text-paper">{org?.name}</span>.
          A link carries no secrets — each person who joins claims their own API
          key from their dashboard ({seatsFree} seat{seatsFree === 1 ? "" : "s"} free).
        </p>
        <form onSubmit={handleCreateLink} className="mt-5 grid gap-4 sm:grid-cols-3">
          <Field
            label="Label (optional)"
            placeholder="Machining team"
            value={linkLabel}
            onChange={(e) => setLinkLabel(e.target.value)}
          />
          <label className="block">
            <span className="mb-1.5 block font-mono text-xs uppercase tracking-wider text-white/50">
              Max uses
            </span>
            <input
              type="number"
              min={1}
              max={500}
              value={linkUses}
              onChange={(e) => setLinkUses(Math.max(1, Number(e.target.value)))}
              className="w-full rounded-[var(--radius-tile)] border border-white/15 bg-ink px-3.5 py-2.5 text-paper focus:border-mint focus:outline-none"
            />
          </label>
          <Field
            label="Expires on"
            type="date"
            value={linkExpiry}
            onChange={(e) => setLinkExpiry(e.target.value)}
          />
          <div className="sm:col-span-3">
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

        {invites.length > 0 && (
          <div className="mt-6 divide-y divide-white/5">
            {invites.map((inv) => {
              const expMs = inv.expiresAt?.toMillis?.();
              const expired = !!expMs && expMs <= Date.now();
              const exhausted = (inv.usedCount ?? 0) >= inv.maxUses;
              const live = inv.status === "active" && !expired && !exhausted;
              const url = `${origin}/invite/${inv.token}`;
              return (
                <div
                  key={inv.id}
                  className="flex flex-wrap items-center justify-between gap-3 py-3"
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-sm text-paper">
                        {inv.label || inv.invitedEmail || "Open invite"}
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
                      {inv.usedCount ?? 0}/{inv.maxUses} used · expires {fmtDate(expMs)}
                    </div>
                  </div>
                  <div className="flex shrink-0 flex-wrap items-center gap-3">
                    {live && (
                      <button
                        onClick={() => navigator.clipboard?.writeText(url)}
                        className="font-mono text-[0.65rem] uppercase tracking-wider text-white/60 hover:text-paper"
                      >
                        Copy link
                      </button>
                    )}
                    {inv.status === "active" && (
                      <button
                        disabled={busy}
                        onClick={() => run(() => revokeOrgInvite({ token: inv.token }))}
                        className="font-mono text-[0.65rem] uppercase tracking-wider text-amber hover:underline disabled:opacity-50"
                      >
                        Disable
                      </button>
                    )}
                    <button
                      disabled={busy}
                      onClick={() => run(() => revokeOrgInvite({ token: inv.token, remove: true }))}
                      className="font-mono text-[0.65rem] uppercase tracking-wider text-white/40 hover:text-amber disabled:opacity-50"
                    >
                      Remove
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Card>

      {/* Invite by email */}
      <Card className="mt-6 p-7">
        <h2 className="display text-lg text-paper">Invite a teammate by email</h2>
        <p className="mt-2 text-sm text-white/60">
          Sends a single-use join link tied to their address. No key codes in
          email — they mint their own key after joining.
        </p>
        <form onSubmit={handleInvite} className="mt-5 flex flex-wrap items-end gap-3">
          <div className="min-w-[16rem] flex-1">
            <Field
              label="Email"
              type="email"
              required
              placeholder="engineer@shop.com"
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
            />
          </div>
          <Button type="submit" disabled={busy || !inviteEmail.trim()}>
            {busy ? "Working…" : "Send invite →"}
          </Button>
        </form>
        {inviteNote ? (
          <div className="mt-4">
            <Alert tone="success">{inviteNote}</Alert>
          </div>
        ) : null}
      </Card>

      {/* Members & their keys */}
      <Card className="mt-6 overflow-hidden">
        <div className="border-b border-white/10 px-7 py-5">
          <h2 className="display text-lg text-paper">Members</h2>
        </div>
        <div className="divide-y divide-white/5">
          {members.map((m) => {
            const isSelf = m.uid === user?.uid;
            const isOwnerMember = m.uid === ownerUid;
            const tier = normalizeRole(m.role);
            const memberKey = m.keyId ? keysById.get(m.keyId) : undefined;
            // Any admin can manage anyone except the org owner and themselves.
            const canManage = !isSelf && !isOwnerMember;
            return (
              <div
                key={m.uid}
                className="flex flex-wrap items-center justify-between gap-3 px-7 py-4"
              >
                <div className="min-w-0">
                  <div className="truncate text-paper">
                    {m.email ?? m.uid}
                    {isSelf ? <span className="text-white/40"> (you)</span> : null}
                  </div>
                  <div className="mt-1 flex items-center gap-2">
                    <Chip tone={isOwnerMember ? "amber" : tier === "admin" ? "aqua" : "neutral"}>
                      {isOwnerMember ? "owner" : tier}
                    </Chip>
                    {memberKey ? (
                      <>
                        <code className="font-mono text-[0.65rem] tracking-widest text-white/50">
                          {memberKey.prefix}…{memberKey.last4}
                        </code>
                        <Chip tone={memberKey.status === "active" ? "mint" : "amber"}>
                          {memberKey.status === "active" ? "key active" : "key revoked"}
                        </Chip>
                      </>
                    ) : (
                      <span className="font-mono text-[0.65rem] uppercase tracking-wider text-white/35">
                        no key
                      </span>
                    )}
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  {memberKey?.status === "active" && (
                    <button
                      disabled={busy}
                      onClick={() => run(() => revokeKey({ orgId: orgId!, keyId: memberKey.id }))}
                      className="font-mono text-[0.65rem] uppercase tracking-wider text-amber hover:underline disabled:opacity-50"
                    >
                      Revoke key
                    </button>
                  )}
                  {canManage && (
                    <>
                      {tier === "user" ? (
                        <button
                          disabled={busy}
                          onClick={() => run(() => setMemberRole({ orgId: orgId!, uid: m.uid, role: "admin" }))}
                          className="font-mono text-[0.65rem] uppercase tracking-wider text-aqua hover:underline disabled:opacity-50"
                        >
                          Make admin
                        </button>
                      ) : (
                        <button
                          disabled={busy}
                          onClick={() => run(() => setMemberRole({ orgId: orgId!, uid: m.uid, role: "user" }))}
                          className="font-mono text-[0.65rem] uppercase tracking-wider text-white/60 hover:underline disabled:opacity-50"
                        >
                          Make user
                        </button>
                      )}
                      <button
                        disabled={busy}
                        onClick={() => run(() => revokeMember({ orgId: orgId!, uid: m.uid }))}
                        className="font-mono text-[0.65rem] uppercase tracking-wider text-amber hover:underline disabled:opacity-50"
                      >
                        Remove
                      </button>
                    </>
                  )}
                </div>
              </div>
            );
          })}
          {members.length === 0 && (
            <div className="px-7 py-8 text-center text-sm text-white/40">
              No members yet.
            </div>
          )}
        </div>
      </Card>
    </AppShell>
  );
}

export default function AdminPage() {
  return (
    <Suspense
      fallback={
        <AppShell>
          <Spinner label="Loading" />
        </AppShell>
      }
    >
      <AdminConsole />
    </Suspense>
  );
}
