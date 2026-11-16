// Runtime feature flags, stored in Firestore at config/flags and read live by
// the client. Functions cache them briefly to avoid a read per call.
import { db } from "./admin";

export interface Flags {
  stripeEnabled: boolean;
}

const DEFAULTS: Flags = { stripeEnabled: false };

let cache: { at: number; flags: Flags } | null = null;
const TTL_MS = 30_000;

export async function getFlags(): Promise<Flags> {
  if (cache && Date.now() - cache.at < TTL_MS) return cache.flags;
  let flags = DEFAULTS;
  try {
    const snap = await db.doc("config/flags").get();
    if (snap.exists) flags = { ...DEFAULTS, ...(snap.data() as Partial<Flags>) };
  } catch {
    /* fall back to defaults */
  }
  cache = { at: Date.now(), flags };
  return flags;
}
