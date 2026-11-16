// Self-hosted telemetry shipper — OTLP/HTTP logs to YOUR box, not BigQuery.
//
// Ships the gateway's structured log events (audit/warn/error) as standard
// OpenTelemetry log records to any OTLP/HTTP endpoint: SigNoz, OpenObserve,
// Grafana Alloy / OTel Collector, etc. Designed for an ON-PREM device reached
// over a TAILNET:
//
//   TELEMETRY_URL    e.g. http://obsbox.tail1234.ts.net:4318   (OTLP base; we
//                    POST to ${TELEMETRY_URL}/v1/logs)
//   TELEMETRY_TOKEN  optional — sent as Authorization: Bearer … AND
//                    signoz-access-token (harmless to whichever backend)
//   TELEMETRY_PROXY  optional HTTP proxy. When the container runs tailscaled in
//                    userspace mode (see Dockerfile entrypoint), this is
//                    http://localhost:1055 and MagicDNS names resolve inside
//                    the tailnet — no public exposure anywhere.
//
// Fail-open by design: a bounded queue, batched flushes, and errors that only
// ever log locally. Telemetry must never take the gateway down. stdout JSON
// logging is unchanged (Cloud Run's free log tail still works for debugging).
import { fetch as undiciFetch, ProxyAgent, type Dispatcher } from "undici";
import { config } from "./config";

type Fields = Record<string, unknown>;

const MAX_QUEUE = 1000; // drop-oldest beyond this
const FLUSH_EVERY_MS = 5_000;
const FLUSH_AT = 200; // early flush when the batch is this big
const SHIP_LEVELS = new Set(
  (process.env.TELEMETRY_LEVELS ?? "audit,warn,error")
    .split(",")
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean),
);

const SEVERITY: Record<string, { num: number; text: string }> = {
  info: { num: 9, text: "INFO" },
  audit: { num: 9, text: "INFO" },
  warn: { num: 13, text: "WARN" },
  error: { num: 17, text: "ERROR" },
};

interface LogRecord {
  timeUnixNano: string;
  severityNumber: number;
  severityText: string;
  body: { stringValue: string };
  attributes: { key: string; value: Record<string, unknown> }[];
}

function anyValue(v: unknown): Record<string, unknown> {
  switch (typeof v) {
    case "string":
      return { stringValue: v };
    case "number":
      return Number.isInteger(v) ? { intValue: String(v) } : { doubleValue: v };
    case "boolean":
      return { boolValue: v };
    default:
      return { stringValue: JSON.stringify(v) };
  }
}

const queue: LogRecord[] = [];
let dropped = 0;
let lastErrorAt = 0;
let dispatcher: Dispatcher | undefined;
if (config.telemetryProxy) {
  dispatcher = new ProxyAgent(config.telemetryProxy);
}

const RESOURCE = {
  attributes: [
    { key: "service.name", value: { stringValue: process.env.TELEMETRY_SERVICE_NAME ?? "conjur3-mcp-gateway" } },
    { key: "deployment.environment", value: { stringValue: config.isProd ? "production" : "development" } },
  ],
};

/** Queue one log event for shipping. No-op unless TELEMETRY_URL is set. */
export function enqueue(level: string, msg: string, fields?: Fields): void {
  if (!config.telemetryUrl || !SHIP_LEVELS.has(level)) return;
  const sev = SEVERITY[level] ?? SEVERITY.info;
  queue.push({
    timeUnixNano: `${Date.now()}000000`,
    severityNumber: sev.num,
    severityText: sev.text,
    body: { stringValue: msg },
    attributes: [
      { key: "log.level", value: { stringValue: level } },
      ...Object.entries(fields ?? {}).map(([key, v]) => ({ key, value: anyValue(v) })),
    ],
  });
  if (queue.length > MAX_QUEUE) {
    queue.splice(0, queue.length - MAX_QUEUE);
    dropped++;
  }
  if (queue.length >= FLUSH_AT) void flush();
}

let flushing = false;
async function flush(): Promise<void> {
  if (flushing || queue.length === 0 || !config.telemetryUrl) return;
  flushing = true;
  const batch = queue.splice(0, queue.length);
  try {
    const headers: Record<string, string> = { "content-type": "application/json" };
    if (config.telemetryToken) {
      headers.authorization = `Bearer ${config.telemetryToken}`;
      headers["signoz-access-token"] = config.telemetryToken;
    }
    const res = await undiciFetch(`${config.telemetryUrl}/v1/logs`, {
      method: "POST",
      headers,
      dispatcher,
      body: JSON.stringify({
        resourceLogs: [
          {
            resource: RESOURCE,
            scopeLogs: [{ scope: { name: "conjur3-gateway" }, logRecords: batch }],
          },
        ],
      }),
      signal: AbortSignal.timeout(10_000),
    });
    if (!res.ok) throw new Error(`OTLP ingest HTTP ${res.status}`);
    if (dropped > 0) {
      // eslint-disable-next-line no-console
      console.warn(`[telemetry] queue overflowed earlier; dropped ${dropped} record(s)`);
      dropped = 0;
    }
  } catch (err) {
    // Fail-open: put the batch back (bounded) and rate-limit the local warning.
    queue.unshift(...batch.slice(-MAX_QUEUE));
    const now = Date.now();
    if (now - lastErrorAt > 60_000) {
      lastErrorAt = now;
      // eslint-disable-next-line no-console
      console.warn(`[telemetry] ship failed (will retry): ${(err as Error).message}`);
    }
  } finally {
    flushing = false;
  }
}

if (config.telemetryUrl) {
  const timer = setInterval(() => void flush(), FLUSH_EVERY_MS);
  timer.unref(); // never keep the process alive for telemetry
  process.on("beforeExit", () => void flush());
  // eslint-disable-next-line no-console
  console.log(
    `[telemetry] shipping ${[...SHIP_LEVELS].join("/")} events → ${config.telemetryUrl}/v1/logs${config.telemetryProxy ? ` via ${config.telemetryProxy}` : ""}`,
  );
}
