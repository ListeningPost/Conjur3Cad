"use client";
import { useEffect, useState } from "react";
import { doc, onSnapshot } from "firebase/firestore";
import { db } from "@/firebase/config";
import type { Organization } from "@/lib/types";

/** Live-subscribe to an organization document. */
export function useOrg(orgId: string | null) {
  const [org, setOrg] = useState<Organization | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!orgId) {
      setOrg(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    const unsub = onSnapshot(
      doc(db, "organizations", orgId),
      (snap) => {
        setOrg(snap.exists() ? ({ id: snap.id, ...snap.data() } as Organization) : null);
        setLoading(false);
      },
      () => setLoading(false),
    );
    return () => unsub();
  }, [orgId]);

  return { org, loading };
}
