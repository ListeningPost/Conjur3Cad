import {
  sendEmailVerification,
  type ActionCodeSettings,
  type User,
} from "firebase/auth";

/**
 * Email a verification link to the given user. The link returns the user to
 * the in-app /verify-email page (which auto-detects the verified state and
 * forwards them on), so the experience stays inside the app.
 *
 * Delivery is handled by Firebase Auth itself — no external mailer required.
 * In the emulator the link is exposed via the Auth emulator's oob-codes REST
 * endpoint instead of being sent.
 */
export default async function sendVerification(
  user: User,
): Promise<{ error: unknown | null }> {
  try {
    const settings: ActionCodeSettings | undefined =
      typeof window !== "undefined"
        ? { url: `${window.location.origin}/verify-email`, handleCodeInApp: false }
        : undefined;
    const timeout = new Promise<never>((_, reject) =>
      setTimeout(() => reject(new Error("timeout")), 10_000),
    );
    await Promise.race([sendEmailVerification(user, settings), timeout]);
    return { error: null };
  } catch (error) {
    return { error };
  }
}
