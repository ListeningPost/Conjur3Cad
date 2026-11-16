# Conjur3 — Setup (connect your AI client to your FreeCAD)

Conjur3 hosts the CAD-piloting MCP. You run **FreeCAD** locally; your AI client
(Claude Code, etc.) talks to the hosted MCP over HTTPS, which then pilots *your*
FreeCAD. The Conjur3 addon dials out to the hosted relay from **inside FreeCAD**
(a pure-Python link — no extra process, no inbound ports), so none of the
Conjur3 logic ships to your machine.

```
your AI client ──Bearer seat key──▶ https://mcp.conjur3.com/mcp
                                        │ (relay)
        ┌── your machine ──────────────┼───────────────────────┐
        │  FreeCAD + Conjur3 addon  ──link dials out──┘          │
        └───────────────────────────────────────────────────────┘
```

**You need:** [FreeCAD](https://www.freecad.org) (any packaging — native, **snap**,
or flatpak) and your **seat key** (`CJ3-XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX`).
Node.js is **not** required.

---

## 1. Install (one command — Linux & macOS)

Pass your seat key so the addon links automatically when FreeCAD opens:

```bash
curl -fsSL https://mcp.conjur3.com/install.sh | CONJUR3_KEY=CJ3-XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX bash
```

This installs the **Conjur3 addon** into FreeCAD's `Mod` folder (with your key +
relay) plus a bundled pure-Python WebSocket client. If Node.js happens to be
installed it also drops an optional standalone `conjur3-connector` in
`~/.local/bin` for headless use — but you don't need it.

## 2. Restart FreeCAD

Quit and reopen FreeCAD so it loads the addon. On startup it:
- runs an in-process RPC bridge, and
- **connects to the hosted MCP on its own** — the report view shows
  `[Conjur3] link established → wss://mcp.conjur3.com` — and tears the link down
  when you quit FreeCAD.

This works identically on **snap/flatpak** FreeCAD: the link runs inside
FreeCAD's own Python, so sandbox confinement is a non-issue. Skip to step 4.

(There's a **Conjur3** workbench with manual start/stop controls if you want them.)

## 3. (Optional) Headless / no-GUI link

Only if you want the link to run **without** opening the FreeCAD GUI (e.g. a
headless workstation) and you have Node.js installed:

```bash
CONJUR3_KEY=CJ3-XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX conjur3-connector
```

## 4. Connect your AI client

**Claude Code (CLI):**
```bash
claude mcp add --transport http conjur3 https://mcp.conjur3.com/mcp \
  --header "Authorization: Bearer CJ3-XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX"
```
Restart Claude Code; `conjur3` shows as connected.

**Claude.ai (web custom connector):** add a connector with URL
`https://mcp.conjur3.com/mcp` and an `Authorization: Bearer <seat key>` header
(the gateway is CORS-enabled for this).

## 5. Verify
Ask the agent to **“create a new FreeCAD document and a box.”** You'll see it
appear in your FreeCAD viewport, and the agent gets a screenshot back.

---

## Run the connector in the background

The in-addon link (above) covers most users — it lives and dies with FreeCAD and
needs no Node. Use a background service **instead** only if you want the link up
even when FreeCAD is closed (e.g. a headless workstation); it needs Node.js.
Don't run both, or you'll have two links on the same key (the newer wins).

**Linux (systemd user service):**
```bash
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/conjur3-connector.service <<'UNIT'
[Unit]
Description=Conjur3 connector
After=network-online.target
[Service]
Environment=CONJUR3_KEY=CJ3-XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX
ExecStart=%h/.local/bin/conjur3-connector
Restart=always
RestartSec=3
[Install]
WantedBy=default.target
UNIT
systemctl --user daemon-reload && systemctl --user enable --now conjur3-connector
```

**macOS (launchd):**
```bash
cat > ~/Library/LaunchAgents/ai.conjur3.connector.plist <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>ai.conjur3.connector</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>-lc</string>
    <string>exec "$HOME/.local/bin/conjur3-connector"</string></array>
  <key>EnvironmentVariables</key><dict>
    <key>CONJUR3_KEY</key><string>CJ3-XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX</string></dict>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
</dict></plist>
PLIST
launchctl load ~/Library/LaunchAgents/ai.conjur3.connector.plist
```

---

## Manual addon install (if the auto-install didn't find FreeCAD)
Drop the addon into FreeCAD's `Mod` folder yourself. The folder is one of:
- Linux (native): `~/.local/share/FreeCAD/Mod`
- Linux (Snap): `~/snap/freecad/common/Mod`
- Linux (Flatpak): `~/.var/app/org.freecadweb.FreeCAD/data/FreeCAD/Mod`
- macOS: `~/Library/Application Support/FreeCAD/Mod`

```bash
MOD=~/.local/share/FreeCAD/Mod            # adjust per the list above
KEY=CJ3-XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX
mkdir -p "$MOD" && curl -fsSL https://mcp.conjur3.com/conjur3-addon.tar.gz | tar -xz -C "$MOD"
printf '{"remote_enabled":true,"allowed_ips":"127.0.0.1","auto_start_rpc":true,"conjur3_key":"%s","conjur3_relay":"wss://mcp.conjur3.com"}\n' "$KEY" \
  > "$(dirname "$MOD")/conjur3_settings.json"
```
(Drop the `conjur3_key`/`conjur3_relay` fields to leave the link unconfigured.)
Restart FreeCAD.

## Troubleshooting
- **Link didn't connect** — open the FreeCAD **Report view** (View ▸ Panels ▸
  Report view) and look for `[Conjur3] link established`. `no seat key configured`
  means re-run the installer with `CONJUR3_KEY=…`. An error there names the cause
  (e.g. a network/proxy block reaching `wss://…`).
- **`401` / "invalid key"** — wrong or revoked key, or inactive subscription. Recreate your key from your dashboard (it is shown only once at creation).
- **Tool calls say "no connector attached"** — FreeCAD isn't open, or the addon
  didn't load. Restart FreeCAD and confirm the **Conjur3** workbench is present.
- **Self-hosting / different domain** — set `CONJUR3_BASE=https://your-host` before
  the install one-liner (the addon's relay is derived from it).
