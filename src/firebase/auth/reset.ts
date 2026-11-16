import {
  sendPasswordResetEmail,
  type ActionCodeSettings,
} from "firebase/auth";
import { auth } from "@/firebase/config";

/**
 * Email a password-reset link. Firebase Auth sends and hosts the reset page
 * itself (no external mailer); the link returns the user to /signin afterwards.
 * In the emulator the link is exposed via the Auth emulator's oob-codes endpoint.
 */
export default async function sendReset(
  email: string,
): Promise<{ error: unknown | null }> {
  try {
    const settings: ActionCodeSettings | undefined =
      typeof window !== "undefined"
        ? { url: `${window.location.origin}/signin` }
        : undefined;
    await sendPasswordResetEmail(auth, email, settings);
    return { error: null };
  } catch (error) {
    return { error };
  }
}
