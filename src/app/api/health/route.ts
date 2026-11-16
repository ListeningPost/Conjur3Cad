// Liveness/health endpoint. Reports app status and whether the optional Redis
// layer is configured and reachable.
import { NextResponse } from "next/server";
import { getRedis, redisConfigured } from "@/lib/redis";

export const dynamic = "force-dynamic";

export async function GET() {
  let redisStatus: "ok" | "down" | "disabled" = "disabled";

  if (redisConfigured()) {
    redisStatus = "down";
    const redis = getRedis();
    if (redis) {
      try {
        const pong = await redis.ping();
        if (pong === "PONG") redisStatus = "ok";
      } catch {
        redisStatus = "down";
      }
    }
  }

  return NextResponse.json({
    status: "ok",
    service: "conjur3-app",
    redis: redisStatus,
    time: new Date().toISOString(),
  });
}
