#!/usr/bin/env bash
# Re-register the Conjur3 MCP with your AI agent (removes stale entry first).
# Use this whenever your seat key changes or claude mcp add says "already exists".
#
#   curl -fsSL https://mcp.conjur3.com/update-mcp.sh | CONJUR3_KEY=CJ3-… bash
#
# Optional: CONJUR3_AGENT=claude|antigravity|opencode|codex|hermes (default: claude)
#           CONJUR3_BASE=https://your-self-hosted-host
set -euo pipefail

BASE="${CONJUR3_BASE:-https://conjur3-mcp-eeifigkc7a-uc.a.run.app}"
KEY="${CONJUR3_KEY:-}"
AGENT="${CONJUR3_AGENT:-claude}"

say() { printf '\033[36m%s\033[0m\n' "$*"; }
ok()  { printf '  \033[32m✓ %s\033[0m\n' "$*"; }
fail(){ printf '  \033[31m✗ %s\033[0m\n' "$*" >&2; }

[ -z "$KEY" ] && {
  printf '\033[31mNo key provided.\033[0m Run:\n'
  printf '  curl -fsSL %s/update-mcp.sh | CONJUR3_KEY=CJ3-… bash\n' "$BASE"
  exit 1
}

AGENT="$(printf '%s' "$AGENT" | tr '[:upper:]' '[:lower:]')"

# Remove conjur3 from every scope in ~/.claude.json (covers all project contexts).
scrub_claude_json() {
  python3 - <<'PY' 2>/dev/null || true
import json, os
p = os.path.expanduser("~/.claude.json")
try:
    with open(p) as f: d = json.load(f)
    changed = False
    for proj in d.get("projects", {}).values():
        if proj.get("mcpServers", {}).pop("conjur3", None) is not None:
            changed = True
    if changed:
        with open(p, "w") as f:
            json.dump(d, f, indent=2)
except (FileNotFoundError, json.JSONDecodeError, PermissionError):
    pass
PY
}

merge_json_config() {  # $1=path $2=topKey $3=flavor
  CJ3_CFG="$1" CJ3_TOP="$2" CJ3_FLAVOR="$3" CJ3_URL="$BASE/mcp" CJ3_KEY="$KEY" python3 <<'PY'
import json, os
p = os.environ["CJ3_CFG"]
try:
    with open(p) as f: cfg = json.load(f)
except (FileNotFoundError, ValueError):
    cfg = {}
auth = {"Authorization": "Bearer " + os.environ["CJ3_KEY"]}
if os.environ["CJ3_FLAVOR"] == "serverUrl":
    entry = {"serverUrl": os.environ["CJ3_URL"], "headers": auth}
else:
    entry = {"type": "remote", "url": os.environ["CJ3_URL"], "enabled": True, "headers": auth}
cfg.setdefault(os.environ["CJ3_TOP"], {})["conjur3"] = entry
os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
with open(p, "w") as f:
    json.dump(cfg, f, indent=2)
    f.write("\n")
print("  ✓ Conjur3 written to " + p)
PY
}

case "$AGENT" in
  claude)
    command -v claude >/dev/null 2>&1 || {
      fail "claude CLI not found. Install Claude Code: https://claude.ai/download"
      exit 1
    }
    say "→ Updating Conjur3 in Claude Code"
    # Scrub ~/.claude.json directly so the remove succeeds regardless of which
    # project context the entry was originally added from.
    scrub_claude_json
    # Also try CLI removes for user-scoped entries.
    claude mcp remove conjur3 --scope user  >/dev/null 2>&1 || true
    claude mcp remove conjur3               >/dev/null 2>&1 || true
    if claude mcp add --transport http conjur3 "$BASE/mcp" \
         --header "Authorization: Bearer $KEY" >/dev/null 2>&1; then
      ok "Conjur3 registered with Claude Code."
      echo "  Restart Claude Code if it is currently running."
    else
      fail "claude mcp add failed — run it manually:"
      printf '    claude mcp add --transport http conjur3 %s/mcp \\\n' "$BASE"
      printf '      --header "Authorization: Bearer %s"\n' "$KEY"
      exit 1
    fi
    ;;

  antigravity)
    say "→ Updating Conjur3 in Antigravity"
    merge_json_config "$HOME/.gemini/config/mcp_config.json" mcpServers serverUrl
    echo "  Open Antigravity → Manage MCP Servers → Refresh."
    ;;

  opencode)
    say "→ Updating Conjur3 in OpenCode"
    merge_json_config "$HOME/.config/opencode/opencode.json" mcp remote
    echo "  Restart OpenCode; verify with: opencode mcp list"
    ;;

  codex)
    command -v codex >/dev/null 2>&1 || { fail "codex CLI not found."; exit 1; }
    say "→ Updating Conjur3 in Codex"
    codex mcp remove conjur3 >/dev/null 2>&1 || true
    if codex mcp add conjur3 --url "$BASE/mcp" --bearer-token-env-var CONJUR3_KEY >/dev/null 2>&1; then
      ok "Conjur3 registered with Codex."
      printf '  Add to ~/.bashrc or ~/.zshrc:  export CONJUR3_KEY=%s\n' "$KEY"
    else
      fail "codex mcp add failed. Add to ~/.codex/config.toml:"
      printf '    [mcp_servers.conjur3]\n    url = "%s/mcp"\n    bearer_token_env_var = "CONJUR3_KEY"\n' "$BASE"
      exit 1
    fi
    ;;

  hermes)
    say "→ Updating Conjur3 in Hermes"
    if python3 - 2>/dev/null <<PY
import yaml, os
p = os.path.expanduser("~/.hermes/config.yaml")
try:
    with open(p) as f: cfg = yaml.safe_load(f) or {}
except FileNotFoundError:
    cfg = {}
cfg.setdefault("mcp_servers", {})["conjur3"] = {
    "url": "${BASE}/mcp",
    "headers": {"Authorization": "Bearer ${KEY}"},
    "enabled": True,
}
os.makedirs(os.path.dirname(p), exist_ok=True)
with open(p, "w") as f: yaml.safe_dump(cfg, f)
print("  ✓ Conjur3 written to " + p)
PY
    then
      echo "  Restart Hermes."
    else
      echo "  Update ~/.hermes/config.yaml manually:"
      printf '    mcp_servers:\n      conjur3:\n        url: "%s/mcp"\n        headers:\n          Authorization: "Bearer %s"\n        enabled: true\n' "$BASE" "$KEY"
    fi
    ;;

  *)
    echo "Unknown CONJUR3_AGENT \"$AGENT\". Use claude | antigravity | opencode | codex | hermes."
    exit 1
    ;;
esac

echo
echo "Done. Your Conjur3 MCP entry has been updated."
