import { createApp } from "./server";
import { config } from "./config";
import { redis, subscriber } from "./redis";
import { attachRelay } from "./relay";
import { log } from "./logger";

const app = createApp();
const server = app.listen(config.port, () => {
  log.info("mcp-gateway listening", {
    port: config.port,
    upstream: config.upstreamMcpUrl,
    relayRpcPort: config.relayRpcPort,
    emulator: !!config.firestoreEmulatorHost,
  });
});

// Connector tunnel (/connector ws) + the loopback RPC forwarder conjur3-pilot
// points at, so the hosted MCP can drive the user's local FreeCAD.
attachRelay(server, config.relayRpcPort, config.relayRpcHost);

async function shutdown(sig: string) {
  log.info("shutting down", { sig });
  server.close();
  await Promise.allSettled([redis.quit(), subscriber.quit()]);
  process.exit(0);
}
process.on("SIGTERM", () => void shutdown("SIGTERM"));
process.on("SIGINT", () => void shutdown("SIGINT"));
