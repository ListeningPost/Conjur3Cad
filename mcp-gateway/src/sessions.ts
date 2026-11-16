// Single live session per seat key, newest-wins (the session started first is
// killed). The "active session" for a key is the current MCP session id
// (mcp-session-id). Taking over atomically swaps the pointer and evicts the
// previous session — both by closing its live connection and by making its
// next request fail the isActive() check.
//
// Cross-instance safe: evictions are broadcast over Redis pub/sub so whichever
// gateway node holds the deposed connection closes it. On a single VM the local
// registry alone suffices; pub/sub makes horizontal scaling a config flip.
import { redis, subscriber, EVICT_CHANNEL } from "./redis";
import { config } from "./config";
import { log } from "./logger";

const seatKey = (keyId: string) => `seat:${keyId}:active`;

// msid -> close the live connection (e.g., end the SSE stream) on this node.
const localConns = new Map<string, () => void>();

subscriber.subscribe(EVICT_CHANNEL).catch((e) => log.error("subscribe failed", { err: String(e) }));
subscriber.on("message", (channel, msid) => {
  if (channel === EVICT_CHANNEL) evictLocal(msid, "remote");
});

function evictLocal(msid: string, reason: string) {
  const close = localConns.get(msid);
  if (close) {
    localConns.delete(msid);
    try {
      close();
    } catch {
      /* connection already gone */
    }
    log.audit("session.evicted", { msid, reason });
  }
}

/**
 * Make `msid` the sole active session for `keyId`. Returns the deposed session
 * id (if any), which has been evicted.
 */
export async function activateSession(
  keyId: string,
  msid: string,
): Promise<string | null> {
  // Atomic set-and-return-previous with TTL (Redis 6.2+ SET ... GET).
  const prev = (await redis.set(
    seatKey(keyId),
    msid,
    "EX",
    config.sessionTtlSeconds,
    "GET",
  )) as string | null;

  if (prev && prev !== msid && config.singleSession) {
    evictLocal(prev, "takeover");
    redis.publish(EVICT_CHANNEL, prev).catch(() => {});
    log.audit("session.takeover", { keyId, deposed: prev, active: msid });
  } else {
    log.audit("session.started", { keyId, msid });
  }
  return prev && prev !== msid ? prev : null;
}

/** True if `msid` is still the active session for `keyId`; refreshes the TTL. */
export async function isActiveSession(
  keyId: string,
  msid: string,
): Promise<boolean> {
  const cur = await redis.get(seatKey(keyId));
  if (cur === msid) {
    await redis.expire(seatKey(keyId), config.sessionTtlSeconds);
    return true;
  }
  return false;
}

/** Register how to close a session's live connection on this node. */
export function registerConnection(msid: string, close: () => void) {
  localConns.set(msid, close);
}

export function unregisterConnection(msid: string) {
  localConns.delete(msid);
}

/** Release a seat when its session ends cleanly. */
export async function releaseSession(keyId: string, msid: string) {
  unregisterConnection(msid);
  const cur = await redis.get(seatKey(keyId));
  if (cur === msid) {
    await redis.del(seatKey(keyId));
    log.audit("session.released", { keyId, msid });
  }
}
