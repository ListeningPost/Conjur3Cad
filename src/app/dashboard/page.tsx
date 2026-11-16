"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { doc, onSnapshot } from "firebase/firestore";
import { db } from "@/firebase/config";
import { useRequireAuth } from "@/hooks/useRequireAuth";
import { useAuthContext } from "@/context/AuthContext";
import { useFlags } from "@/hooks/useFlags";
import { useOrg } from "@/hooks/useOrg";
import {
  claimMyKey,
  rotateMyKey,
  revokeMyKey,
  deleteMyKey,
  callableError,
} from "@/lib/callables";
import { AppShell, PageHeader } from "@/components/AppShell";
import { Button, ButtonLink } from "@/components/Button";
import { Card, Chip, Spinner, Alert } from "@/components/ui";
import type { ApiKey, Membership } from "@/lib/types";

const STATUS_TONE = {
  active: "mint",
  inactive: "neutral",
  past_due: "amber",
  canceled: "amber",
} as const;

// Base URL of the hosted MCP gateway. mcp.conjur3.com has NO DNS yet
// (conjur3.com is the marketing site only), so the fallback is the live Cloud
// Run service URL — NEXT_PUBLIC_MCP_BASE_URL overrides it per environment.
// Passing CONJUR3_BASE makes the addon download + wss relay use this origin.
const MCP_BASE =
  process.env.NEXT_PUBLIC_MCP_BASE_URL ??
  "https://conjur3-mcp-eeifigkc7a-uc.a.run.app";

// AI agents the installer can register the MCP with (CONJUR3_AGENT). The
// install script auto-configures the chosen one (or prints its exact snippet).
const AGENTS = [
  { id: "claude", label: "Claude Code" },
  { id: "antigravity", label: "Google Antigravity" },
  { id: "codex", label: "OpenAI Codex" },
  { id: "hermes", label: "Hermes" },
  { id: "opencode", label: "OpenCode" },
] as const;
type AgentId = (typeof AGENTS)[number]["id"];

function installCommand(key: string, agent: AgentId): string {
  return `curl -fsSL ${MCP_BASE}/install.sh | CONJUR3_BASE=${MCP_BASE} CONJUR3_KEY=${key} CONJUR3_AGENT=${agent} bash`;
}

function AgentSelect({
  value,
  onChange,
}: {
  value: AgentId;
  onChange: (a: AgentId) => void;
}) {
  return (
    <label className="flex items-center gap-2">
      <span className="font-mono text-[0.65rem] uppercase tracking-wider text-white/50">
        Your AI agent
      </span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value as AgentId)}
        className="rounded-[var(--radius-tile)] border border-white/15 bg-ink px-2.5 py-1.5 text-xs text-paper focus:border-mint focus:outline-none"
      >
        {AGENTS.map((a) => (
          <option key={a.id} value={a.id}>
            {a.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={() => {
        navigator.clipboard?.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
      className="shrink-0 font-mono text-[0.65rem] uppercase tracking-wider text-white/50 hover:text-paper"
    >
      {copied ? "Copied ✓" : label}
    </button>
  );
}

/**
 * One organization the user belongs to: seat status plus THEIR key in it —
 * claim, recreate, invalidate, delete. A freshly minted code is shown exactly
 * once; afterwards only the prefix/last4 stub is ever visible.
 */
function OrgCard({ membership }: { membership: Membership }) {
  const { orgId, role } = membership;
  const { user, platformAdmin } = useAuthContext();
  const { stripeEnabled } = useFlags();
  const { org, loading } = useOrg(orgId);

  const [keyId, setKeyId] = useState<string | null>(null);
  const [apiKey, setApiKey] = useState<ApiKey | null>(null);
  const [freshCode, setFreshCode] = useState<string | null>(null);
  const [agent, setAgent] = useState<AgentId>("claude");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // Live member doc → which key is mine.
  useEffect(() => {
    if (!user) return;
    return onSnapshot(doc(db, "organizations", orgId, "members", user.uid), (snap) =>
      setKeyId(snap.exists() ? ((snap.get("keyId") as string) ?? null) : null),
    );
  }, [orgId, user]);

  // Live key doc (metadata only — prefix/last4/status).
  useEffect(() => {
    if (!keyId) {
      setApiKey(null);
      return;
    }
    return onSnapshot(doc(db, "organizations", orgId, "keys", keyId), (snap) =>
      setApiKey(snap.exists() ? ({ id: snap.id, ...snap.data() } as ApiKey) : null),
    );
  }, [orgId, keyId]);

  if (loading || !org) {
    return (
      <Card className="p-7">
        <Spinner label="Loading" />
      </Card>
    );
  }

  const isAdmin = role === "admin" || platformAdmin;
  const isOwner = org.ownerUid === user?.uid;
  const hasAccess = !stripeEnabled || org.status === "active";
  const seatsFree = Math.max(0, (org.seatLimit ?? 0) - (org.seatsUsed ?? 0));
  const hasActiveKey = !!apiKey && apiKey.status === "active";

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

  return (
    <Card className="p-7">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="display text-xl text-paper">{org.name}</h2>
          <div className="mt-1 flex items-center gap-2">
            <Chip tone={role === "admin" ? "aqua" : "neutral"}>{role}</Chip>
            <Chip tone={hasAccess ? "mint" : STATUS_TONE[org.status] ?? "neutral"}>
              {hasAccess ? "active" : org.status}
            </Chip>
            <span className="font-mono text-[0.65rem] uppercase tracking-wider text-white/40">
              {org.seatsUsed ?? 0}/{org.seatLimit ?? 0} seats
            </span>
          </div>
        </div>
        <div className="flex flex-wrap gap-3">
          {isAdmin && (
            <Link
              href={`/admin?org=${orgId}`}
              className="text-sm text-mint hover:underline"
            >
              Team console →
            </Link>
          )}
          {isOwner && stripeEnabled && (
            <Link href="/billing" className="text-sm text-aqua hover:underline">
              Billing →
            </Link>
          )}
        </div>
      </div>

      {error ? (
        <div className="mt-4">
          <Alert>{error}</Alert>
        </div>
      ) : null}

      {/* Show-once: the plaintext exists only in this render. */}
      {freshCode ? (
        <div className="mt-5 rounded-[var(--radius-tile)] border border-mint/40 bg-ink p-5">
          <p className="font-mono text-xs uppercase tracking-wider text-mint">
            Your new API key — copy it now
          </p>
          <p className="mt-1 text-xs text-white/50">
            For your security we only store a fingerprint. This is the only time
            the full key is shown; if you lose it, recreate it.
          </p>
          <div className="mt-3 flex items-center justify-between gap-3 rounded-[var(--radius-tile)] border border-white/10 bg-ink-3/50 px-4 py-2.5">
            <code className="break-all font-mono text-sm tracking-widest text-mint">
              {freshCode}
            </code>
            <CopyButton text={freshCode} />
          </div>
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
            <p className="text-xs text-white/50">
              Install the connector (macOS / Linux) with your key baked in — it
              registers Conjur3 with your agent too:
            </p>
            <AgentSelect value={agent} onChange={setAgent} />
          </div>
          <div className="mt-2 flex items-center justify-between gap-3">
            <pre className="grow overflow-x-auto rounded-[var(--radius-tile)] border border-white/10 bg-ink px-4 py-3 font-mono text-xs text-mint">
              {installCommand(freshCode, agent)}
            </pre>
            <CopyButton text={installCommand(freshCode, agent)} />
          </div>
          <Button className="mt-4" onClick={() => setFreshCode(null)}>
            I&apos;ve copied my key — hide it
          </Button>
        </div>
      ) : (
        <div className="mt-5">
          {!hasAccess ? (
            <p className="text-sm text-white/60">
              {isOwner
                ? "Your subscription isn't active yet. Set up seats on the Billing page."
                : "This organization's subscription isn't active. Contact your admin."}
            </p>
          ) : hasActiveKey && apiKey ? (
            <>
              <div className="flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-tile)] border border-white/10 bg-ink-3/50 px-4 py-2.5">
                <span className="flex items-center gap-3">
                  <code className="font-mono text-sm tracking-widest text-paper">
                    {apiKey.prefix}…{apiKey.last4}
                  </code>
                  <Chip tone="mint">active</Chip>
                </span>
                <span className="flex flex-wrap items-center gap-3">
                  <button
                    disabled={busy}
                    onClick={() =>
                      run(async () => {
                        const res = await rotateMyKey({ orgId });
                        setFreshCode(res.code);
                      })
                    }
                    className="font-mono text-[0.65rem] uppercase tracking-wider text-aqua hover:underline disabled:opacity-50"
                  >
                    Recreate
                  </button>
                  <button
                    disabled={busy}
                    onClick={() => run(() => revokeMyKey({ orgId }))}
                    className="font-mono text-[0.65rem] uppercase tracking-wider text-amber hover:underline disabled:opacity-50"
                  >
                    Invalidate
                  </button>
                  <button
                    disabled={busy}
                    onClick={() => run(() => deleteMyKey({ orgId }))}
                    className="font-mono text-[0.65rem] uppercase tracking-wider text-white/40 hover:text-amber disabled:opacity-50"
                  >
                    Delete
                  </button>
                </span>
              </div>
              <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
                <p className="text-xs text-white/40">
                  The full key isn&apos;t retrievable — recreate it if
                  you&apos;ve lost your copy. Install command (key goes where
                  the placeholder is):
                </p>
                <AgentSelect value={agent} onChange={setAgent} />
              </div>
              <pre className="mt-2 overflow-x-auto rounded-[var(--radius-tile)] border border-white/10 bg-ink px-4 py-3 font-mono text-xs text-mint">
                {installCommand("CJ3-…your-key…", agent)}
              </pre>
            </>
          ) : (
            <>
              {apiKey && apiKey.status === "revoked" ? (
                <div className="mb-3 flex items-center justify-between gap-3 rounded-[var(--radius-tile)] border border-white/10 bg-ink-3/50 px-4 py-2.5">
                  <span className="flex items-center gap-3">
                    <code className="font-mono text-sm tracking-widest text-white/40">
                      {apiKey.prefix}…{apiKey.last4}
                    </code>
                    <Chip tone="amber">invalidated</Chip>
                  </span>
                  <button
                    disabled={busy}
                    onClick={() => run(() => deleteMyKey({ orgId }))}
                    className="font-mono text-[0.65rem] uppercase tracking-wider text-white/40 hover:text-amber disabled:opacity-50"
                  >
                    Delete record
                  </button>
                </div>
              ) : null}
              <p className="text-sm text-white/60">
                {seatsFree > 0
                  ? "You don't have an API key here yet. Claim your seat — the key is yours alone, shown once."
                  : "No seats are free in this organization. Ask your admin for more seats."}
              </p>
              <Button
                className="mt-4"
                disabled={busy || seatsFree <= 0}
                onClick={() =>
                  run(async () => {
                    const res = await claimMyKey({ orgId });
                    setFreshCode(res.code);
                  })
                }
              >
                {busy ? "Working…" : "Claim your key →"}
              </Button>
            </>
          )}
        </div>
      )}
    </Card>
  );
}

export default function DashboardPage() {
  const { ready } = useRequireAuth();
  const { user, memberships, membershipsLoading } = useAuthContext();

  if (!ready || membershipsLoading) {
    return (
      <AppShell>
        <Spinner label="Loading" />
      </AppShell>
    );
  }

  // No organization yet → offer the two entry paths.
  if (memberships.length === 0) {
    return (
      <AppShell>
        <PageHeader kicker="Welcome" title="Get started" />
        <p className="mb-8 max-w-xl text-white/60">
          Signed in as <span className="text-paper">{user?.email}</span>.
          You&apos;re not part of an organization yet.
        </p>
        <div className="grid gap-5 md:grid-cols-2">
          <Card className="p-7">
            <h2 className="display text-xl text-paper">Have an invite?</h2>
            <p className="mt-2 text-sm text-white/60">
              Open the invite link your admin sent you (it looks like
              conjur3.web.app/invite/…) and you&apos;ll join their team instantly —
              then claim your API key right here.
            </p>
          </Card>
          <Card className="p-7">
            <h2 className="display text-xl text-paper">Start an organization</h2>
            <p className="mt-2 text-sm text-white/60">
              Become the owner, get seats, and invite your engineers.
            </p>
            <ButtonLink href="/onboarding" variant="outline" className="mt-5">
              Create org →
            </ButtonLink>
          </Card>
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <PageHeader
        kicker="Dashboard"
        title={memberships.length === 1 ? "Your organization" : "Your organizations"}
      />
      <div className="grid gap-5">
        {memberships.map((m) => (
          <OrgCard key={m.orgId} membership={m} />
        ))}
      </div>
      <p className="mt-6 text-xs text-white/40">
        Full setup (FreeCAD + connector + Claude) is in the onboarding guide.
        Need another workspace?{" "}
        <Link href="/onboarding" className="text-mint hover:underline">
          Create an organization
        </Link>
        .
      </p>
    </AppShell>
  );
}
