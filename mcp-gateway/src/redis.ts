// Redis connections. We keep a normal client (commands) plus a dedicated
// subscriber (a Redis connection in subscribe mode can't run other commands),
// used to broadcast session evictions across gateway instances.
import Redis from "ioredis";
import { config } from "./config";
import { log } from "./logger";

export const redis = new Redis(config.redisUrl, {
  maxRetriesPerRequest: 2,
  enableOfflineQueue: true,
});
export const subscriber = new Redis(config.redisUrl, {
  maxRetriesPerRequest: null,
});

redis.on("error", (e) => log.error("redis error", { err: e.message }));
subscriber.on("error", (e) => log.error("redis sub error", { err: e.message }));

export const EVICT_CHANNEL = "mcpgw:evict";
