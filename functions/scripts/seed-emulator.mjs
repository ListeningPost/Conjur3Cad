// Seed the Firebase emulators with runtime config only — NO account credentials.
//
//   npm --prefix functions run seed
//
// Sets feature flags (config/flags). It deliberately creates no users, orgs, or
// keys: real people sign up in the app, and emails listed in
// PLATFORM_ADMIN_EMAILS (functions/.env.<projectId>) become platform admins
// automatically on sign-up with a verified email. Emulator only — refuses real
// projects.
import { initializeApp, getApps } from "firebase-admin/app";
import { getFirestore } from "firebase-admin/firestore";

const PROJECT = process.env.FIREBASE_PROJECT_ID || "demo-conjur3";
process.env.FIRESTORE_EMULATOR_HOST ||= "127.0.0.1:8088";

if (!PROJECT.startsWith("demo-")) {
  console.error(`Refusing to seed non-demo project "${PROJECT}".`);
  process.exit(1);
}

const app = getApps()[0] ?? initializeApp({ projectId: PROJECT });
const db = getFirestore(app);

async function main() {
  // Feature flags — Stripe disabled for now. While off, only platform admins
  // mint keys (see functions/src/seatKeys.ts).
  await db.doc("config/flags").set({ stripeEnabled: false }, { merge: true });

  console.log("✓ Seeded config/flags (stripeEnabled=false) on", PROJECT);
  console.log("  No accounts seeded — sign up in the app to create your account/org.");
  console.log("  Emails in PLATFORM_ADMIN_EMAILS become platform admins on verified sign-up.");
  process.exit(0);
}

main().catch((e) => {
  console.error("seed failed:", e?.message ?? e);
  process.exit(1);
});
