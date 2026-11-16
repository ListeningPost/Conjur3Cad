// Firebase Admin — the source of truth for license keys, orgs, and seats.
//
// On a GCP VM, attach a service account and Application Default Credentials are
// used automatically (no key file). Locally, set FIRESTORE_EMULATOR_HOST to hit
// the emulator. initializeApp() with just a projectId is all that's needed.
import { initializeApp, getApps, applicationDefault } from "firebase-admin/app";
import { getFirestore } from "firebase-admin/firestore";
import { config } from "./config";

if (config.firestoreEmulatorHost) {
  // Admin SDK reads FIRESTORE_EMULATOR_HOST from env automatically; ensure set.
  process.env.FIRESTORE_EMULATOR_HOST = config.firestoreEmulatorHost;
}

const app =
  getApps()[0] ??
  initializeApp({
    projectId: config.firebaseProjectId,
    // Skip real creds when talking to the emulator.
    ...(config.firestoreEmulatorHost
      ? {}
      : { credential: applicationDefault() }),
  });

export const db = getFirestore(app);
