#!/usr/bin/env node
// One-time migration to the hashed, self-service key model (multi-org).
//
// What it does, per organization:
//   • CLAIMED keys  → rewritten as a new auto-ID doc holding only
//                     { hash, prefix, last4, status:"active", ownerUid, … };
//                     the owner's member doc keyId is repointed; the old
//                     plaintext doc is deleted. Existing users keep working —
//                     the gateway now looks keys up by hash.
//   • AVAILABLE / REVOKED pool keys → deleted (no more unclaimed codes at rest).
//   • org.seatsUsed → recomputed (= number of active keys).
// Then, per users/{uid} doc: legacy orgId / role / claimedKeyId fields are
// removed (memberships are the source of truth now). Stale custom claims are
// left in place — nothing reads them anymore.
//
// Usage (dry run by default; nothing is written without --apply):
//   GOOGLE_APPLICATION_CREDENTIALS=… node scripts/migrate-keys.mjs --project <id> [--apply]
// or with gcloud ADC:  gcloud auth application-default login
//
// Run it AFTER deploying the new functions/gateway/rules.
import { createHash } from "node:crypto";
import { createRequire } from "node:module";

const require = createRequire(new URL("../functions/package.json", import.meta.url));
const { initializeApp } = require("firebase-admin/app");
const { getFirestore, FieldValue } = require("firebase-admin/firestore");

const args = process.argv.slice(2);
const apply = args.includes("--apply");
const projectIdx = args.indexOf("--project");
const projectId = projectIdx >= 0 ? args[projectIdx + 1] : process.env.GOOGLE_CLOUD_PROJECT;
if (!projectId) {
  console.error("Usage: node scripts/migrate-keys.mjs --project <id> [--apply]");
  process.exit(1);
}

initializeApp({ projectId });
const db = getFirestore();

const sha256 = (s) => createHash("sha256").update(s.trim().toUpperCase()).digest("hex");
const act = apply ? "APPLY" : "dry-run";
let migrated = 0;
let deleted = 0;
let skipped = 0;

const orgs = await db.collection("organizations").get();
console.log(`[${act}] ${orgs.size} organization(s) in ${projectId}\n`);

for (const org of orgs.docs) {
  const keys = await org.ref.collection("keys").get();
  let active = 0;

  for (const key of keys.docs) {
    const data = key.data();

    if (data.hash && !data.code) {
      // Already in the new shape.
      if (data.status === "active") active++;
      skipped++;
      continue;
    }

    const code = typeof data.code === "string" ? data.code.trim().toUpperCase() : null;

    if (data.status === "claimed" && data.claimedByUid && code) {
      const ownerUid = data.claimedByUid;
      const memberRef = org.ref.collection("members").doc(ownerUid);
      const memberSnap = await memberRef.get();
      const newRef = org.ref.collection("keys").doc();
      console.log(
        `  [migrate] ${org.id}/${key.id} → ${newRef.id} (owner ${ownerUid}, ${code.slice(0, 12)}…${code.slice(-4)})`,
      );
      if (apply) {
        const batch = db.batch();
        batch.set(newRef, {
          hash: sha256(code),
          prefix: code.slice(0, 12),
          last4: code.slice(-4),
          status: "active",
          ownerUid,
          ownerEmail: memberSnap.exists ? (memberSnap.get("email") ?? null) : null,
          createdAt: data.claimedAt ?? data.createdAt ?? FieldValue.serverTimestamp(),
          rotatedAt: null,
          migratedFrom: key.id,
        });
        if (memberSnap.exists) batch.update(memberRef, { keyId: newRef.id });
        batch.delete(key.ref);
        await batch.commit();
      }
      active++;
      migrated++;
    } else {
      // Unclaimed pool / revoked / malformed → no longer representable, delete.
      console.log(`  [delete ] ${org.id}/${key.id} (status=${data.status ?? "?"})`);
      if (apply) await key.ref.delete();
      deleted++;
    }
  }

  const seatsUsed = org.get("seatsUsed") ?? 0;
  if (seatsUsed !== active) {
    console.log(`  [seats  ] ${org.id}: seatsUsed ${seatsUsed} → ${active}`);
    if (apply) await org.ref.update({ seatsUsed: active });
  }
}

// Strip legacy single-org fields off user profiles.
const users = await db.collection("users").get();
let cleaned = 0;
for (const user of users.docs) {
  const d = user.data();
  if ("orgId" in d || "role" in d || "claimedKeyId" in d) {
    cleaned++;
    if (apply) {
      await user.ref.update({
        orgId: FieldValue.delete(),
        role: FieldValue.delete(),
        claimedKeyId: FieldValue.delete(),
      });
    }
  }
}

console.log(
  `\n[${act}] done: ${migrated} key(s) migrated, ${deleted} pool key(s) deleted, ${skipped} already migrated, ${cleaned} user doc(s) cleaned.`,
);
if (!apply) console.log("Re-run with --apply to write these changes.");
