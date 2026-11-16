# Conjur3

Live parametric CAD piloting. An MCP server that drives a running FreeCAD GUI via an in-process RPC bridge — every edit updates the 3D viewport on the next recompute, and a screenshot of the result is returned to the model.

Composed of three pieces working together:

| Layer | What | Where |
|---|---|---|
| **Workbench addon** | Starts an XML-RPC server on `:9875` inside the FreeCAD Qt event loop. 30+ curated handlers (sketches, pad/pocket/revolve, fillets, booleans, patterns, variable sets, exports), each wrapped in an undo transaction. | `addon/conjur3_pilot/` |
| **MCP server** | FastMCP server that exposes the same surface as MCP tools. Attaches a screenshot to every mutating result so the LLM sees what changed. | `src/conjur3_pilot/` |
| **Claude Code skill bundle** | Top-level `conjur3-pilot/SKILL.md` teaches the document-first, parametric-first, screenshot-often workflow. Sub-skills for enclosures, gears, fastener holes, server racks. | `skills/conjur3-pilot/` |

A second, headless **batch mode** (`run_design_program`) replays woodbloks-ai `DesignProgram` JSON files via FreeCAD's bundled Python — useful for CI or STEP-only jobs.

## Install

### 1. Install the workbench addon into FreeCAD

```bash
# Linux
mkdir -p ~/.local/share/FreeCAD/Mod
ln -sfn "$PWD/addon/conjur3_pilot" ~/.local/share/FreeCAD/Mod/Conjur3
```

Restart FreeCAD. Switch to the **"Conjur3"** workbench. The RPC server auto-starts on `127.0.0.1:9875` (disabled for remote connections by default). Toolbar commands let you start/stop, toggle auto-start, and configure allowed IPs.

### 2. Install the MCP server

```bash
cd conjur3-pilot
uv pip install -e .           # or: pipx install -e .
```

This installs the `conjur3-pilot` command.

### 3. Register with Claude Code

Either per-project (`.mcp.json` in the repo root) or globally (`~/.claude.json`):

```json
{
  "mcpServers": {
    "conjur3-pilot": {
      "command": "conjur3-pilot",
      "args": []
    }
  }
}
```

Or via the CLI:

```bash
claude mcp add conjur3-pilot -- conjur3-pilot
```

Restart Claude Code. The `conjur3-pilot` MCP should show as connected.

### 3b. (Optional) Register with opencode

Per-project (`opencode.json` in the repo root) or globally (`~/.config/opencode/opencode.json`):

```json
{
  "mcp": {
    "conjur3-pilot": {
      "type": "local",
      "command": ["conjur3-pilot"],
      "enabled": true
    }
  }
}
```

Restart opencode. The `conjur3-pilot` tools should appear in the tool list.

### 4. (Optional) Install the skill bundle

```bash
mkdir -p ~/.claude/skills
ln -sfn "$PWD/skills/conjur3-pilot" ~/.claude/skills/conjur3-pilot
```

## Usage

1. Launch FreeCAD. The workbench auto-starts the RPC.
2. In Claude Code, ask something like *"using conjur3-pilot, build a 60×40×20 mm parametric enclosure with 3 mm walls and M3 corner bosses."*
3. Watch the viewport. Claude issues `create_document` → `create_body` → `create_sketch` → `pad_sketch` → `shell_object` → ..., and each step returns a screenshot.
4. *"Make the wall 2 mm."* — Claude updates a spreadsheet cell; the model recomputes live.
5. *"Export a STEP."* — `export_step` writes the file and confirms.

## Batch / headless

```bash
# Replay an existing DesignProgram JSON
conjur3-pilot  # run MCP as usual; then from Claude, call run_design_program(program_path=...)

# Or directly (bypassing Claude):
python -c "from conjur3_pilot.batch import run; print(run('../woodbloks-ai/designs/rk-gen-001.json', '/tmp/rack.FCStd', '/tmp/rack.step'))"
```

## Troubleshooting

- **MCP can't reach FreeCAD.** Check that (a) FreeCAD is running, (b) the "Conjur3" workbench was activated at least once, (c) the "Auto-Start on Launch" menu item is checked, (d) port 9875 is open (`ss -tlnp | grep 9875`).
- **"no active document" errors.** Call `create_document` first. Most tools accept `doc_name=None` which means the current active doc.
- **PartDesign operations fail.** Did you `create_body` first? All `pad_sketch` / `pocket_sketch` / `fillet_edges` / `shell_object` / `linear_pattern` / etc. require a Body.
- **Edge / face indices don't match.** Indices re-number when topology changes. Call `list_edges` / `list_faces` immediately before the fillet/chamfer call, not several steps earlier.

## Credits

- Bridge pattern (XML-RPC addon, GUI task queue, auto-start, screenshot capture) adapted from [neka-nat/freecad-mcp](https://github.com/neka-nat/freecad-mcp) (MIT).
- Tool-surface curation (undo-wrapped handlers, parametric-first, skills system) inspired by [ghbalf/freecad-ai](https://github.com/ghbalf/freecad-ai) (LGPL-2.1).
- Batch / DesignProgram path delegates to the separate `woodbloks-ai` package, which is not part of this repository; `run_design_program` only works when that package is checked out alongside `conjur3-pilot`.
