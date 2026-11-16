// Per-key fixed-window rate limit (defense in depth against scripted abuse —
// not customer-facing metering). Fails open if Redis is unavailable.
import { redis } from "./redis";

export async function allow(keyId: string, perMin: number): Promise<boolean> {
  const k = `rl:${keyId}:${Math.floor(Date.now() / 60000)}`;
  try {
    const n = await redis.incr(k);
    if (n === 1) await redis.expire(k, 65);
    return n <= perMin;
  } catch {
    return true;
  }
}
