// Firebase web SDK initialization for the Conjur3 app.
//
// Exports singletons for the services the app uses (auth, Firestore, callable
// functions) and, in development, connects them to the local emulator suite
// when NEXT_PUBLIC_USE_EMULATORS === "true".
import { initializeApp, getApps, getApp, type FirebaseApp } from "firebase/app";
import { getAuth, connectAuthEmulator, type Auth } from "firebase/auth";
import {
  getFirestore,
  connectFirestoreEmulator,
  type Firestore,
} from "firebase/firestore";
import {
  getFunctions,
  connectFunctionsEmulator,
  type Functions,
} from "firebase/functions";

const firebaseConfig = {
  apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY,
  authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN,
  projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
  storageBucket: process.env.NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: process.env.NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID,
  appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID,
};

const useEmulators = process.env.NEXT_PUBLIC_USE_EMULATORS === "true";

// Reuse the app across HMR / multiple imports.
const firebaseApp: FirebaseApp =
  getApps().length === 0 ? initializeApp(firebaseConfig) : getApp();

const auth: Auth = getAuth(firebaseApp);
const db: Firestore = getFirestore(firebaseApp);
const functions: Functions = getFunctions(firebaseApp, "us-central1");

// Connect to the emulator suite exactly once, on the client only.
declare global {
  // eslint-disable-next-line no-var
  var __CONJUR3_EMULATORS_CONNECTED__: boolean | undefined;
}

if (
  useEmulators &&
  typeof window !== "undefined" &&
  !globalThis.__CONJUR3_EMULATORS_CONNECTED__
) {
  globalThis.__CONJUR3_EMULATORS_CONNECTED__ = true;
  connectAuthEmulator(auth, "http://127.0.0.1:9099", { disableWarnings: true });
  connectFirestoreEmulator(db, "127.0.0.1", 8088);
  connectFunctionsEmulator(functions, "127.0.0.1", 5001);
}

export default firebaseApp;
export { firebaseApp, auth, db, functions, useEmulators };
