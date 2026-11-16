#!/usr/bin/env python3
"""Bundle a Conjur3 benchmark run into a CADGenBench submission zip.

    python3 benchmark/package.py benchmark/results/<run> --submitter "Jane Doe" --agree

The zip follows the leaderboard's contract: a top-level `meta.json` plus one
folder per sample holding `output.step`. Samples without a valid candidate are
included as empty folders (they score zero). A `run_report.json` describing how
the run was produced is written next to the zip, not inside it.
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

REPO_URL = "https://github.com/ListeningPost/Conjur3Cad"
EXPECTED = {"generation": 49, "editing": 32}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--submitter", required=True, help="your name or handle, shown on the leaderboard")
    ap.add_argument("--name", help="submission name (default: 'Conjur3 <commit> + <model>')")
    ap.add_argument("--notes", default=None, help="free text, at most 500 characters")
    ap.add_argument("--agent-url", default=REPO_URL)
    ap.add_argument("--agree", action="store_true",
                    help="set agree_to_publish=true; the leaderboard rejects the zip without it")
    ap.add_argument("--include-invalid", action="store_true",
                    help="also ship candidates that failed the local validity check")
    ap.add_argument("-o", "--output", type=Path)
    args = ap.parse_args()

    run = args.run_dir.resolve()
    params = json.loads((run / "params.json").read_text())
    samples = sorted(p for p in run.iterdir() if p.is_dir() and (p / "status.json").exists())
    if not samples:
        print(f"no finished samples under {run}", file=sys.stderr)
        return 1

    name = args.name or f"Conjur3 {params.get('conjur3_commit', '?')} + {params.get('model', '?')}"
    notes = args.notes or (f"Conjur3 MCP driving FreeCAD {params.get('freecad', '?')}; agent "
                           f"{params.get('agent')}, prompt style '{params.get('style', 'tools')}'; one attempt per "
                           f"sample, {params.get('timeout')} s limit.")
    meta = {"submitter_name": args.submitter, "submission_name": name, "agent_url": args.agent_url,
            "notes": notes[:500], "agree_to_publish": bool(args.agree)}

    out = args.output or run.with_suffix(".zip")
    out.parent.mkdir(parents=True, exist_ok=True)
    rows, counts, by_task = [], {}, {}
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("meta.json", json.dumps(meta, indent=2) + "\n")
        for d in samples:
            st = json.loads((d / "status.json").read_text())
            result = st.get("result", "missing")
            counts[result] = counts.get(result, 0) + 1
            by_task[st.get("task_type", "?")] = by_task.get(st.get("task_type", "?"), 0) + 1
            zf.writestr(f"{d.name}/", "")
            cand = d / "output.step"
            ship = cand.is_file() and cand.stat().st_size > 0 and (
                result in ("ok", "unchecked") or args.include_invalid)
            if ship:
                zf.write(cand, arcname=f"{d.name}/output.step")
            rows.append({k: st.get(k) for k in ("sample", "task_type", "result", "seconds", "timed_out",
                                                "num_turns", "tool_calls", "images_seen",
                                                "total_cost_usd")} | {"shipped": bool(ship)})

    report = {"meta": meta, "params": params, "counts": counts, "samples": rows}
    report_path = out.with_name(out.stem + ".run_report.json")
    report_path.write_text(json.dumps(report, indent=2) + "\n")

    shipped = sum(r["shipped"] for r in rows)
    print(f"wrote {out}  ({len(rows)} samples, {shipped} with a candidate)")
    print(f"wrote {report_path}")
    print("results: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    short = [f"{t}: {by_task.get(t, 0)}/{n}" for t, n in EXPECTED.items() if by_task.get(t, 0) != n]
    if short:
        print("NOTE: this is a partial run (" + ", ".join(short) + "). Missing samples score zero "
              "on the leaderboard; say so in --notes or finish the run with --resume.", file=sys.stderr)
    if not args.agree:
        print("NOTE: agree_to_publish is false. Re-run with --agree when you are ready to submit.",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
