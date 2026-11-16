#!/usr/bin/env bash
# Conjur3 setup (Linux + macOS) — installs the Conjur3 FreeCAD addon, which
# connects to the hosted Conjur3 MCP on its own (a pure-Python link runs inside
# FreeCAD — no Node, works under snap/flatpak confinement).
#
#   curl -fsSL <gateway>/install.sh | CONJUR3_KEY=CJ3-… bash
#
# Requires: FreeCAD. Node.js is OPTIONAL — only for the standalone connector
# (a background/headless alternative to the in-FreeCAD link). No inbound ports.
# Override the server with CONJUR3_BASE=https://your-host.
set -euo pipefail

# Default gateway = the live Cloud Run service. mcp.conjur3.com has no DNS yet
# (conjur3.com is the marketing site); switch this when that record exists.
BASE="${CONJUR3_BASE:-https://conjur3-mcp-eeifigkc7a-uc.a.run.app}"
RELAY_DEFAULT="${BASE/https:/wss:}"; RELAY_DEFAULT="${RELAY_DEFAULT/http:/ws:}"
DEST="$HOME/.conjur3"
BIN="$HOME/.local/bin"
OS="$(uname -s)"
# Optional: pass your seat key so FreeCAD auto-runs the connector as a sidecar.
#   curl -fsSL .../install.sh | CONJUR3_KEY=CJ3-… bash
KEY="${CONJUR3_KEY:-}"

json_escape() { printf '%s' "$1" | sed 's/["\\]/\\&/g'; }

say() { printf '\033[36m%s\033[0m\n' "$*"; }
die() { printf '\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

# Node is optional (only for the standalone connector). Detect, don't require.
HAVE_NODE=0
if command -v node >/dev/null 2>&1; then
  NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)"
  [ "$NODE_MAJOR" -ge 18 ] && HAVE_NODE=1
fi

mkdir -p "$DEST" "$BIN"

# ── 1. Conjur3 addon (the RPC bridge FreeCAD exposes on :9875) ──────────
say "→ Installing the Conjur3 addon"
fc_dirs=()
for d in "$HOME/.local/share/FreeCAD" "$HOME/snap/freecad/common" \
         "$HOME/.var/app/org.freecadweb.FreeCAD/data/FreeCAD" \
         "$HOME/.var/app/org.freecad.FreeCAD/data/FreeCAD" \
         "$HOME/Library/Application Support/FreeCAD" \
         "$HOME/Library/Preferences/FreeCAD"; do
  [ -d "$d" ] && fc_dirs+=("$d")
done
if [ "${#fc_dirs[@]}" -eq 0 ]; then
  [ "$OS" = "Darwin" ] && fc_dirs=("$HOME/Library/Application Support/FreeCAD") || fc_dirs=("$HOME/.local/share/FreeCAD")
  echo "  (No FreeCAD profile found yet — installing to the default location.)"
  if [ "$OS" = "Darwin" ]; then
    echo "  If FreeCAD isn't installed:  brew install --cask freecad   (or https://www.freecad.org/downloads.php)"
  else
    echo "  If FreeCAD isn't installed:  sudo snap install freecad   /   flatpak install org.freecad.FreeCAD"
    echo "  (or your distro's package). Open FreeCAD once afterward so it picks up the addon."
  fi
fi
addon_tmp="$(mktemp)"
curl -fsSL "$BASE/conjur3-addon.tar.gz" -o "$addon_tmp" || die "Addon download failed: $BASE/conjur3-addon.tar.gz"
for d in "${fc_dirs[@]}"; do
  mkdir -p "$d/Mod"
  rm -rf "$d/Mod/Conjur3"
  tar -xzf "$addon_tmp" -C "$d/Mod"
  if [ -n "$KEY" ]; then
    printf '{"remote_enabled":true,"allowed_ips":"127.0.0.1","auto_start_rpc":true,"conjur3_key":"%s","conjur3_relay":"%s"}\n' \
      "$(json_escape "$KEY")" "$RELAY_DEFAULT" > "$d/conjur3_settings.json"
  else
    printf '{"remote_enabled":true,"allowed_ips":"127.0.0.1","auto_start_rpc":true,"conjur3_relay":"%s"}\n' \
      "$RELAY_DEFAULT" > "$d/conjur3_settings.json"
  fi
  echo "  addon → $d/Mod/Conjur3 (RPC auto-start enabled)"
done
rm -f "$addon_tmp"

# ── 2. Standalone connector (OPTIONAL) ────────────────────────────────────────
# The addon already connects from inside FreeCAD. This Node connector is only a
# background/headless alternative (e.g. run the link without the FreeCAD GUI).
if [ "$HAVE_NODE" = "1" ]; then
  say "→ Installing the optional standalone connector (Node found)"
  if curl -fsSL "$BASE/connector.js" -o "$DEST/conjur3-connector.js" 2>/dev/null; then
    cat > "$BIN/conjur3-connector" <<LAUNCH
#!/usr/bin/env bash
# Set CONJUR3_KEY to your seat key. Override CONJUR3_RELAY / CONJUR3_LOCAL if needed.
export CONJUR3_RELAY="\${CONJUR3_RELAY:-$RELAY_DEFAULT}"
exec node "$DEST/conjur3-connector.js" "\$@"
LAUNCH
    chmod +x "$BIN/conjur3-connector"
    echo "  connector → $BIN/conjur3-connector"
    case ":$PATH:" in *":$BIN:"*) : ;; *) echo "  Add to PATH:  export PATH=\"$BIN:\$PATH\"  (append to ~/.bashrc or ~/.zshrc)";; esac
  fi
else
  say "→ Node not found — skipping the optional standalone connector"
  echo "  (Not needed: the FreeCAD addon connects on its own.)"
fi

# ── 3. Verify the key against the gateway ────────────────────────────────────
# The dashboard shows your key exactly once at creation; this confirms the copy
# you pasted actually works before you ever open FreeCAD.
if [ -n "$KEY" ]; then
  say "→ Verifying your API key with $BASE"
  VERIFY_CODE="$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $KEY" "$BASE/verify" || echo 000)"
  case "$VERIFY_CODE" in
    200) printf '  \033[32m✓ Key verified — your seat is live.\033[0m\n' ;;
    401) printf '  \033[31m✗ The gateway rejected this key (invalid or revoked).\033[0m\n'
         echo  "    Recreate your key on your dashboard ($BASE → Conjur3 dashboard) and re-run:"
         echo  "      curl -fsSL $BASE/install.sh | CONJUR3_KEY=CJ3-… bash" ;;
    *)   printf '  \033[33m! Could not reach the gateway to verify (HTTP %s) — continuing anyway.\033[0m\n' "$VERIFY_CODE" ;;
  esac
fi

# ── 4. Connect your AI agent ─────────────────────────────────────────────────
# Pick via CONJUR3_AGENT=claude|antigravity|codex|hermes|opencode, or answer the
# prompt (read from /dev/tty — stdin is the script when piped through curl).
# Where the agent has a CLI or a JSON config we register Conjur3 for you;
# otherwise we print the exact snippet.
AGENT="${CONJUR3_AGENT:-}"
if [ -z "$AGENT" ] && [ -r /dev/tty ] && [ -t 1 ]; then
  say "→ Which AI agent do you use?"
  printf '   1) Claude Code   2) Google Antigravity   3) OpenAI Codex   4) Hermes   5) OpenCode\n'
  printf '   Choose [1-5] (default 1): '
  read -r _choice < /dev/tty || _choice=""
  case "$_choice" in
    2|antigravity) AGENT=antigravity ;;
    3|codex)       AGENT=codex ;;
    4|hermes)      AGENT=hermes ;;
    5|opencode)    AGENT=opencode ;;
    *)             AGENT=claude ;;
  esac
fi
AGENT="$(printf '%s' "${AGENT:-claude}" | tr '[:upper:]' '[:lower:]')"
KEY_SHOWN="${KEY:-CJ3-XXXX…your-key…}"

# Merge one server entry into a JSON config (used for Antigravity / OpenCode).
merge_json_config() { # $1=path $2=topKey(mcpServers|mcp) $3=flavor(serverUrl|remote)
  CJ3_CFG="$1" CJ3_TOP="$2" CJ3_FLAVOR="$3" CJ3_URL="$BASE/mcp" CJ3_KEY="$KEY" python3 <<'PY'
import json, os
p = os.environ["CJ3_CFG"]
try:
    with open(p) as f: cfg = json.load(f)
except (FileNotFoundError, ValueError):
    cfg = {}
auth = {"Authorization": "Bearer " + os.environ["CJ3_KEY"]}
if os.environ["CJ3_FLAVOR"] == "serverUrl":   # Antigravity
    entry = {"serverUrl": os.environ["CJ3_URL"], "headers": auth}
else:                                          # OpenCode
    entry = {"type": "remote", "url": os.environ["CJ3_URL"], "enabled": True, "headers": auth}
cfg.setdefault(os.environ["CJ3_TOP"], {})["conjur3"] = entry
os.makedirs(os.path.dirname(p), exist_ok=True)
with open(p, "w") as f: json.dump(cfg, f, indent=2); f.write("\n")
print(f"  ✓ Conjur3 written to {p}")
PY
}

echo
echo "✓ Addon installed. The Conjur3 link runs inside FreeCAD — restart FreeCAD"
echo "  once, then connect your agent:"
echo
case "$AGENT" in
  claude)
    if [ -n "$KEY" ] && command -v claude >/dev/null 2>&1; then
      claude mcp remove conjur3 >/dev/null 2>&1 || true
      if claude mcp add --transport http conjur3 "$BASE/mcp" \
           --header "Authorization: Bearer $KEY" >/dev/null 2>&1; then
        say "  ✓ Conjur3 registered with Claude Code (claude mcp add)"
      else
        echo "  ! claude mcp add failed — run it yourself:"
      fi
    else
      echo "  Add the MCP to Claude Code:"
    fi
    cat <<EOF
       claude mcp add --transport http conjur3 $BASE/mcp \\
         --header "Authorization: Bearer $KEY_SHOWN"

  Then ask Claude to "create a FreeCAD document" — watch your viewport.
EOF
    ;;
  antigravity)
    AG_CFG="$HOME/.gemini/config/mcp_config.json"
    if [ -n "$KEY" ] && command -v python3 >/dev/null 2>&1; then
      merge_json_config "$AG_CFG" mcpServers serverUrl
      echo "  Open Antigravity → Manage MCP Servers → Refresh (or restart it)."
    else
      cat <<EOF
  Add to $AG_CFG
  (Antigravity → Manage MCP Servers → View raw config):

       { "mcpServers": { "conjur3": {
           "serverUrl": "$BASE/mcp",
           "headers": { "Authorization": "Bearer $KEY_SHOWN" } } } }
EOF
    fi
    ;;
  codex)
    if [ -n "$KEY" ] && command -v codex >/dev/null 2>&1; then
      codex mcp remove conjur3 >/dev/null 2>&1 || true
      if codex mcp add conjur3 --url "$BASE/mcp" --bearer-token-env-var CONJUR3_KEY >/dev/null 2>&1; then
        say "  ✓ Conjur3 registered with Codex (codex mcp add)"
      else
        echo "  ! codex mcp add failed — add to ~/.codex/config.toml yourself:"
        printf '       [mcp_servers.conjur3]\n       url = "%s/mcp"\n       bearer_token_env_var = "CONJUR3_KEY"\n' "$BASE"
      fi
    else
      cat <<EOF
  Add to ~/.codex/config.toml:

       [mcp_servers.conjur3]
       url = "$BASE/mcp"
       bearer_token_env_var = "CONJUR3_KEY"
EOF
    fi
    cat <<EOF

  Codex reads the key from your environment — add to ~/.bashrc or ~/.zshrc:
       export CONJUR3_KEY=$KEY_SHOWN
EOF
    ;;
  hermes)
    cat <<EOF
  Add to your Hermes config.yaml (usually ~/.hermes/config.yaml), under
  mcp_servers:

       mcp_servers:
         conjur3:
           url: "$BASE/mcp"
           headers:
             Authorization: "Bearer $KEY_SHOWN"
           enabled: true

  (Newer Hermes builds can manage this via the \`hermes mcp\` command.)
EOF
    ;;
  opencode)
    OC_CFG="$HOME/.config/opencode/opencode.json"
    if [ -n "$KEY" ] && command -v python3 >/dev/null 2>&1; then
      merge_json_config "$OC_CFG" mcp remote
      echo "  Restart OpenCode; check with: opencode mcp list"
    else
      cat <<EOF
  Add to $OC_CFG (or your project's opencode.json):

       { "mcp": { "conjur3": {
           "type": "remote", "url": "$BASE/mcp", "enabled": true,
           "headers": { "Authorization": "Bearer $KEY_SHOWN" } } } }
EOF
    fi
    ;;
  *)
    echo "  Unknown CONJUR3_AGENT \"$AGENT\" — use claude | antigravity | codex | hermes | opencode."
    ;;
esac

if [ -z "$KEY" ]; then
cat <<EOF

  No key was provided this run. Re-run with your seat key (from your dashboard)
  so FreeCAD links automatically and your agent gets the real key:

     curl -fsSL $BASE/install.sh | CONJUR3_KEY=CJ3-XXXX… CONJUR3_AGENT=$AGENT bash
EOF
fi
echo
echo "  Full guide: ONBOARDING.md"
