// Pluggable transactional email.
//
// There is no email provider wired by default. Until one is configured this
// logs the message (so the emulator and un-provisioned prod still work and the
// in-app flows never block on email). Set RESEND_API_KEY to send for real via
// Resend; swapping providers is a one-function change.
import { isEmulator } from "./admin";

export interface EmailMessage {
  to: string;
  subject: string;
  html: string;
  text?: string;
}

const FROM = process.env.EMAIL_FROM || "Conjur3 <noreply@conjur3.com>";

function stripHtml(html: string): string {
  return html
    .replace(/<style[\s\S]*?<\/style>/gi, "")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * Best-effort send. Never throws — returns whether it was delivered and how, so
 * callers can surface "emailed" status without failing the whole operation when
 * email isn't configured.
 */
export async function sendEmail(
  msg: EmailMessage,
): Promise<{ ok: boolean; via: string }> {
  const resendKey = process.env.RESEND_API_KEY;

  // No provider (or local emulator) → log the message instead of sending.
  // In the emulator that counts as success (flows shouldn't block on email);
  // in production it must report ok:false so the UI tells the admin to share
  // the link manually rather than claiming an email went out.
  if (!resendKey || isEmulator) {
    console.log(
      `[email:dev] to=${msg.to} subject="${msg.subject}"\n${msg.text ?? stripHtml(msg.html)}`,
    );
    return { ok: isEmulator, via: "dev-log" };
  }

  try {
    const res = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${resendKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        from: FROM,
        to: msg.to,
        subject: msg.subject,
        html: msg.html,
        text: msg.text ?? stripHtml(msg.html),
      }),
    });
    if (!res.ok) {
      console.error("[email] resend failed", res.status, await res.text());
      return { ok: false, via: "resend" };
    }
    return { ok: true, via: "resend" };
  } catch (e) {
    console.error("[email] send error", e);
    return { ok: false, via: "resend" };
  }
}

/** Shared brand wrapper for outbound HTML emails. */
export function emailLayout(title: string, bodyHtml: string): string {
  return `<div style="font-family:ui-sans-serif,system-ui,Segoe UI,Roboto,Helvetica,Arial,sans-serif;background:#0b0f14;color:#e7ecf0;padding:32px">
  <div style="max-width:520px;margin:0 auto;background:#11161d;border:1px solid rgba(255,255,255,.08);border-radius:16px;padding:28px">
    <div style="font-weight:700;letter-spacing:.04em;color:#3ee6b0;font-size:18px;margin-bottom:16px">CONJUR<span style="color:#7cc7ff">3</span></div>
    <h1 style="font-size:20px;margin:0 0 12px;color:#fff">${title}</h1>
    ${bodyHtml}
    <p style="margin-top:24px;font-size:12px;color:rgba(255,255,255,.4)">Conjur3 · autonomous parametric CAD for manufacturing</p>
  </div>
</div>`;
}
