"use client";
import { useEffect, useState } from "react";
import { doc, onSnapshot } from "firebase/firestore";
import { db } from "@/firebase/config";

export interface Flags {
  stripeEnabled: boolean;
}

const DEFAULTS: Flags = { stripeEnabled: false };

/** Live runtime feature flags from Firestore config/flags. */
export function useFlags(): Flags {
  const [flags, setFlags] = useState<Flags>(DEFAULTS);
  useEffect(() => {
    const unsub = onSnapshot(
      doc(db, "config", "flags"),
      (snap) => setFlags({ ...DEFAULTS, ...(snap.data() as Partial<Flags>) }),
      () => setFlags(DEFAULTS),
    );
    return () => unsub();
  }, []);
  return flags;
}
