"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { doc, getDoc } from "firebase/firestore";
import { db } from "@/firebase/config";
import { useRequireAuth } from "@/hooks/useRequireAuth";
import { useAuthContext } from "@/context/AuthContext";
import { deleteSelf, callableError } from "@/lib/callables";
import { AppShell, PageHeader } from "@/components/AppShell";
import { Button } from "@/components/Button";
import { Card, Alert, Spinner } from "@/components/ui";

export default function AccountPage() {
  // Allow even an unverified user to remove their own account.
  const { ready } = useRequireAuth({ allowUnverified: true });
  const { user, memberships, logout } = useAuthContext();
  const router = useRouter();

  const [ownedOrgNames, setOwnedOrgNames] = useState<string[]>([]);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // Which of the user's orgs do they OWN? Those get erased with the account.
  useEffect(() => {
    let active = true;
    if (!user || memberships.length === 0) {
      setOwnedOrgNames([]);
      return;
    }
    Promise.all(
      memberships.map(async (m) => {
        try {
          const snap = await getDoc(doc(db, "organizations", m.orgId));
          return snap.exists() && snap.get("ownerUid") === user.uid
            ? ((snap.get("name") as string) ?? m.orgId)
            : null;
        } catch {
          return null;
        }
      }),
    ).then((names) => {
      if (active) setOwnedOrgNames(names.filter((n): n is string => n !== null));
    });
    return () => {
      active = false;
    };
  }, [user, memberships]);

  if (!ready) {
    return (
      <AppShell>
        <Spinner label="Loading" />
      </AppShell>
    );
  }

  const memberOnly = memberships.length - ownedOrgNames.length;
  let warning: string;
  if (memberships.length === 0) {
    warning = "Your account will be permanently deleted.";
  } else {
    const parts: string[] = ["Your account will be permanently deleted"];
    if (ownedOrgNames.length > 0) {
      parts.push(
        `the organization${ownedOrgNames.length === 1 ? "" : "s"} you own (${ownedOrgNames.join(", ")}) will be erased — other members keep their accounts`,
      );
    }
    if (memberOnly > 0) {
      parts.push(
        `your seat${memberOnly === 1 ? "" : "s"} in ${memberOnly} other organization${memberOnly === 1 ? "" : "s"} will be freed`,
      );
    }
    warning = parts.join("; ") + ".";
  }

  async function handleDelete() {
    setBusy(true);
    setError("");
    try {
      await deleteSelf({});
      await logout();
      router.push("/");
    } catch (e) {
      setError(callableError(e));
      setBusy(false);
    }
  }

  return (
    <AppShell>
      <PageHeader kicker="Account" title="Account settings" />
      <Card className="border border-amber/30 p-7">
        <h2 className="display text-lg text-amber">Delete account</h2>
        <p className="mt-2 text-sm text-white/60">
          Signed in as <span className="text-paper">{user?.email}</span>.
        </p>
        <div className="mt-4">
          <Alert tone="error">{warning} This can&apos;t be undone.</Alert>
        </div>
        {error ? (
          <div className="mt-3">
            <Alert>{error}</Alert>
          </div>
        ) : null}
        {!confirming ? (
          <Button variant="danger" className="mt-5" onClick={() => setConfirming(true)}>
            Delete my account
          </Button>
        ) : (
          <div className="mt-5 flex flex-wrap gap-3">
            <Button variant="danger" disabled={busy} onClick={handleDelete}>
              {busy ? "Deleting…" : "Yes, permanently delete"}
            </Button>
            <Button variant="ghost" disabled={busy} onClick={() => setConfirming(false)}>
              Cancel
            </Button>
          </div>
        )}
      </Card>
    </AppShell>
  );
}
