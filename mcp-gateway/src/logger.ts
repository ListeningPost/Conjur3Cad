// Minimal structured logger. Audit events are just log lines with event names.
// Every line goes to stdout (Cloud Run's built-in log tail); audit/warn/error
// additionally ship to the self-hosted OTLP backend over the tailnet when
// TELEMETRY_URL is set (see telemetry.ts) — no BigQuery, no paid log sinks.
import { enqueue } from "./telemetry";

type Fields = Record<string, unknown>;

function emit(level: string, msg: string, fields?: Fields) {
  const line = { ts: new Date().toISOString(), level, msg, ...fields };
  // eslint-disable-next-line no-console
  console.log(JSON.stringify(line));
  enqueue(level, msg, fields);
}

export const log = {
  info: (msg: string, f?: Fields) => emit("info", msg, f),
  warn: (msg: string, f?: Fields) => emit("warn", msg, f),
  error: (msg: string, f?: Fields) => emit("error", msg, f),
  /** Security/usage audit trail (session start, takeover, deny, revoke). */
  audit: (event: string, f?: Fields) => emit("audit", event, { event, ...f }),
};
