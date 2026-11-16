# Running CADGenBench with Conjur3

[CADGenBench](https://github.com/huggingface/cadgenbench) measures how well an
AI system produces correct mechanical parts. It has 81 samples: 49 where the
system builds a part from an engineering drawing, and 32 where it applies a
requested change to an existing STEP file. A submission is one `output.step`
per sample, scored by the benchmark's
[leaderboard](https://huggingface.co/spaces/HuggingAI4Engineering/CADGenBench)
against ground truth that is not public.

This directory runs that benchmark with Conjur3: for each sample it starts a
fresh AI agent, connects it to a FreeCAD session through the Conjur3 MCP
server, and collects the STEP file the agent exports. Anyone can run it, with
any model their agent client supports.

## What you need

- Linux on x86-64 (the only platform this has been run on)
- Docker
- Python 3.10 or newer (standard library only, nothing to install)
- An agent CLI. The default is [Claude Code](https://claude.com/claude-code),
  signed in; see [Other agents](#other-agents) for anything else
- About 6 GB of disk for the Docker image and 100 MB for the benchmark inputs

## Quick start

From the repository root:

```bash
# 1. One sample, to check everything works (builds the Docker image on first use)
python3 benchmark/run.py --model claude-fable-5-2 --samples 101

# 2. The whole benchmark
python3 benchmark/run.py --model claude-fable-5-2 --workers 4

# 3. Package the run for the leaderboard
python3 benchmark/package.py benchmark/results/<run> --submitter "Your Name" --agree
```

Then upload the zip on the **Submit** tab of the
[leaderboard Space](https://huggingface.co/spaces/HuggingAI4Engineering/CADGenBench).
Scores appear there; nothing in this repository can compute them, because the
ground truth is private.

## What a run does

1. Downloads the public benchmark inputs into `benchmark/data/`.
2. Starts one Docker container per worker. Each holds FreeCAD, the Conjur3
   addon and the Conjur3 MCP server, reachable only from your machine.
3. For each sample: closes any open documents, writes the prompt, and launches
   the agent with access to two things only: the Conjur3 MCP tools and a
   read-only file tool for opening the input images.
4. The agent reads the drawing, builds the part, checks it against the drawing
   using screenshots and cross-sections, and runs a finalize script that
   validates the solid and writes `output.step`.
5. The runner re-reads the STEP file in FreeCAD, records whether it is a
   single valid closed solid, and moves on.

The prompts are in [`prompts/`](./prompts). How they use images is explained
in the main README under
[How Conjur3 guides the model with images](../README.md#how-conjur3-guides-the-model-with-images).

To watch a session live, open the noVNC address the runner prints when a
worker starts (`http://127.0.0.1:18865/vnc.html` for the first worker).

## Options

| Option | Default | Meaning |
| --- | --- | --- |
| `--model` | required | Model id passed to the agent and recorded with the results |
| `--samples 101 205 …` | all | Run only these samples |
| `--task generation\|editing\|all` | `all` | Run one of the two task families |
| `--workers N` | 1 | FreeCAD sessions to run in parallel |
| `--style tools\|free` | `tools` | `tools`: the agent builds with Conjur3's first-class tools, one feature at a time. `free`: it may script geometry in Python through `execute_code`, which is faster and cheaper but uses little of Conjur3 |
| `--timeout SECONDS` | 1800 | Time allowed per sample before the agent is stopped |
| `--resume RUN_DIR` | | Continue a run, skipping finished samples |
| `--retry missing invalid` | | With `--resume`, also redo samples with these results |
| `--agent-args "…"` | | Extra arguments for the `claude` command, e.g. `--agent-args "--effort high"` |
| `--build` | | Rebuild the Docker image (do this after pulling new Conjur3 code) |
| `--keep-containers` | | Leave the containers running afterwards |

`python3 benchmark/run.py --help` lists the rest.

### Time and cost

A sample takes as long as the agent takes; the limit is `--timeout`. Each
worker needs roughly 2 GB of memory and one agent session, so the practical
ceiling on `--workers` is your machine's memory and your model provider's rate
limits. A crash or reboot loses at most the samples in progress: rerun with
`--resume`.

With Claude Code the runner records the turn count and the cost the CLI
reports for each sample in `status.json`, and prints the total at the end.
Run a few samples first and multiply before committing to all 81.

### Other agents

Any agent that can connect to an MCP server over HTTP and open image files
can run the benchmark:

```bash
python3 benchmark/run.py --agent custom --model my-model \
  --agent-cmd 'my-agent --model {model} --mcp-server {mcp_url} --prompt-file {prompt_file}'
```

The command runs once per sample, in that sample's results folder.
Placeholders: `{model}`, `{mcp_url}` (the Conjur3 MCP endpoint for this
worker), `{prompt_file}` (the full task prompt, Markdown) and `{workdir}`.
The agent must follow the prompt and exit when done; whatever it prints is
saved as `transcript.jsonl`. Image paths in the prompt are paths on your
machine. Give the agent no shell or file-writing tools, or the result is not
a measurement of Conjur3.

Models without image input can be run by starting the MCP server with
`--only-text-feedback`, but the drawings in the generation samples are images,
so expect those samples to fail.

### Without Docker

If you already run FreeCAD 1.0 with the Conjur3 addon and the MCP server
(`conjur3-pilot --http`), point the runner at it:

```bash
python3 benchmark/run.py --backend native --model claude-fable-5-2 --samples 101
```

This uses your own FreeCAD session, one sample at a time, and closes every
open document before each sample. Do not use it on a session with unsaved work.

## Results

```
benchmark/results/<run>/
├── params.json            how the run was configured: model, agent, Conjur3 commit, FreeCAD version
└── <sample>/
    ├── output.step        the candidate (absent if the agent did not finish)
    ├── status.json        result, time, turns, calls per tool, images seen, reported cost
    ├── prompt.md          the exact prompt the agent received
    ├── transcript.jsonl   the agent's full output
    └── agent.stderr.log
```

`result` in `status.json` is one of:

- `ok`: one valid, closed solid was exported
- `invalid`: a file was exported but is not a single valid closed solid
- `missing`: no file (the agent stopped, failed or timed out first)
- `unchecked`: a file exists but the runner could not re-read it

`ok` means the file passed Conjur3's own check in FreeCAD. The leaderboard
applies its own validity gate, which is stricter in places. To run the official
gate locally before uploading, install the benchmark's code and use its
checker:

```bash
git clone https://github.com/huggingface/cadgenbench && pip install -e cadgenbench
python benchmark/data/sanity_check_submission.py benchmark/results/<run>/101/output.step
```

## Submitting and sharing

`package.py` writes two files next to the run folder:

- `<run>.zip`: what you upload. It contains `meta.json` and each sample's
  `output.step`, nothing else. Samples without a valid candidate are included
  as empty folders and score zero.
- `<run>.run_report.json`: the configuration and per-sample statistics.

Without `--agree` the zip is marked as not agreed for publication and the
leaderboard will reject it. Submissions appear publicly under the submitter
name you give.

If you run this for the Conjur3 project, please open an issue on this
repository with the leaderboard row, the `run_report.json`, and the model and
hardware you used, so results from different people can be compared.

## Keeping runs comparable

- Say which `--style` you ran; it is recorded in `params.json` and in the
  default submission notes. The two styles are different measurements.
- The Docker image installs FreeCAD from the `freecad-stable` PPA, which
  currently provides 0.21.2. `params.json` records the version used.
- Claude Code loads your personal settings, hooks and memory by default. For a
  run others can reproduce exactly, pass `--agent-args "--bare"` (this requires
  `ANTHROPIC_API_KEY`; it ignores a subscription login).

- Use the prompts as they are. If you change them, say so in `--notes`.
- One attempt per sample. Use `--retry` for samples that produced no valid
  file because of an infrastructure failure, not to reroll parts you think
  look wrong.
- Do not edit `output.step` files by hand.
- Keep the run folder. Leaderboard maintainers may ask for evidence of how a
  submission was produced, and the transcripts are that evidence.
- Report the Conjur3 commit. `params.json` records it, with `-dirty` appended
  if `conjur3/` or `benchmark/` had local changes.

## Safety

- The containers publish their ports on `127.0.0.1` only. The MCP server in
  them has no authentication and includes a tool that runs arbitrary Python
  inside the container, so do not republish those ports.
- With the default agent, the model is given the Conjur3 tools and a file
  reader, and no shell or write access to your machine. Conjur3's
  `execute_code` tool does run arbitrary Python inside the FreeCAD container,
  and the container has network access, so the model can reach the network
  from there. The transcripts of the published run show no network use; check
  yours the same way if it matters for your submission.
- Files the container writes into the run folder are handed back to your user
  when each sample finishes.

## Troubleshooting

- **`FreeCAD did not become ready`**: check `docker logs conjur3-bench-0`.
  The first start after a build can take a minute.
- **Every sample is `missing` within seconds**: the agent is failing to
  start. Read `<sample>/agent.stderr.log`; the usual causes are not being
  signed in and an unknown model id.
- **Port already in use**: pass `--base-port` with a free range. Worker *i*
  uses `base+i` for MCP and `base+100+i` for noVNC.
- **Stale image after `git pull`**: add `--build`.
