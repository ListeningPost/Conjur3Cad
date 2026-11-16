"""Build the CADGenBench result graphics for the Conjur3 README.

Reads the leaderboard's public results.jsonl and writes light and dark SVGs.
Usage: python3 -I make_charts.py <results.jsonl> <out_dir>
"""
import datetime as dt
import json
import statistics
import sys
from pathlib import Path

RESULTS, OUT = Path(sys.argv[1]), Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)
OURS = ("anonymous-agent-setup + claude-fable-5-2", "2026-11-14T16:22")   # this run's leaderboard row

rows = [json.loads(l) for l in RESULTS.open() if l.strip()]
ours = next(r for r in rows if r["submission_name"] == OURS[0] and r["submitted_at"].startswith(OURS[1]))
S = ours["aggregate_score"]
done = [r for r in rows if r["status"] == "completed" and r.get("aggregate_score") is not None]
others = sorted((r for r in done if r is not ours), key=lambda r: r["submitted_at"])
snapshot = max(r["submitted_at"] for r in rows)[:10]

def day(ts):
    return dt.date.fromisoformat(ts[:10])

# Record progression (best score submitted so far, by any team).
steps, best = [], 0.0
for r in others:
    if r["aggregate_score"] > best:
        best = r["aggregate_score"]
        steps.append((day(r["submitted_at"]), best))
start, end = steps[0][0], dt.date.fromisoformat(snapshot)
overtaken = next(d for d, v in steps if v > S)          # first day the record passed us
lead_days = (overtaken - start).days

def best_before(date_iso):
    prior = [r for r in others if r["submitted_at"] < date_iso]
    return max(prior, key=lambda r: r["aggregate_score"])

june = best_before("2026-06-25T21:00:00Z")
pre_aug = best_before(overtaken.isoformat())
leader = max(others, key=lambda r: r["aggregate_score"])
median = statistics.median(r["aggregate_score"] for r in others)
rank_now = 1 + sum(r["aggregate_score"] > S for r in others)
n_now = len(others) + 1
pct_top = 100 * rank_now / n_now
# Standing on the day of submission: only rows submitted before ours.
prior = [r for r in others if r["submitted_at"] < ours["submitted_at"]]
rank_sub = 1 + sum(r["aggregate_score"] > S for r in prior)
n_sub = len(prior) + 1
pct_sub = 100 * rank_sub / n_sub
sub_day = day(ours["submitted_at"])

THEMES = {
    "light": dict(surface="#fcfcfb", grid="#e4e3df", axis="#c9c8c2", text="#0b0b0b",
                  text2="#52514e", muted="#6f6e69", series="#2a78d6", accent="#eb6834",
                  band="#eb6834", band_op="0.10", neutral="#8fb6e8"),
    "dark": dict(surface="#1a1a19", grid="#2c2c2a", axis="#45453f", text="#f0efec",
                 text2="#c3c2b7", muted="#9a998f", series="#3987e5", accent="#d95926",
                 band="#d95926", band_op="0.16", neutral="#2f5d94"),
}
FONT = "ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"

def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def fmt_date(d):
    return f"{d.day} {d:%b}"

# ---------------------------------------------------------------------------
# Chart 1: the leaderboard record over time, with our score as a reference.
# ---------------------------------------------------------------------------
def timeline(t):
    W, H = 900, 450
    L, R, T, B = 64, 28, 92, 90
    pw, ph = W - L - R, H - T - B
    span = (end - start).days
    x = lambda d: L + pw * (d - start).days / span
    y = lambda v: T + ph * (1 - v)
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
         f'font-family="{FONT}" role="img" aria-labelledby="t d">',
         f'<title id="t">Best CADGenBench score submitted so far, versus Conjur3\'s 0.595</title>',
         f'<desc id="d">Step line of the highest CADGenBench score on the public leaderboard from '
         f'{fmt_date(start)} to {fmt_date(end)} 2026, with a horizontal line at 0.595 for Conjur3 with '
         f'Claude Fable 5.2, submitted 14 Nov 2026. The record stayed below 0.595 until '
         f'{fmt_date(overtaken)} 2026, {lead_days} days after the leaderboard opened.</desc>',
         f'<rect width="{W}" height="{H}" rx="12" fill="{t["surface"]}"/>',
         f'<text x="{L}" y="34" font-size="18" font-weight="700" fill="{t["text"]}">'
         f'Best score on the CADGenBench leaderboard, by date submitted</text>',
         f'<text x="{L}" y="58" font-size="13" fill="{t["text2"]}">'
         f'Conjur3\'s 0.595 would have been the top score for the leaderboard\'s first {lead_days} days</text>']
    # band where 0.595 would have led
    o.append(f'<rect x="{x(start):.1f}" y="{T}" width="{x(overtaken)-x(start):.1f}" height="{ph}" '
             f'fill="{t["band"]}" fill-opacity="{t["band_op"]}"/>')
    # grid + y axis
    for v in (0, .2, .4, .6, .8, 1.0):
        o.append(f'<line x1="{L}" x2="{L+pw}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="{t["grid"]}" stroke-width="1"/>')
        o.append(f'<text x="{L-10}" y="{y(v)+4:.1f}" font-size="12" text-anchor="end" fill="{t["muted"]}">{v:.1f}</text>')
    o.append(f'<text x="18" y="{T+ph/2:.1f}" font-size="12" fill="{t["muted"]}" transform="rotate(-90 18 {T+ph/2:.1f})" text-anchor="middle">CAD Score (0–1)</text>')
    # x axis: month ticks
    m = dt.date(start.year, start.month, 1)
    while m <= end:
        if m >= start:
            o.append(f'<line x1="{x(m):.1f}" x2="{x(m):.1f}" y1="{T+ph}" y2="{T+ph+5}" stroke="{t["axis"]}"/>')
            o.append(f'<text x="{x(m):.1f}" y="{T+ph+20}" font-size="12" text-anchor="middle" fill="{t["muted"]}">{m:%b}</text>')
        m = dt.date(m.year + (m.month // 12), m.month % 12 + 1, 1)
    o.append(f'<line x1="{L}" x2="{L+pw}" y1="{T+ph}" y2="{T+ph}" stroke="{t["axis"]}" stroke-width="1"/>')
    # record step line
    pts, prev = [], None
    for d, v in steps:
        if prev is not None:
            pts.append(f"{x(d):.1f},{y(prev):.1f}")
        pts.append(f"{x(d):.1f},{y(v):.1f}")
        prev = v
    pts.append(f"{x(end):.1f},{y(prev):.1f}")
    o.append(f'<polyline points="{" ".join(pts)}" fill="none" stroke="{t["series"]}" stroke-width="2" stroke-linejoin="round"/>')
    # our reference line + submission marker
    o.append(f'<line x1="{x(start):.1f}" x2="{x(end):.1f}" y1="{y(S):.1f}" y2="{y(S):.1f}" stroke="{t["accent"]}" stroke-width="2"/>')
    sub = day(ours["submitted_at"])
    o.append(f'<circle cx="{x(sub):.1f}" cy="{y(S):.1f}" r="5" fill="{t["accent"]}" stroke="{t["surface"]}" stroke-width="2"/>')
    # overtaken marker
    o.append(f'<circle cx="{x(overtaken):.1f}" cy="{y(S):.1f}" r="4" fill="{t["surface"]}" stroke="{t["accent"]}" stroke-width="2"/>')
    # annotations
    o.append(f'<text x="{x(start)+8:.1f}" y="{y(S)-10:.1f}" font-size="12.5" font-weight="600" fill="{t["text"]}">Conjur3 + Claude Fable 5.2: {S:.3f}</text>')
    o.append(f'<text x="{x(start)+8:.1f}" y="{T+20}" font-size="12" fill="{t["text2"]}">0.595 above every entry</text>')
    o.append(f'<text x="{x(start)+8:.1f}" y="{T+36}" font-size="12" fill="{t["text2"]}">{fmt_date(start)} – {fmt_date(overtaken - dt.timedelta(days=1))}</text>')
    o.append(f'<text x="{x(overtaken)+8:.1f}" y="{y(S)+20:.1f}" font-size="12" fill="{t["text2"]}">{fmt_date(overtaken)}: first entry above it ({pre_aug_next:.3f})</text>')
    o.append(f'<text x="{x(end)-4:.1f}" y="{y(steps[-1][1])-10:.1f}" font-size="12" text-anchor="end" fill="{t["text2"]}">Leader on {fmt_date(end)}: {steps[-1][1]:.3f}</text>')
    o.append(f'<text x="{x(sub)-8:.1f}" y="{y(S)+20:.1f}" font-size="12" text-anchor="end" fill="{t["text2"]}">submitted {fmt_date(sub)}</text>')
    # legend
    ly = H - 44
    o.append(f'<line x1="{L}" x2="{L+22}" y1="{ly}" y2="{ly}" stroke="{t["series"]}" stroke-width="2"/>')
    o.append(f'<text x="{L+30}" y="{ly+4}" font-size="12" fill="{t["text2"]}">Best score submitted so far (all teams, all models)</text>')
    o.append(f'<line x1="{L+370}" x2="{L+392}" y1="{ly}" y2="{ly}" stroke="{t["accent"]}" stroke-width="2"/>')
    o.append(f'<text x="{L+400}" y="{ly+4}" font-size="12" fill="{t["text2"]}">Conjur3 run, 14 Nov 2026 (Claude Fable 5.2)</text>')
    o.append(f'<text x="{L}" y="{ly+26}" font-size="11" fill="{t["muted"]}">Source: CADGenBench public results file, snapshot {snapshot}. '
             f'Earlier entries used the models available at the time; this run used Claude Fable 5.2.</text>')
    o.append("</svg>")
    return "\n".join(o)

pre_aug_next = next(v for d, v in steps if v > S)

# ---------------------------------------------------------------------------
# Chart 2: where 0.595 sits against reference points.
# ---------------------------------------------------------------------------
def bars(t):
    items = [
        (f"Leaderboard leader, {fmt_date(end)} 2026", leader["aggregate_score"], False),
        ("Conjur3 + Claude Fable 5.2 (this run)", S, True),
        (f"Best entry before {fmt_date(overtaken)} 2026", pre_aug["aggregate_score"], False),
        ("Best entry on 25 Jun 2026 (Hugging Face baseline)", june["aggregate_score"], False),
        (f"Median of all {n_now - 1:,} other submissions", median, False),
    ]
    W, rowh, T, L, R = 900, 46, 84, 330, 70
    H = T + rowh * len(items) + 44
    pw = W - L - R
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
         f'font-family="{FONT}" role="img" aria-labelledby="t2 d2">',
         '<title id="t2">CADGenBench score: Conjur3 against reference points</title>',
         '<desc id="d2">' + esc("; ".join(f"{n}: {v:.3f}" for n, v, _ in items)) + '</desc>',
         f'<rect width="{W}" height="{H}" rx="12" fill="{t["surface"]}"/>',
         f'<text x="28" y="34" font-size="18" font-weight="700" fill="{t["text"]}">Where 0.595 sits</text>',
         f'<text x="28" y="58" font-size="13" fill="{t["text2"]}">CAD Score, 0 to 1. Leaderboard snapshot {snapshot}.</text>']
    for v in (0, .25, .5, .75, 1.0):
        gx = L + pw * v
        o.append(f'<line x1="{gx:.1f}" x2="{gx:.1f}" y1="{T-8}" y2="{T+rowh*len(items)}" stroke="{t["grid"]}" stroke-width="1"/>')
        o.append(f'<text x="{gx:.1f}" y="{T+rowh*len(items)+18}" font-size="11.5" text-anchor="middle" fill="{t["muted"]}">{v:g}</text>')
    for i, (name, v, mine) in enumerate(items):
        cy = T + i * rowh + rowh / 2
        fill = t["accent"] if mine else t["series"]
        bw = max(pw * v, 2)
        o.append(f'<text x="{L-14}" y="{cy+4:.1f}" font-size="13" text-anchor="end" '
                 f'font-weight="{700 if mine else 400}" fill="{t["text"] if mine else t["text2"]}">{esc(name)}</text>')
        o.append(f'<path d="M{L},{cy-11:.1f} h{bw-4:.1f} a4,4 0 0 1 4,4 v14 a4,4 0 0 1 -4,4 h-{bw-4:.1f} z" fill="{fill}"/>')
        o.append(f'<text x="{L+bw+8:.1f}" y="{cy+4:.1f}" font-size="13" font-weight="{700 if mine else 400}" fill="{t["text"]}">{v:.3f}</text>')
    o.append("</svg>")
    return "\n".join(o)

# ---------------------------------------------------------------------------
# Banner: three headline numbers.
# ---------------------------------------------------------------------------
def banner(t):
    W, H = 900, 170
    tiles = [
        (f"{S:.3f}", "CAD Score on CADGenBench", "81 tasks, private ground truth"),
        (f"Top {pct_sub:.0f}%", f"Submitted {fmt_date(sub_day)}: rank {rank_sub} of {n_sub:,}",
         f"{fmt_date(end)}: top {pct_top:.0f}%, rank {rank_now} of {n_now:,}"),
        (f"{lead_days} days", "it would have led the leaderboard", f"{fmt_date(start)} – {fmt_date(overtaken - dt.timedelta(days=1))} 2026"),
    ]
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
         f'font-family="{FONT}" role="img" aria-labelledby="t3 d3">',
         '<title id="t3">Conjur3 on CADGenBench</title>',
         '<desc id="d3">' + esc(" · ".join(f"{a} {b} ({c})" for a, b, c in tiles)) + '</desc>',
         f'<rect width="{W}" height="{H}" rx="12" fill="{t["surface"]}"/>']
    tw = (W - 2 * 24 - 2 * 16) / 3
    for i, (big, line1, line2) in enumerate(tiles):
        x0 = 24 + i * (tw + 16)
        o.append(f'<rect x="{x0:.1f}" y="24" width="{tw:.1f}" height="{H-48}" rx="10" fill="none" stroke="{t["grid"]}" stroke-width="1.5"/>')
        o.append(f'<rect x="{x0:.1f}" y="24" width="4" height="{H-48}" rx="2" fill="{t["accent"] if i == 0 else t["series"]}"/>')
        o.append(f'<text x="{x0+24:.1f}" y="78" font-size="34" font-weight="800" fill="{t["text"]}">{esc(big)}</text>')
        o.append(f'<text x="{x0+24:.1f}" y="104" font-size="13.5" fill="{t["text2"]}">{esc(line1)}</text>')
        o.append(f'<text x="{x0+24:.1f}" y="124" font-size="12" fill="{t["muted"]}">{esc(line2)}</text>')
    o.append("</svg>")
    return "\n".join(o)

for mode, t in THEMES.items():
    (OUT / f"cadgenbench-timeline-{mode}.svg").write_text(timeline(t))
    (OUT / f"cadgenbench-standing-{mode}.svg").write_text(bars(t))
    (OUT / f"cadgenbench-banner-{mode}.svg").write_text(banner(t))

print(json.dumps(dict(score=S, rank_sub=rank_sub, n_sub=n_sub, pct_sub=round(pct_sub, 1), rank=rank_now, n=n_now, pct_top=round(pct_top, 1), lead_days=lead_days,
                      overtaken=str(overtaken), first_above=pre_aug_next, june=june["aggregate_score"],
                      pre_aug=pre_aug["aggregate_score"], leader=leader["aggregate_score"],
                      median=round(median, 4), snapshot=snapshot, start=str(start))))
