# Conjur3 setup for Windows — installs the FreeCAD addon and registers the MCP
# with your AI agent.
#
#   $env:CONJUR3_KEY="CJ3-..."; irm https://mcp.conjur3.com/install.ps1 | iex
#
# Optional env vars:
#   CONJUR3_AGENT  claude|antigravity|opencode|codex|hermes  (default: claude)
#   CONJUR3_BASE   override gateway URL (self-hosted)
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

$ErrorActionPreference = "Stop"

function Say($msg)  { Write-Host $msg -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "  v $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "  ! $msg" -ForegroundColor Yellow }
function Fail($msg) { Write-Host "  x $msg" -ForegroundColor Red }

# ── Supported OS check ───────────────────────────────────────────────────────
# Conjur3 targets Windows 10 and 11 (both report OS major version 10). Bail
# politely on anything older so users don't hit a cryptic failure later — e.g.
# the built-in `tar` extractor, which only exists on Windows 10 1803+.
# Use OSVersion.Major (works on Windows PowerShell 5.1, where $IsWindows is
# undefined) and only block when this is actually Windows.
$osv = [System.Environment]::OSVersion
if ($osv.Platform -eq [System.PlatformID]::Win32NT -and $osv.Version.Major -lt 10) {
  # Map the NT version (e.g. 6.1) to its familiar marketing name (Windows 7).
  $winNames = @{
    "6.3" = "Windows 8.1"; "6.2" = "Windows 8";                "6.1" = "Windows 7"
    "6.0" = "Windows Vista"; "5.2" = "Windows XP / Server 2003"; "5.1" = "Windows XP"
  }
  $mm   = "$($osv.Version.Major).$($osv.Version.Minor)"
  $name = if ($winNames.ContainsKey($mm)) { $winNames[$mm] } else { "Windows (NT $mm)" }
  Fail ":( Conjur3 supports only Windows 10 and 11."
  Write-Host "  Detected: $name."
  Write-Host "  Please upgrade to Windows 10 or 11, then re-run this installer."
  exit 1
}

$Relay = $Base -replace '^https:', 'wss:' -replace '^http:', 'ws:'

# ── 1. FreeCAD addon ─────────────────────────────────────────────────────────
Say "-> Installing the Conjur3 addon"

# FreeCAD 1.0+ uses versioned user-data dirs (v1.1, v1.0); check newest first,
# then fall back to the legacy unversioned path for older installs.
$candidateDirs = @(
  "$env:APPDATA\FreeCAD\v1.1",
  "$env:APPDATA\FreeCAD\v1.0",
  "$env:APPDATA\FreeCAD",
  "$env:LOCALAPPDATA\FreeCAD\v1.1",
  "$env:LOCALAPPDATA\FreeCAD\v1.0",
  "$env:LOCALAPPDATA\FreeCAD"
) | Where-Object { Test-Path $_ }

if ($candidateDirs.Count -eq 0) {
  # Default to FreeCAD 1.1 versioned path; the legacy unversioned path is
  # only used by pre-1.0 installs.
  $candidateDirs = @("$env:APPDATA\FreeCAD\v1.1")
  Warn "No FreeCAD profile found — will install to the default 1.1 location."
  Write-Host "  Download FreeCAD from https://www.freecad.org/downloads.php"
  Write-Host "  Open FreeCAD once so it creates its profile, then re-run this script."
}

$addonTmp = [System.IO.Path]::GetTempFileName() + ".tar.gz"
try {
  Invoke-WebRequest -Uri "$Base/conjur3-addon.tar.gz" -OutFile $addonTmp -UseBasicParsing
} catch {
  Write-Error "Addon download failed: $Base/conjur3-addon.tar.gz"; exit 1
}

foreach ($fcDir in $candidateDirs) {
  $modDir    = Join-Path $fcDir "Mod"
  $conjurDir = Join-Path $modDir "Conjur3"
  New-Item -ItemType Directory -Force -Path $modDir | Out-Null
  if (Test-Path $conjurDir) { Remove-Item -Recurse -Force $conjurDir }

  # tar is built-in on Windows 10 1803+ (bsdtar); fails gracefully on older builds.
  $tarResult = & tar -xzf $addonTmp -C $modDir 2>&1
  if ($LASTEXITCODE -ne 0) {
    Write-Host "  tar failed — Windows 10 1803+ required for automatic extraction."
    Write-Host "  Manual alternative: download $Base/conjur3-addon.tar.gz, extract"
    Write-Host "  to $modDir\Conjur3, then re-run this script."
    exit 1
  }

  $settings = [ordered]@{
    remote_enabled = $true
    allowed_ips    = "127.0.0.1"
    auto_start_rpc = $true
    conjur3_relay  = $Relay
  }
  if ($Key) { $settings["conjur3_key"] = $Key }
  $settings | ConvertTo-Json -Compress | Set-Content -Path (Join-Path $fcDir "conjur3_settings.json") -Encoding UTF8
  Ok "addon -> $modDir\Conjur3 (RPC auto-start enabled)"
}
Remove-Item $addonTmp -ErrorAction SilentlyContinue

# ── 2. Verify key ────────────────────────────────────────────────────────────
if ($Key) {
  Say "-> Verifying your API key with $Base"
  try {
    $resp = Invoke-WebRequest -Uri "$Base/verify" `
      -Headers @{ Authorization = "Bearer $Key" } `
      -UseBasicParsing -ErrorAction Stop
    if ($resp.StatusCode -eq 200) { Ok "Key verified — your seat is live." }
  } catch {
    $code = $null
    try { $code = $_.Exception.Response.StatusCode.value__ } catch {}
    if ($code -eq 401) {
      Fail "The gateway rejected this key (invalid or revoked)."
      Write-Host "  Recreate your key on the dashboard, then re-run:"
      Write-Host "  `$env:CONJUR3_KEY=`"CJ3-...`"; irm $Base/install.ps1 | iex"
    } else {
      Warn "Could not verify key (HTTP $code) — continuing anyway."
    }
  }
}

# ── 3. Register with AI agent ────────────────────────────────────────────────
$Agent = $Agent.ToLower()

# Remove conjur3 from every project context in ~/.claude.json.
function Remove-ClaudeJsonEntry {
  $claudeJson = Join-Path $env:USERPROFILE ".claude.json"
  if (-not (Test-Path $claudeJson)) { return }
  try {
    $d = Get-Content $claudeJson -Raw -Encoding UTF8 | ConvertFrom-Json
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
  } catch {}
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

Write-Host ""
Write-Host "v Addon installed. Restart FreeCAD once, then connect your agent:"
Write-Host ""

$keyShown = if ($Key) { $Key } else { "CJ3-XXXX...your-key" }

switch ($Agent) {
  "claude" {
    if ($Key -and (Get-Command claude -ErrorAction SilentlyContinue)) {
      Say "  -> Registering with Claude Code"
      Remove-ClaudeJsonEntry
      claude mcp remove conjur3 --scope user 2>$null; $true
      claude mcp remove conjur3              2>$null; $true
      claude mcp add --transport http conjur3 "$Base/mcp" --header "Authorization: Bearer $Key" 2>&1 | Out-Null
      if ($LASTEXITCODE -eq 0) {
        Ok "Conjur3 registered with Claude Code."
        Write-Host "  Restart Claude Code if it is currently running."
      } else {
        Fail "claude mcp add failed — run it yourself:"
        Write-Host "    claude mcp add --transport http conjur3 $Base/mcp ``"
        Write-Host "      --header `"Authorization: Bearer $keyShown`""
      }
    } else {
      Write-Host "  Add the MCP to Claude Code:"
    }
    Write-Host "     claude mcp add --transport http conjur3 $Base/mcp ``"
    Write-Host "       --header `"Authorization: Bearer $keyShown`""
    Write-Host ""
    Write-Host "  Then ask Claude to `"create a FreeCAD document`" — watch your viewport."
  }

  "antigravity" {
    if ($Key) {
      Say "  -> Registering with Antigravity"
      Merge-JsonConfig "$env:USERPROFILE\.gemini\config\mcp_config.json" "mcpServers" "serverUrl"
      Write-Host "  Open Antigravity -> Manage MCP Servers -> Refresh."
    } else {
      Write-Host "  Add to %USERPROFILE%\.gemini\config\mcp_config.json:"
      Write-Host "  { `"mcpServers`": { `"conjur3`": { `"serverUrl`": `"$Base/mcp`","
      Write-Host "      `"headers`": { `"Authorization`": `"Bearer $keyShown`" } } } }"
    }
  }

  "opencode" {
    if ($Key) {
      Say "  -> Registering with OpenCode"
      Merge-JsonConfig "$env:APPDATA\opencode\opencode.json" "mcp" "remote"
      Write-Host "  Restart OpenCode; verify with: opencode mcp list"
    } else {
      Write-Host "  Add to %APPDATA%\opencode\opencode.json:"
      Write-Host "  { `"mcp`": { `"conjur3`": { `"type`": `"remote`", `"url`": `"$Base/mcp`","
      Write-Host "      `"enabled`": true, `"headers`": { `"Authorization`": `"Bearer $keyShown`" } } } }"
    }
  }

  "codex" {
    if ($Key -and (Get-Command codex -ErrorAction SilentlyContinue)) {
      codex mcp remove conjur3 2>$null; $true
      codex mcp add conjur3 --url "$Base/mcp" --bearer-token-env-var CONJUR3_KEY 2>&1 | Out-Null
      if ($LASTEXITCODE -eq 0) {
        Ok "Conjur3 registered with Codex."
      } else {
        Fail "codex mcp add failed."
      }
    }
    Write-Host "  Add to %USERPROFILE%\.codex\config.toml:"
    Write-Host "    [mcp_servers.conjur3]"
    Write-Host "    url = `"$Base/mcp`""
    Write-Host "    bearer_token_env_var = `"CONJUR3_KEY`""
    Write-Host "  Add to your PowerShell profile: `$env:CONJUR3_KEY = `"$keyShown`""
  }

  "hermes" {
    Write-Host "  Add to %USERPROFILE%\.hermes\config.yaml:"
    Write-Host "    mcp_servers:"
    Write-Host "      conjur3:"
    Write-Host "        url: `"$Base/mcp`""
    Write-Host "        headers:"
    Write-Host "          Authorization: `"Bearer $keyShown`""
    Write-Host "        enabled: true"
  }

  default {
    Write-Host "  Unknown CONJUR3_AGENT `"$Agent`" — use claude | antigravity | opencode | codex | hermes."
  }
}

if (-not $Key) {
  Write-Host ""
  Write-Host "  No key was provided. Re-run with your seat key (from your dashboard):"
  Write-Host "  `$env:CONJUR3_KEY=`"CJ3-XXXX...`"; `$env:CONJUR3_AGENT=`"$Agent`"; irm $Base/install.ps1 | iex"
}

Write-Host ""
Write-Host "  Full guide: ONBOARDING.md"
