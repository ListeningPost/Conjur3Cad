// License-key generation + at-rest hashing.
//
// Format: CJ3-<uuid> — the "CJ3-" designation followed by a v4 UUID
// (128-bit, uppercased), e.g. CJ3-3F2A9C10-8B4E-4D2A-BF17-2C9E5A1D6E88.
// ~122 bits of randomness makes keys effectively unguessable.
//
// The plaintext code exists only in the response of the call that minted it
// (shown to the owner exactly once). Firestore stores a SHA-256 hash plus a
// short display stub (prefix + last4) so the UI can identify a key without
// ever being able to reveal it.
import { createHash, randomUUID } from "crypto";

/** A regex matching the key format (case-insensitive). */
export const KEY_REGEX =
  /^CJ3-[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$/i;

export function generateKeyCode(): string {
  return `CJ3-${randomUUID().toUpperCase()}`;
}

/** SHA-256 of the normalized (uppercased, trimmed) code, hex-encoded. */
export function hashKeyCode(code: string): string {
  return createHash("sha256").update(code.trim().toUpperCase()).digest("hex");
}

/** Display stub stored alongside the hash, e.g. { prefix: "CJ3-3F2A9C10", last4: "6E88" }. */
export function keyDisplay(code: string): { prefix: string; last4: string } {
  const c = code.trim().toUpperCase();
  return { prefix: c.slice(0, 12), last4: c.slice(-4) };
}
