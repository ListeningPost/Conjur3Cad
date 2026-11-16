#!/usr/bin/env node
// Delete all Firebase Auth users and their Firestore data EXCEPT the given
// keep list (--keep a@x.com,b@y.com or KEEP_EMAILS; required).
//
// Usage (dry-run by default):
//   GOOGLE_APPLICATION_CREDENTIALS=path/to/sa.json \
//     node scripts/cleanup-test-users.mjs --project <projectId> --keep you@example.com [--apply]
// or with gcloud ADC:
//   gcloud auth application-default login
//   node scripts/cleanup-test-users.mjs --project <projectId> --keep you@example.com [--apply]
import { createRequire } from "node:module";

const require = createRequire(new URL("../functions/package.json", import.meta.url));
const { initializeApp, cert, applicationDefault } = require("firebase-admin/app");
const { getAuth } = require("firebase-admin/auth");
const { getFirestore } = require("firebase-admin/firestore");

const args = process.argv.slice(2);
const apply = args.includes("--apply");
const projectIdx = args.indexOf("--project");
const projectId = projectIdx >= 0 ? args[projectIdx + 1] : process.env.GCLOUD_PROJECT;
const keepIdx = args.indexOf("--keep");
const keepEmails = new Set(
  (keepIdx >= 0 ? args[keepIdx + 1] : process.env.KEEP_EMAILS ?? "")
    .split(",")
    .map((e) => e.trim().toLowerCase())
    .filter(Boolean),
);

if (keepEmails.size === 0) {
  console.error("Pass --keep <email[,email…]> or set KEEP_EMAILS (refusing to delete every user).");
  process.exit(1);
}

if (!projectId) {
  console.error("Pass --project <id> or set GCLOUD_PROJECT");
  process.exit(1);
}

const credential = process.env.GOOGLE_APPLICATION_CREDENTIALS
  ? cert(process.env.GOOGLE_APPLICATION_CREDENTIALS)
  : applicationDefault();

initializeApp({ credential, projectId });
const auth = getAuth();
const db = getFirestore();

async function listAllUsers() {
  const users = [];
  let pageToken;
  do {
    const page = await auth.listUsers(1000, pageToken);
    users.push(...page.users);
    pageToken = page.pageToken;
  } while (pageToken);
  return users;
}

async function deleteUserData(uid) {
  // Delete users/{uid}
  await db.doc(`users/${uid}`).delete().catch(() => {});

  // Delete the user from any org memberships, and clean up orgs they own.
  const memberSnaps = await db.collectionGroup("members").where("uid", "==", uid).get();
  for (const memberDoc of memberSnaps.docs) {
    const orgRef = memberDoc.ref.parent.parent;
    if (!orgRef) continue;
    const orgDoc = await orgRef.get();
    if (orgDoc.exists && orgDoc.get("ownerUid") === uid) {
      // Delete the entire org + subcollections if this user is the owner.
      await db.recursiveDelete(orgRef);
      console.log(`  [firestore] deleted org ${orgRef.id} (owner was ${uid})`);
    } else {
      await memberDoc.ref.delete();
      console.log(`  [firestore] removed member ${uid} from org ${orgRef.id}`);
    }
  }

  // Clean up guided invite redemptions.
  const giRedemptions = await db.collectionGroup("redemptions").where("uid", "==", uid).get();
  for (const doc of giRedemptions.docs) {
    if (apply) await doc.ref.delete();
    console.log(`  [firestore] ${apply ? "deleted" : "would delete"} redemption ${doc.ref.path}`);
  }
}

const users = await listAllUsers();
const toDelete = users.filter((u) => !keepEmails.has((u.email ?? "").toLowerCase()));

console.log(`\nFound ${users.length} total users, ${toDelete.length} to delete (keeping: ${[...keepEmails].join(", ")})\n`);

if (!apply) {
  for (const u of toDelete) {
    console.log(`  would delete: ${u.email ?? "(no email)"} [${u.uid}]`);
  }
  console.log("\nDry run — pass --apply to execute.\n");
  process.exit(0);
}

for (const u of toDelete) {
  console.log(`Deleting ${u.email ?? "(no email)"} [${u.uid}]…`);
  await deleteUserData(u.uid);
  await auth.deleteUser(u.uid);
  console.log(`  [auth] deleted`);
}

console.log(`\nDone. Deleted ${toDelete.length} user(s).`);
