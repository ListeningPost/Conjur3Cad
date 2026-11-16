# Conjur3 Connector

The tiny local bridge that lets the **hosted** Conjur3 MCP drive **your** FreeCAD.
It dials out to the relay (no inbound ports), authenticates with your seat key,
and forwards each request to your local FreeCAD addon — then streams the result
back. It contains **no product logic**; the MCP commands/code/knowledge stay on
Conjur3's server.

```
hosted MCP ──relay(wss)──▶ connector ──HTTP──▶ FreeCAD addon (127.0.0.1:9875)
```

## Run
```bash
npm install && npm run build
CONJUR3_KEY=CJ3-XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX \
node dist/index.js --relay wss://mcp.conjur3.com --local http://127.0.0.1:9875
```

| flag / env | default | meaning |
|---|---|---|
| `--key` / `CONJUR3_KEY` | — | your seat key (required) |
| `--relay` / `CONJUR3_RELAY` | `ws://127.0.0.1:8090` | the Conjur3 relay endpoint |
| `--local` / `CONJUR3_LOCAL` | `http://127.0.0.1:9875` | your local FreeCAD addon RPC |

Then point your AI client at the hosted MCP:
```bash
claude mcp add conjur3 --transport http https://mcp.conjur3.com/mcp \
  --header "Authorization: Bearer CJ3-XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX"
```

A second connector (or MCP session) on the same key evicts the first — one live
session per seat.
