#!/usr/bin/env python3
"""Run CADGenBench with Conjur3.

For every benchmark sample this starts a fresh agent (Claude Code by default,
or any MCP-capable agent CLI) connected to a Conjur3 FreeCAD session, lets it
build or edit the part, and collects `output.step`. Python standard library
only. See README.md in this directory.

    python3 benchmark/run.py --model claude-fable-5-2 --samples 101
    python3 benchmark/run.py --model claude-fable-5-2 --workers 4
    python3 benchmark/run.py --resume benchmark/results/<run>
"""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
import os
import platform
import queue
import shlex
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import xmlrpc.client
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DATASET = "HuggingAI4Engineering/cadgenbench-data"
HF = "https://huggingface.co"
SKIP_FILES = ("input.mesh.npz",)           # large, not used by the agent
CANDIDATE = "output.step"

# In-container mount points (docker backend).
C_DATA = "/bench/data"
C_RUN = "/bench/run"


def log(msg: str) -> None:
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


# --------------------------------------------------------------------------
# Dataset
# --------------------------------------------------------------------------

def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "conjur3-bench"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def _tree(path: str = "") -> list[dict]:
    url = f"{HF}/api/datasets/{DATASET}/tree/main"
    if path:
        url += "/" + urllib.parse.quote(path)
    return json.loads(_get(url))


def download_dataset(data_dir: Path, wanted: set[str] | None) -> None:
    """Fetch the public benchmark inputs (skips files already present)."""
    data_dir.mkdir(parents=True, exist_ok=True)
    todo: list[tuple[str, int]] = []
    for entry in _tree():
        if entry["type"] != "directory" or not entry["path"].isdigit():
            continue
        if wanted and entry["path"] not in wanted:
            continue
        stack = [entry["path"]]
        while stack:
            for e in _tree(stack.pop()):
                if e["type"] == "directory":
                    stack.append(e["path"])
                elif Path(e["path"]).name not in SKIP_FILES:
                    todo.append((e["path"], e.get("size", 0)))
    todo.append(("sanity_check_submission.py", 0))    # the benchmark's own validity checker
    for rel, size in todo:
        dest = data_dir / rel
        if dest.exists() and (not size or dest.stat().st_size == size):
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        tmp.write_bytes(_get(f"{HF}/datasets/{DATASET}/resolve/main/{urllib.parse.quote(rel)}"))
        tmp.replace(dest)
        log(f"downloaded {rel}")


def read_description(sample_dir: Path) -> dict:
    """Minimal reader for the benchmark's description.yaml (no PyYAML needed)."""
    out: dict = {"description": "", "input_files": []}
    key = None
    for raw in (sample_dir / "description.yaml").read_text().splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if not raw.startswith((" ", "\t")) and ":" in line:
            key, _, val = line.partition(":")
            key, val = key.strip(), val.strip()
            if key == "input_files":
                out[key] = []
            elif val in (">", "|", ">-", "|-", ""):
                out[key] = ""
            else:
                out[key] = val.strip("\"'")
        elif key == "input_files" and line.strip().startswith("-"):
            out[key].append(line.strip()[1:].strip().strip("\"'"))
        elif key:
            out[key] = (str(out.get(key, "")) + " " + line.strip()).strip()
    edit = sample_dir / "edit_description.txt"
    if edit.exists() and edit.read_text().strip():
        out["description"] = edit.read_text().strip()
    if "task_type" not in out:
        out["task_type"] = "editing" if (sample_dir / "input.step").exists() else "generation"
    return out


# --------------------------------------------------------------------------
# FreeCAD sessions ("workers")
# --------------------------------------------------------------------------

class Worker:
    """One FreeCAD + Conjur3 MCP session that handles one sample at a time."""

    mcp_url: str
    name: str

    def run_python(self, code: str, timeout: int = 120) -> str:
        """Run Python inside FreeCAD through the addon; return its stdout."""
        raise NotImplementedError

    def path_in_session(self, host_path: Path) -> str:
        return str(host_path)

    def start(self) -> None: ...
    def restart(self) -> None: ...
    def stop(self) -> None: ...
    def fix_ownership(self, path: Path) -> None: ...

    def wait_ready(self, seconds: int = 240) -> None:
        deadline = time.time() + seconds
        last = ""
        while time.time() < deadline:
            try:
                if "ready" in self.run_python("print('ready')", timeout=20):
                    return
            except Exception as e:  # noqa: BLE001 - keep polling
                last = str(e)
            time.sleep(3)
        raise RuntimeError(f"{self.name}: FreeCAD did not become ready ({last[:200]})")

    def reset(self) -> None:
        """Close every open document so the next sample starts clean."""
        self.run_python(
            "import FreeCAD\n"
            "for n in list(FreeCAD.listDocuments()):\n"
            "    FreeCAD.closeDocument(n)\n"
            "print('reset')\n")

    def info(self) -> str:
        return self.run_python(
            "import FreeCAD\nprint('.'.join(FreeCAD.Version()[:3]))").strip()


_RPC_SNIPPET = (
    "import sys,xmlrpc.client,socket\n"
    "socket.setdefaulttimeout(float(sys.argv[2]))\n"
    "p=xmlrpc.client.ServerProxy('http://localhost:'+sys.argv[1],allow_none=True)\n"
    "r=p.execute_code(sys.stdin.read(),int(float(sys.argv[2])*1000))\n"
    "ok=isinstance(r,dict) and r.get('success')\n"
    "sys.stdout.write(r.get('stdout','') if ok else '')\n"
    "sys.stderr.write('' if ok else str(r))\n"
    "sys.exit(0 if ok else 1)\n"
)


class DockerWorker(Worker):
    def __init__(self, idx: int, image: str, data_dir: Path, run_dir: Path, base_port: int):
        self.name = f"conjur3-bench-{idx}"
        self.image = image
        self.data_dir, self.run_dir = data_dir, run_dir
        self.mcp_port = base_port + idx
        self.vnc_port = base_port + 100 + idx
        self.mcp_url = f"http://127.0.0.1:{self.mcp_port}/mcp"

    def path_in_session(self, host_path: Path) -> str:
        host_path = host_path.resolve()
        for host_root, c_root in ((self.run_dir.resolve(), C_RUN), (self.data_dir.resolve(), C_DATA)):
            try:
                return f"{c_root}/{host_path.relative_to(host_root).as_posix()}"
            except ValueError:
                continue
        raise ValueError(f"{host_path} is not under the data or run directory")

    def start(self) -> None:
        subprocess.run(["docker", "rm", "-f", self.name], capture_output=True)
        cmd = ["docker", "run", "-d", "--name", self.name, "--shm-size", "512m",
               "-p", f"127.0.0.1:{self.mcp_port}:8765",
               "-p", f"127.0.0.1:{self.vnc_port}:6080",
               "-v", f"{self.data_dir.resolve()}:{C_DATA}:ro",
               "-v", f"{self.run_dir.resolve()}:{C_RUN}",
               self.image]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        self.wait_ready()
        log(f"{self.name}: ready — MCP {self.mcp_url}, watch at http://127.0.0.1:{self.vnc_port}/vnc.html")

    def restart(self) -> None:
        log(f"{self.name}: restarting FreeCAD")
        subprocess.run(["docker", "restart", "-t", "5", self.name], capture_output=True)
        self.wait_ready()

    def stop(self) -> None:
        subprocess.run(["docker", "rm", "-f", self.name], capture_output=True)

    def run_python(self, code: str, timeout: int = 120) -> str:
        p = subprocess.run(
            ["docker", "exec", "-i", self.name, "python3", "-c", _RPC_SNIPPET, "9875", str(timeout)],
            input=code, capture_output=True, text=True, timeout=timeout + 30)
        if p.returncode != 0:
            raise RuntimeError(p.stderr.strip() or "execute_code failed")
        return p.stdout

    def fix_ownership(self, path: Path) -> None:
        if hasattr(os, "getuid"):
            subprocess.run(["docker", "exec", self.name, "chown", "-R",
                            f"{os.getuid()}:{os.getgid()}", self.path_in_session(path)],
                           capture_output=True)


class NativeWorker(Worker):
    """A FreeCAD you started yourself, with the Conjur3 addon and MCP server."""

    def __init__(self, mcp_url: str, rpc_port: int):
        self.name = "native"
        self.mcp_url = mcp_url
        self.rpc_port = rpc_port

    def start(self) -> None:
        self.wait_ready(30)
        log(f"native FreeCAD ready — MCP {self.mcp_url}")

    def restart(self) -> None:
        raise RuntimeError("FreeCAD is unresponsive; restart it and rerun with --resume")

    def run_python(self, code: str, timeout: int = 120) -> str:
        import socket
        socket.setdefaulttimeout(timeout + 10)
        proxy = xmlrpc.client.ServerProxy(f"http://localhost:{self.rpc_port}", allow_none=True)
        r = proxy.execute_code(code, timeout * 1000)
        if not (isinstance(r, dict) and r.get("success")):
            raise RuntimeError(str(r))
        return r.get("stdout", "")


# --------------------------------------------------------------------------
# Prompt
# --------------------------------------------------------------------------

def finalize_script(out_path: str, canonical: bool) -> str:
    src = (HERE / "finalize.py").read_text()
    return (src.replace("__OUT_PATH__", out_path)
               .replace("__CANONICAL_POSE__", "True" if canonical else "False"))


def build_prompt(sample_id: str, desc: dict, sample_dir: Path, work: Path, worker: Worker,
                 style: str = "tools") -> str:
    task = desc["task_type"]
    out_in_session = worker.path_in_session(work / CANDIDATE)
    if task == "editing":
        images = sorted((sample_dir / "renders").glob("*.png")) if (sample_dir / "renders").is_dir() else []
    else:
        images = [sample_dir / f for f in desc.get("input_files", []) if f.lower().endswith((".png", ".jpg", ".jpeg"))]
        images = images or sorted(sample_dir.glob("input*.png"))
    # Copy the images next to the agent's working directory so a sandboxed
    # file reader can open them.
    inputs = work / "inputs"
    inputs.mkdir(exist_ok=True)
    images = [Path(shutil.copy2(p, inputs / p.name)) for p in images if p.is_file()]
    template = (HERE / "prompts" / f"{task}.md").read_text()
    body = template.format(
        sample_id=sample_id,
        description=desc["description"],
        image_list="\n".join(f"- `{p.resolve()}`" for p in images) or "- (none provided)",
        input_step=worker.path_in_session(sample_dir / "input.step") if task == "editing" else "",
        finalize_script=finalize_script(out_in_session, canonical=(task == "generation")),
    )
    common = (HERE / "prompts" / "common.md").read_text().replace(
        "<<TOOL_RULE>>", (HERE / "prompts" / f"style_{style}.md").read_text().rstrip())
    return common + "\n" + body


# --------------------------------------------------------------------------
# Agents
# --------------------------------------------------------------------------

def agent_command(args, worker: Worker, work: Path, prompt_file: Path) -> tuple[list[str], str | None]:
    """Return (argv, stdin_text)."""
    if args.agent == "claude":
        cfg = work / "mcp.json"
        cfg.write_text(json.dumps({"mcpServers": {"conjur3": {"type": "http", "url": worker.mcp_url}}}))
        argv = ["claude", "-p", "--model", args.model,
                "--mcp-config", str(cfg), "--strict-mcp-config",
                "--tools", "Read",
                "--allowedTools", "Read", "mcp__conjur3",
                "--permission-prompts", "none",
                "--output-format", "stream-json", "--verbose",
                "--no-session-persistence"]
        argv += shlex.split(args.agent_args or "")
        return argv, prompt_file.read_text()
    fields = {"model": args.model, "mcp_url": worker.mcp_url,
              "prompt_file": str(prompt_file), "workdir": str(work)}
    return [a.format(**fields) for a in shlex.split(args.agent_cmd)], None


def summarize_transcript(path: Path) -> dict:
    """Pull turn count, cost and image count out of a Claude Code stream-json log."""
    out: dict = {}
    images = tool_calls = 0
    tools: dict[str, int] = {}
    try:
        for line in path.read_text(errors="replace").splitlines():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("type") == "result":
                for k in ("num_turns", "total_cost_usd", "duration_ms", "is_error", "subtype"):
                    if k in ev:
                        out[k] = ev[k]
            content = (ev.get("message") or {}).get("content")
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_use":
                        tool_calls += 1
                        name = str(block.get("name", "?")).replace("mcp__conjur3__", "")
                        tools[name] = tools.get(name, 0) + 1
                    if block.get("type") == "tool_result" and isinstance(block.get("content"), list):
                        images += sum(1 for c in block["content"]
                                      if isinstance(c, dict) and c.get("type") == "image")
    except OSError:
        pass
    if tool_calls:
        out["tool_calls"] = tool_calls
        out["images_seen"] = images
        out["tools"] = dict(sorted(tools.items(), key=lambda kv: -kv[1]))
    return out


# --------------------------------------------------------------------------
# One sample
# --------------------------------------------------------------------------

INSPECT = """
import json, Part
s = Part.Shape(); s.read({path!r})
try:
    s.tessellate(0.05)      # tightens BoundBox on curved faces
except Exception:
    pass
b = s.BoundBox
print("INSPECT " + json.dumps({{
    "is_valid": bool(s.isValid()), "solids": len(s.Solids),
    "all_shells_closed": bool(s.Shells) and all(x.isClosed() for x in s.Shells),
    "faces": len(s.Faces), "volume_mm3": round(float(s.Volume), 3),
    "bbox_mm": [round(b.XLength, 3), round(b.YLength, 3), round(b.ZLength, 3)]}}))
"""


def run_sample(args, sample_id: str, worker: Worker, data_dir: Path, run_dir: Path) -> dict:
    sample_dir = data_dir / sample_id
    work = run_dir / sample_id
    work.mkdir(parents=True, exist_ok=True)
    for stale in (CANDIDATE, "status.json"):
        (work / stale).unlink(missing_ok=True)
    desc = read_description(sample_dir)
    status: dict = {"sample": sample_id, "task_type": desc["task_type"], "model": args.model,
                    "agent": args.agent, "started": dt.datetime.now(dt.timezone.utc).isoformat()}
    try:
        worker.reset()
    except Exception:  # noqa: BLE001 - a wedged FreeCAD gets one restart
        worker.restart()
        worker.reset()

    prompt_file = work / "prompt.md"
    prompt_file.write_text(build_prompt(sample_id, desc, sample_dir, work, worker, args.style))
    argv, stdin_text = agent_command(args, worker, work, prompt_file)
    t0 = time.time()
    transcript = work / "transcript.jsonl"
    with transcript.open("w") as out, (work / "agent.stderr.log").open("w") as err:
        try:
            p = subprocess.run(argv, input=stdin_text, stdout=out, stderr=err, text=True,
                               cwd=work, timeout=args.timeout,
                               env={**os.environ, "CONJUR3_MCP_URL": worker.mcp_url})
            status["agent_exit"] = p.returncode
        except subprocess.TimeoutExpired:
            status["timed_out"] = True
        except FileNotFoundError:
            raise SystemExit(f"agent command not found: {argv[0]}")
    status["seconds"] = round(time.time() - t0, 1)
    status.update(summarize_transcript(transcript))

    worker.fix_ownership(work)
    candidate = work / CANDIDATE
    if candidate.is_file() and candidate.stat().st_size > 0:
        try:
            out = worker.run_python(INSPECT.format(path=worker.path_in_session(candidate)))
            line = next(l for l in out.splitlines() if l.startswith("INSPECT "))
            status["inspect"] = json.loads(line[len("INSPECT "):])
            ins = status["inspect"]
            ok = ins["is_valid"] and ins["solids"] == 1 and ins["all_shells_closed"]
            status["result"] = "ok" if ok else "invalid"
        except Exception as e:  # noqa: BLE001
            status["result"] = "unchecked"
            status["inspect_error"] = str(e)[:300]
    else:
        status["result"] = "missing"
    if status.get("timed_out"):
        try:
            worker.restart()      # the agent may have left FreeCAD mid-operation
        except Exception as e:  # noqa: BLE001
            status["restart_error"] = str(e)[:200]
    (work / "status.json").write_text(json.dumps(status, indent=2) + "\n")
    log(f"{sample_id} [{desc['task_type']}] → {status['result']} in {status['seconds']:.0f}s"
        + (" (timed out)" if status.get("timed_out") else ""))
    return status


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def git_commit() -> str:
    try:
        rev = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--", "conjur3", "benchmark"],
                               capture_output=True, text=True).stdout.strip()
        return rev + ("-dirty" if dirty else "")
    except OSError:
        return "unknown"


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", help="model id passed to the agent and recorded in the results")
    ap.add_argument("--agent", choices=["claude", "custom"], default="claude")
    ap.add_argument("--agent-args", help="extra arguments appended to the claude command line")
    ap.add_argument("--agent-cmd", help="custom agent command; placeholders: {model} {mcp_url} {prompt_file} {workdir}")
    ap.add_argument("--samples", nargs="*", help="sample ids (default: all)")
    ap.add_argument("--task", choices=["generation", "editing", "all"], default="all")
    ap.add_argument("--style", choices=["tools", "free"], default="tools",
                    help="tools: build with Conjur3's first-class tools (default); "
                         "free: the agent may script geometry with execute_code")
    ap.add_argument("--workers", type=int, default=1, help="parallel FreeCAD sessions (docker backend)")
    ap.add_argument("--timeout", type=int, default=1800, help="seconds allowed per sample")
    ap.add_argument("--backend", choices=["docker", "native"], default="docker")
    ap.add_argument("--image", default="conjur3:bench")
    ap.add_argument("--build", action="store_true", help="(re)build the docker image first")
    ap.add_argument("--base-port", type=int, default=18765)
    ap.add_argument("--mcp-url", default="http://127.0.0.1:8765/mcp", help="native backend: MCP endpoint")
    ap.add_argument("--rpc-port", type=int, default=9875, help="native backend: addon RPC port")
    ap.add_argument("--data-dir", type=Path, default=HERE / "data")
    ap.add_argument("--run-name")
    ap.add_argument("--resume", type=Path, help="continue an earlier run directory")
    ap.add_argument("--retry", nargs="*", default=[], metavar="RESULT",
                    help="with --resume, also redo samples whose result is one of: missing invalid unchecked")
    ap.add_argument("--keep-containers", action="store_true")
    args = ap.parse_args()
    if args.resume:
        saved = json.loads((args.resume / "params.json").read_text())
        for k in ("model", "agent", "agent_args", "agent_cmd", "timeout", "backend", "image", "task", "style"):
            if getattr(args, k) in (None, ap.get_default(k)):
                setattr(args, k, saved.get(k, getattr(args, k)))
    if not args.model:
        ap.error("--model is required")
    if args.agent == "custom" and not args.agent_cmd:
        ap.error("--agent custom needs --agent-cmd")
    if args.backend == "native" and args.workers != 1:
        ap.error("the native backend runs one sample at a time (--workers 1)")
    return args


def main() -> int:
    args = parse_args()
    data_dir = args.data_dir.resolve()
    wanted = set(args.samples) if args.samples else None
    log("checking benchmark inputs …")
    download_dataset(data_dir, wanted)
    samples = sorted(p.name for p in data_dir.iterdir() if p.is_dir() and (p / "description.yaml").exists())
    if wanted:
        samples = [s for s in samples if s in wanted]
    if args.task != "all":
        samples = [s for s in samples if read_description(data_dir / s)["task_type"] == args.task]
    if not samples:
        raise SystemExit("no samples selected")

    if args.resume:
        run_dir = args.resume.resolve()
    else:
        name = args.run_name or f"{dt.datetime.now():%Y%m%d_%H%M%S}_{args.model.replace('/', '-')}"
        run_dir = (HERE / "results" / name).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)

    def done(s: str) -> bool:
        f = run_dir / s / "status.json"
        if not f.exists():
            return False
        return json.loads(f.read_text()).get("result") not in set(args.retry)

    todo = [s for s in samples if not (args.resume and done(s))]
    log(f"run dir {run_dir} — {len(todo)} of {len(samples)} samples to run")
    if not todo:
        return 0

    if args.backend == "docker":
        if args.build or not subprocess.run(["docker", "image", "inspect", args.image],
                                            capture_output=True).returncode == 0:
            log(f"building {args.image} (first build takes several minutes) …")
            subprocess.run(["docker", "build", "--build-arg", "CLOUDFLARED_VER=skip",
                            "-t", args.image, str(REPO / "conjur3")], check=True)
        workers: list[Worker] = [DockerWorker(i, args.image, data_dir, run_dir, args.base_port)
                                 for i in range(min(args.workers, len(todo)))]
    else:
        workers = [NativeWorker(args.mcp_url, args.rpc_port)]

    try:
        for w in workers:
            w.start()
        params = {k: (str(v) if isinstance(v, Path) else v) for k, v in vars(args).items()}
        params.update(conjur3_commit=git_commit(), freecad=workers[0].info(),
                      host=f"{platform.system()} {platform.machine()}", dataset=DATASET,
                      started=dt.datetime.now(dt.timezone.utc).isoformat())
        if not (run_dir / "params.json").exists():
            (run_dir / "params.json").write_text(json.dumps(params, indent=2) + "\n")

        free: queue.Queue = queue.Queue()
        for w in workers:
            free.put(w)

        def job(s: str) -> dict:
            w = free.get()
            try:
                return run_sample(args, s, w, data_dir, run_dir)
            except Exception as e:  # noqa: BLE001 - one bad sample must not stop the run
                log(f"{s} → runner error: {e}")
                return {"sample": s, "result": "error", "error": str(e)[:300]}
            finally:
                free.put(w)

        with concurrent.futures.ThreadPoolExecutor(len(workers)) as pool:
            list(pool.map(job, todo))
    finally:
        if not args.keep_containers:
            for w in workers:
                w.stop()

    counts: dict[str, int] = {}
    secs = cost = 0.0
    for s in samples:
        f = run_dir / s / "status.json"
        st = json.loads(f.read_text()) if f.exists() else {"result": "not run"}
        counts[st["result"]] = counts.get(st["result"], 0) + 1
        secs += st.get("seconds", 0)
        cost += st.get("total_cost_usd", 0) or 0
    log("summary: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        + f" | agent time {secs / 3600:.1f} h" + (f" | reported cost ${cost:.2f}" if cost else ""))
    log(f"next: python3 benchmark/package.py {run_dir} --submitter \"<your name>\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
