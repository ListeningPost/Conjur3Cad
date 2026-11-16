// Tiny cache-aside helper over the optional Redis client. Server-only.
import "server-only";
import { getRedis } from "./redis";

/**
 * Return the cached JSON value for `key`, or compute it with `loader`, cache
 * it for `ttlSeconds`, and return it. Transparently bypasses the cache when
 * Redis is unavailable.
 */
export async function getOrSet<T>(
  key: string,
  ttlSeconds: number,
  loader: () => Promise<T>,
): Promise<T> {
  const redis = getRedis();
  if (!redis) return loader();

  try {
    const hit = await redis.get(`cache:${key}`);
    if (hit) return JSON.parse(hit) as T;
  } catch {
    /* fall through to loader */
  }

  const value = await loader();
  try {
    await redis.set(`cache:${key}`, JSON.stringify(value), "EX", ttlSeconds);
  } catch {
    /* best effort */
  }
  return value;
}

/** Invalidate a cached key (best effort). */
export async function invalidate(key: string): Promise<void> {
  const redis = getRedis();
  if (!redis) return;
  try {
    await redis.del(`cache:${key}`);
  } catch {
    /* best effort */
  }
}
