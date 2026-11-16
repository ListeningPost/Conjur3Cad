// Lazy, OPTIONAL Redis client for the Next.js server layer.
//
// The app must run with or without Redis. If REDIS_URL is unset, or a
// connection can't be established, getRedis() returns null and callers should
// degrade gracefully (skip caching, fail-open on rate limits). Server-only —
// never import from a client component.
import "server-only";
import Redis from "ioredis";

let client: Redis | null | undefined; // undefined = not yet initialized

export function getRedis(): Redis | null {
  if (client !== undefined) return client;

  const url = process.env.REDIS_URL;
  if (!url) {
    client = null;
    return null;
  }

  try {
    client = new Redis(url, {
      lazyConnect: false,
      maxRetriesPerRequest: 1,
      // Don't crash the server on a flaky cache; back off and keep going.
      retryStrategy: (times) => (times > 3 ? null : Math.min(times * 200, 1000)),
      enableOfflineQueue: false,
    });
    client.on("error", (err) => {
      // Avoid noisy crashes; log once per error tick.
      console.warn("[redis] connection error:", err.message);
    });
  } catch (err) {
    console.warn("[redis] init failed:", (err as Error).message);
    client = null;
  }
  return client;
}

/** True when a Redis instance is configured (not necessarily connected). */
export function redisConfigured(): boolean {
  return !!process.env.REDIS_URL;
}
