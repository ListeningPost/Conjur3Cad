// Centralized config, read from the environment with sane defaults so the
// gateway runs locally with zero setup against the emulator + a local Redis.
function num(v: string | undefined, d: number): number {
  const n = Number(v);
  return Number.isFinite(n) ? n : d;
}

export const config = {
  port: num(process.env.PORT, 8080),
  upstreamMcpUrl: process.env.UPSTREAM_MCP_URL ?? "http://localhost:8765/mcp",
  redisUrl: process.env.REDIS_URL ?? "redis://localhost:6379",
  firebaseProjectId: process.env.FIREBASE_PROJECT_ID ?? "demo-conjur3",
  firestoreEmulatorHost: process.env.FIRESTORE_EMULATOR_HOST, // set => emulator
  sessionTtlSeconds: num(process.env.SESSION_TTL_SECONDS, 90),
  rateLimitPerMin: num(process.env.RATE_LIMIT_PER_MIN, 240),
  // Single live session per key. OFF by default (multiple sessions allowed);
  // flip SINGLE_SESSION=true to re-enable evict-oldest.
  singleSession: process.env.SINGLE_SESSION === "true",
  // CORS allow-origin for browser MCP clients (e.g. claude.ai connectors).
  // "*" for open testing; set a specific origin (e.g. https://claude.ai) for prod.
  corsOrigin: process.env.CORS_ORIGIN ?? "*",
  // Port the relay exposes as a fake FreeCAD addon (conjur3-pilot connects here
  // with --host <relayRpcHost> --port <this>). Host is 127.0.0.1 locally; set
  // 0.0.0.0 in Docker so the sibling MCP container can reach it.
  relayRpcPort: num(process.env.RELAY_RPC_PORT, 9000),
  relayRpcHost: process.env.RELAY_RPC_HOST ?? "127.0.0.1",
  isProd: process.env.NODE_ENV === "production",
  // Self-hosted observability (OTLP/HTTP over the tailnet) — see telemetry.ts.
  // Unset = disabled; stdout JSON logging is always on regardless.
  telemetryUrl: process.env.TELEMETRY_URL?.replace(/\/$/, ""),
  telemetryToken: process.env.TELEMETRY_TOKEN,
  telemetryProxy: process.env.TELEMETRY_PROXY,
};

// The upstream split into origin + path for the proxy target / path rewrite.
const u = new URL(config.upstreamMcpUrl);
export const upstream = {
  origin: u.origin, // e.g. http://localhost:8765
  path: u.pathname, // e.g. /mcp
};
