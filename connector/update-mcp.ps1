# Re-register the Conjur3 MCP with your AI agent on Windows (removes stale entry first).
# Use this whenever your seat key changes or claude mcp add says "already exists".
#
#   $env:CONJUR3_KEY="CJ3-..."; irm https://mcp.conjur3.com/update-mcp.ps1 | iex
#
# Optional env vars: CONJUR3_AGENT (claude|antigravity|opencode|codex|hermes), CONJUR3_BASE
[CmdletBinding()]
param(
  [string]$Key   = $env:CONJUR3_KEY,
  [string]$Agent = $env:CONJUR3_AGENT,
  [string]$Base  = $env:CONJUR3_BASE
)
# Note: PowerShell param defaults must be expressions, not `if` statements,
# so apply fallbacks here rather than inline above.
if (-not $Agent) { $Agent = "claude" }
if (-not $Base)  { $Base  = "https://conjur3-mcp-eeifigkc7a-uc.a.run.app" }

function Say($msg)  { Write-Host $msg -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "  v $msg" -ForegroundColor Green }
function Fail($msg) { Write-Host "  x $msg" -ForegroundColor Red; throw $msg }

if (-not $Key) {
  Write-Host 'No key provided. Run:' -ForegroundColor Red
  Write-Host "  `$env:CONJUR3_KEY=`"CJ3-...`"; irm $Base/update-mcp.ps1 | iex"
  exit 1
}

$Agent = $Agent.ToLower()

# Remove conjur3 from every project context in ~/.claude.json (Windows path varies).
function Remove-ClaudeJsonEntry {
  $claudeJson = Join-Path $env:USERPROFILE ".claude.json"
  if (-not (Test-Path $claudeJson)) { return }
  try {
    $raw = Get-Content $claudeJson -Raw -Encoding UTF8
    $d   = $raw | ConvertFrom-Json
    $changed = $false
    foreach ($proj in $d.projects.PSObject.Properties) {
      if ($proj.Value.mcpServers -and $proj.Value.mcpServers.PSObject.Properties["conjur3"]) {
        $proj.Value.mcpServers.PSObject.Properties.Remove("conjur3")
        $changed = $true
      }
    }
    if ($changed) {
      # -Depth 100 (PowerShell's max) so a deeply nested .claude.json is never silently truncated.
      $d | ConvertTo-Json -Depth 100 | Set-Content $claudeJson -Encoding UTF8
    }
  } catch {
    # Non-fatal; CLI remove will handle user-scoped entries
  }
}

function Merge-JsonConfig {
  param([string]$Path, [string]$TopKey, [string]$Flavor)
  $dir = Split-Path $Path -Parent
  if ($dir) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
  $cfg = if (Test-Path $Path) {
    try { Get-Content $Path -Raw -Encoding UTF8 | ConvertFrom-Json } catch { [PSCustomObject]@{} }
  } else { [PSCustomObject]@{} }

  if (-not ($cfg.PSObject.Properties[$TopKey])) {
    $cfg | Add-Member -NotePropertyName $TopKey -NotePropertyValue ([PSCustomObject]@{})
  }
  $auth  = [PSCustomObject]@{ Authorization = "Bearer $Key" }
  $entry = if ($Flavor -eq "serverUrl") {
    [PSCustomObject]@{ serverUrl = "$Base/mcp"; headers = $auth }
  } else {
    [PSCustomObject]@{ type = "remote"; url = "$Base/mcp"; enabled = $true; headers = $auth }
  }
  $cfg.$TopKey | Add-Member -NotePropertyName "conjur3" -NotePropertyValue $entry -Force
  # -Depth 100 (PowerShell's max) so we never silently truncate a deeply nested existing config.
  $cfg | ConvertTo-Json -Depth 100 | Set-Content $Path -Encoding UTF8
  Ok "Conjur3 written to $Path"
}

switch ($Agent) {
  "claude" {
    if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
      Fail "claude CLI not found. Install Claude Code: https://claude.ai/download"
    }
    Say "-> Updating Conjur3 in Claude Code"
    # Scrub ~/.claude.json so stale project-scoped entries are removed regardless
    # of which directory the user originally ran claude mcp add from.
    Remove-ClaudeJsonEntry
    # Also try CLI removes for user-scoped entries.
    claude mcp remove conjur3 --scope user 2>$null; $true
    claude mcp remove conjur3              2>$null; $true
    claude mcp add --transport http conjur3 "$Base/mcp" --header "Authorization: Bearer $Key" 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
      Ok "Conjur3 registered with Claude Code."
      Write-Host "  Restart Claude Code if it is currently running."
    } else {
      Write-Host "  claude mcp add failed. Run manually:" -ForegroundColor Red
      Write-Host "    claude mcp add --transport http conjur3 $Base/mcp ``"
      Write-Host "      --header `"Authorization: Bearer $Key`""
      exit 1
    }
  }

  "antigravity" {
    Say "-> Updating Conjur3 in Antigravity"
    Merge-JsonConfig "$env:USERPROFILE\.gemini\config\mcp_config.json" "mcpServers" "serverUrl"
    Write-Host "  Open Antigravity -> Manage MCP Servers -> Refresh."
  }

  "opencode" {
    Say "-> Updating Conjur3 in OpenCode"
    Merge-JsonConfig "$env:APPDATA\opencode\opencode.json" "mcp" "remote"
    Write-Host "  Restart OpenCode; verify with: opencode mcp list"
  }

  "codex" {
    if (-not (Get-Command codex -ErrorAction SilentlyContinue)) {
      Fail "codex CLI not found."
    }
    Say "-> Updating Conjur3 in Codex"
    codex mcp remove conjur3 2>$null; $true
    codex mcp add conjur3 --url "$Base/mcp" --bearer-token-env-var CONJUR3_KEY 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
      Ok "Conjur3 registered with Codex."
      Write-Host "  Add to your PowerShell profile:  `$env:CONJUR3_KEY = `"$Key`""
    } else {
      Write-Host "  codex mcp add failed. Add to %USERPROFILE%\.codex\config.toml:" -ForegroundColor Red
      Write-Host "    [mcp_servers.conjur3]"
      Write-Host "    url = `"$Base/mcp`""
      Write-Host "    bearer_token_env_var = `"CONJUR3_KEY`""
      exit 1
    }
  }

  "hermes" {
    Say "-> Updating Conjur3 in Hermes"
    Write-Host "  Add to %USERPROFILE%\.hermes\config.yaml:"
    Write-Host "    mcp_servers:"
    Write-Host "      conjur3:"
    Write-Host "        url: `"$Base/mcp`""
    Write-Host "        headers:"
    Write-Host "          Authorization: `"Bearer $Key`""
    Write-Host "        enabled: true"
  }

  default {
    Write-Host "Unknown CONJUR3_AGENT `"$Agent`". Use claude | antigravity | opencode | codex | hermes." -ForegroundColor Red
    exit 1
  }
}

Write-Host ""
Write-Host "Done. Your Conjur3 MCP entry has been updated."
