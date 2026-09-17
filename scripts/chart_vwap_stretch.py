#!/usr/bin/env python3
"""Draw the VWAP stretch picture: one self-contained HTML file, no dependencies.

    ./venv/bin/python scripts/chart_vwap_stretch.py
    ./venv/bin/python scripts/chart_vwap_stretch.py --day 2026-09-15 --open

Written 2026-09-15 for TODO.md G4b. The numbers behind the "don't chase" rule are
convincing in a table and invisible in one -- "1 wiggle" does not mean anything
until you see the band breathe through the day. Three panels:

  1. ONE SESSION. SPY, its VWAP, and the +/-1 wiggle band. The band is narrow at
     the open and fans out by the afternoon: that is the whole argument for
     measuring distance in wiggles rather than cents.
  2. THE BAND THROUGH THE DAY. Median wiggle by clock minute across every
     session on disk, against a sqrt(time-since-open) curve. Shows the same
     thing as a single number per hour.
  3. DOES IT COME BACK? Forward 30-minute move grouped by how stretched price
     was, with a 95% interval per bucket, day as the independent unit.

Reads ONLY data/backtest/underlying/<SYM>_1min.json (top it up with
scripts/fetch_1min_bars.py). It does not import replay_session or touch the
engine, the database or the broker.

VWAP and the wiggle are computed with the same formula the engine uses
(signal_generator._calculate_vwap_wiggle): a volume-weighted mean of the bar's
typical price, and the volume-weighted standard deviation around it. Rebuilt
from MINUTE BARS here, where the live engine accumulates tick by tick -- on
sessions where the engine restarted mid-day the two disagree, because the
engine's accumulator restarts with the process. See TODO.md G4b.

Colours come from the UI theme tokens (ui/src/styles.scss) so the page is
readable in light and dark, and profit/loss keying matches the app.
"""
import argparse
import json
import math
import os
import statistics
import subprocess
import sys
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENTRY_START, ENTRY_END = "10:00", "15:45"     # the live strategy window, ET
HORIZON = 30                                   # minutes ahead
BUCKETS = [(0.5, "on the line", "<0.5"),
           (1.0, "a bit away", "0.5-1"),
           (2.0, "clearly away", "1-2"),
           (math.inf, "far away", ">2")]
W, H = 1120, 380                               # panel viewBox


def load(symbol):
    path = os.path.join(REPO, "data", "backtest", "underlying", f"{symbol}_1min.json")
    if not os.path.exists(path):
        sys.exit(f"No {path}. Run scripts/fetch_1min_bars.py first.")
    with open(path) as fh:
        return json.load(fh)


def session_track(bars):
    """Per minute: (hhmm, close, vwap, wiggle) accumulating from the open."""
    sum_pv = sum_v = sum_p2v = 0.0
    out = []
    for b in bars:
        price = b.get("price") or b.get("close")
        vol = b.get("volume") or 0
        if price is None:
            continue
        if vol > 0:
            sum_pv += price * vol
            sum_v += vol
            sum_p2v += price * price * vol
        if sum_v <= 0:
            continue
        vwap = sum_pv / sum_v
        var = sum_p2v / sum_v - vwap * vwap
        wiggle = math.sqrt(var) if var > 0 else None
        out.append((b["time"][11:16], b.get("close", price), vwap, wiggle))
    return out


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def mean_ci(values):
    """Mean and a 95% interval, t-ish via 1.96 -- day is the unit, so n is small."""
    if not values:
        return None, None, None
    m = statistics.fmean(values)
    if len(values) < 2:
        return m, None, None
    se = statistics.stdev(values) / math.sqrt(len(values))
    return m, m - 1.96 * se, m + 1.96 * se


# ----------------------------------------------------------------- panel 1
def panel_session(track, day):
    pad_l, pad_r, pad_t, pad_b = 62, 18, 16, 34
    pts = [(i, c, v, w) for i, (_, c, v, w) in enumerate(track) if w]
    if not pts:
        return "<p class='empty-state'>no usable minutes</p>"
    lo = min(min(c, v - w) for _, c, v, w in pts)
    hi = max(max(c, v + w) for _, c, v, w in pts)
    span = (hi - lo) or 1
    n = len(track)

    def X(i):
        return pad_l + (W - pad_l - pad_r) * i / max(n - 1, 1)

    def Y(p):
        return pad_t + (H - pad_t - pad_b) * (1 - (p - lo) / span)

    upper = " ".join(f"{X(i):.1f},{Y(v + w):.1f}" for i, _, v, w in pts)
    lower = " ".join(f"{X(i):.1f},{Y(v - w):.1f}" for i, _, v, w in reversed(pts))
    vwap_d = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, _, v, _ in pts)
    price_d = " ".join(f"{X(i):.1f},{Y(c):.1f}" for i, c, _, _ in pts)

    # y gridlines
    grid = []
    for k in range(5):
        p = lo + span * k / 4
        y = Y(p)
        grid.append(f"<line class='grid' x1='{pad_l}' y1='{y:.1f}' x2='{W-pad_r}' y2='{y:.1f}'/>"
                    f"<text class='ax' x='{pad_l-8}' y='{y+4:.1f}' text-anchor='end'>${p:,.2f}</text>")
    # x labels every 30 min
    for i, (hhmm, *_ ) in enumerate(track):
        if hhmm.endswith(":00") or hhmm.endswith(":30"):
            grid.append(f"<text class='ax' x='{X(i):.1f}' y='{H-12}' text-anchor='middle'>{hhmm}</text>")

    return f"""<svg viewBox="0 0 {W} {H}" role="img" aria-label="SPY, VWAP and the one-wiggle band on {esc(day)}">
  {''.join(grid)}
  <polygon class="band" points="{upper} {lower}"/>
  <polyline class="vwap" points="{vwap_d}"/>
  <polyline class="price" points="{price_d}"/>
</svg>"""


# ----------------------------------------------------------------- panel 2
def panel_wiggle_by_minute(days):
    per_minute = defaultdict(list)
    for track in days.values():
        for hhmm, _, _, w in track:
            if w:
                per_minute[hhmm].append(w)
    mins = sorted(per_minute)
    if not mins:
        return "", []
    med = [statistics.median(per_minute[m]) for m in mins]
    pad_l, pad_r, pad_t, pad_b = 62, 18, 16, 34
    hi = max(med) * 1.15
    n = len(mins)

    def X(i):
        return pad_l + (W - pad_l - pad_r) * i / max(n - 1, 1)

    def Y(v):
        return pad_t + (H - pad_t - pad_b) * (1 - v / hi)

    # sqrt(time since open) reference, scaled to match at noon
    def minutes_since_open(hhmm):
        h, m = int(hhmm[:2]), int(hhmm[3:])
        return max((h * 60 + m) - (9 * 60 + 30), 1)

    anchor_i = min(range(n), key=lambda i: abs(minutes_since_open(mins[i]) - 150))
    k = med[anchor_i] / math.sqrt(minutes_since_open(mins[anchor_i]))
    ref = " ".join(f"{X(i):.1f},{Y(k*math.sqrt(minutes_since_open(m))):.1f}"
                   for i, m in enumerate(mins))
    line = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(med))

    grid = []
    for j in range(5):
        v = hi * j / 4
        y = Y(v)
        grid.append(f"<line class='grid' x1='{pad_l}' y1='{y:.1f}' x2='{W-pad_r}' y2='{y:.1f}'/>"
                    f"<text class='ax' x='{pad_l-8}' y='{y+4:.1f}' text-anchor='end'>${v:.2f}</text>")
    for i, m in enumerate(mins):
        if m.endswith(":00"):
            grid.append(f"<text class='ax' x='{X(i):.1f}' y='{H-12}' text-anchor='middle'>{m}</text>")

    callouts = []
    for target in ("10:00", "10:30", "12:00", "15:00"):
        if target in per_minute:
            i = mins.index(target)
            callouts.append((target, med[i]))

    svg = f"""<svg viewBox="0 0 {W} {H}" role="img" aria-label="Median wiggle by time of day">
  {''.join(grid)}
  <polyline class="ref" points="{ref}"/>
  <polyline class="price" points="{line}"/>
</svg>"""
    return svg, callouts


# ----------------------------------------------------------------- panel 3
def panel_reversion(days):
    """Forward 30m move, folded so + = kept going away, - = came back."""
    per_bucket = defaultdict(lambda: defaultdict(list))
    for day, track in days.items():
        by_min = {hhmm: (c, v, w) for hhmm, c, v, w in track}
        keys = [k for k in sorted(by_min) if ENTRY_START <= k <= ENTRY_END]
        idx = {k: i for i, k in enumerate(sorted(by_min))}
        order = sorted(by_min)
        for k in keys:
            c, v, w = by_min[k]
            if not w:
                continue
            j = idx[k] + HORIZON
            if j >= len(order):
                continue
            fwd = by_min[order[j]][0]
            stretch = (c - v) / w
            if stretch == 0:
                continue
            # fold: positive = moved further from the line
            bp = ((fwd - c) / c) * 10_000 * (1 if stretch > 0 else -1)
            a = abs(stretch)
            for edge, name, label in BUCKETS:
                if a < edge:
                    per_bucket[label][day].append(bp)
                    break

    rows = []
    for edge, name, label in BUCKETS:
        by_day = per_bucket.get(label, {})
        day_means = [statistics.fmean(v) for v in by_day.values() if v]
        n_min = sum(len(v) for v in by_day.values())
        m, lo, hi = mean_ci(day_means)
        rows.append((label, name, n_min, len(day_means), m, lo, hi))

    finite = [r for r in rows if r[4] is not None]
    if not finite:
        return "", rows
    lim = max(max(abs(r[5] or r[4]), abs(r[6] or r[4])) for r in finite) * 1.2 or 1
    ph, pad_l, pad_r = 260, 120, 18
    band = (ph - 40) / len(rows)

    def X(bp):
        return pad_l + (W - pad_l - pad_r) * (bp + lim) / (2 * lim)

    parts = [f"<line class='zero' x1='{X(0):.1f}' y1='16' x2='{X(0):.1f}' y2='{ph-24}'/>"]
    for i, (label, name, n_min, n_days, m, lo, hi) in enumerate(rows):
        y = 28 + band * i + band / 2
        parts.append(f"<text class='ax rowlab' x='{pad_l-12}' y='{y+4:.1f}' text-anchor='end'>"
                     f"{esc(name)} ({esc(label)})</text>")
        if m is None:
            continue
        cls = "loss" if m < 0 else "profit"
        if lo is not None:
            parts.append(f"<line class='ci {cls}' x1='{X(lo):.1f}' y1='{y:.1f}' x2='{X(hi):.1f}' y2='{y:.1f}'/>")
            for e in (lo, hi):
                parts.append(f"<line class='cap {cls}' x1='{X(e):.1f}' y1='{y-5:.1f}' x2='{X(e):.1f}' y2='{y+5:.1f}'/>")
        parts.append(f"<circle class='dot {cls}' cx='{X(m):.1f}' cy='{y:.1f}' r='5'/>")
        parts.append(f"<text class='ax val' x='{W-pad_r}' y='{y+4:.1f}' text-anchor='end'>"
                     f"{m:+.2f} bp · {n_min:,} min</text>")
    parts.append(f"<text class='ax' x='{X(-lim*0.55):.1f}' y='{ph-6}' text-anchor='middle'>"
                 f"&#8592; came back toward VWAP</text>")
    parts.append(f"<text class='ax' x='{X(lim*0.55):.1f}' y='{ph-6}' text-anchor='middle'>"
                 f"kept going away &#8594;</text>")
    return (f"<svg viewBox='0 0 {W} {ph}' role='img' "
            f"aria-label='Forward 30 minute move by stretch bucket'>{''.join(parts)}</svg>"), rows


CSS = """
:root{
  --surface:#fff; --surface-alt:#f6f7f9; --surface-sunken:#eef0f3;
  --text:#14171a; --text-muted:#5b646e; --text-faint:#8a939d;
  --border:#dfe3e8; --primary:#3355ff;
  --color-profit:#06894c; --color-loss:#d92d20;
  --band:rgba(51,85,255,.10); --ref:#8a939d;
  --sp-2:8px; --sp-3:12px; --sp-4:16px; --sp-6:24px; --sp-8:32px;
  --radius-md:8px; --fs-micro:11px; --fs-sm:13px;
  --font-sans:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  --font-mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
}
@media (prefers-color-scheme:dark){ :root:not([data-theme="light"]){
  --surface:#15181c; --surface-alt:#0f1215; --surface-sunken:#1b1f24;
  --text:#e8eaed; --text-muted:#9aa3ad; --text-faint:#6b747e;
  --border:#2a2f36; --primary:#7f95ff;
  --color-profit:#3ddc97; --color-loss:#ff6b5e;
  --band:rgba(127,149,255,.14); --ref:#6b747e;
}}
:root[data-theme="dark"]{
  --surface:#15181c; --surface-alt:#0f1215; --surface-sunken:#1b1f24;
  --text:#e8eaed; --text-muted:#9aa3ad; --text-faint:#6b747e;
  --border:#2a2f36; --primary:#7f95ff;
  --color-profit:#3ddc97; --color-loss:#ff6b5e;
  --band:rgba(127,149,255,.14); --ref:#6b747e;
}
*{box-sizing:border-box}
body{margin:0;background:var(--surface-alt);color:var(--text);
  font-family:var(--font-sans);font-variant-numeric:tabular-nums;
  line-height:1.5;padding:var(--sp-6) var(--sp-4)}
.wrap{max-width:1180px;margin:0 auto}
h1{font-size:22px;margin:0 0 var(--sp-2);letter-spacing:-.02em}
.sub{color:var(--text-muted);font-size:var(--fs-sm);margin:0 0 var(--sp-6)}
.panel{background:var(--surface);border:1px solid var(--border);
  border-radius:var(--radius-md);padding:var(--sp-4);margin-bottom:var(--sp-6)}
h2{font-size:15px;margin:0 0 4px}
.note{color:var(--text-muted);font-size:var(--fs-sm);margin:0 0 var(--sp-4);max-width:76ch}
svg{width:100%;height:auto;display:block}
.grid{stroke:var(--border);stroke-width:1}
.zero{stroke:var(--text-faint);stroke-width:1;stroke-dasharray:3 3}
.ax{fill:var(--text-muted);font-size:var(--fs-micro);font-family:var(--font-mono)}
.rowlab{fill:var(--text)}
.val{fill:var(--text-muted)}
.band{fill:var(--band);stroke:none}
.vwap{fill:none;stroke:var(--primary);stroke-width:1.6;stroke-dasharray:5 4}
.price{fill:none;stroke:var(--text);stroke-width:1.6}
.ref{fill:none;stroke:var(--ref);stroke-width:1.4;stroke-dasharray:4 4}
.ci{stroke-width:2}.cap{stroke-width:2}
.profit{stroke:var(--color-profit)}circle.profit{fill:var(--color-profit);stroke:none}
.loss{stroke:var(--color-loss)}circle.loss{fill:var(--color-loss);stroke:none}
.key{display:flex;gap:var(--sp-6);flex-wrap:wrap;font-size:var(--fs-micro);
  color:var(--text-muted);margin-top:var(--sp-3)}
.key i{display:inline-block;width:18px;height:0;vertical-align:middle;margin-right:6px}
.chips{display:flex;gap:var(--sp-2);flex-wrap:wrap;margin-bottom:var(--sp-4)}
.chip{font-family:var(--font-mono);font-size:var(--fs-micro);
  background:var(--surface-sunken);border:1px solid var(--border);
  border-radius:999px;padding:3px 10px;color:var(--text-muted)}
footer{color:var(--text-faint);font-size:var(--fs-micro);margin-top:var(--sp-8)}
@media(max-width:640px){body{padding:var(--sp-4) var(--sp-3)}h1{font-size:19px}}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="SPY")
    ap.add_argument("--day", default=None, help="session for panel 1 (default: latest)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--open", action="store_true", help="open in the browser when done")
    args = ap.parse_args()

    raw = load(args.symbol)
    days = {d: session_track(bars) for d, bars in sorted(raw.items())}
    days = {d: t for d, t in days.items() if t}
    if not days:
        sys.exit("no usable sessions")
    day = args.day or max(days)
    if day not in days:
        sys.exit(f"{day} not in file ({min(days)} .. {max(days)})")

    p1 = panel_session(days[day], day)
    p2, callouts = panel_wiggle_by_minute(days)
    p3, rows = panel_reversion(days)

    chips = "".join(
        f"<span class='chip'>{esc(t)} ET &nbsp;${v:,.2f}</span>" for t, v in callouts)
    out = args.out or os.path.join(REPO, "data", "backtest", "vwap_stretch.html")
    os.makedirs(os.path.dirname(out), exist_ok=True)

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VWAP Stretch</title><style>{CSS}</style></head>
<body><div class="wrap">
<h1>How far is too far from VWAP?</h1>
<p class="sub">{esc(args.symbol)} &middot; {len(days)} sessions
  {esc(min(days))} &ndash; {esc(max(days))} &middot; minute bars &middot;
  TODO.md G4b</p>

<div class="panel">
  <h2>1 &middot; One session: {esc(day)}</h2>
  <p class="note">The shaded band is one <strong>wiggle</strong> either side of VWAP &mdash;
  how far {esc(args.symbol)} had typically sat from the line by that point in the day.
  It starts narrow and fans out. That is the whole reason distance is measured in
  wiggles and not in cents: the same 50&cent; is a long way at 10:00 ET and nothing
  at 15:00 ET. The rule declines to enter when price is outside this band.</p>
  {p1}
  <div class="key">
    <span><i style="border-top:2px solid var(--text)"></i>price</span>
    <span><i style="border-top:2px dashed var(--primary)"></i>VWAP</span>
    <span><i style="border-top:10px solid var(--band)"></i>&plusmn;1 wiggle</span>
  </div>
</div>

<div class="panel">
  <h2>2 &middot; The band through the day</h2>
  <p class="note">Median wiggle at each minute across all {len(days)} sessions (solid),
  against a square-root-of-time-since-the-open curve (dashed). They track closely
  through the morning, which is why one fixed threshold in wiggles behaves
  consistently all day where a fixed dollar amount cannot.</p>
  <div class="chips">{chips}</div>
  {p2}
</div>

<div class="panel">
  <h2>3 &middot; Does price come back?</h2>
  <p class="note">Forward 30-minute move, grouped by how stretched price was, folded
  so the sign means one thing: <strong>left = came back toward VWAP</strong>,
  right = kept going. Bars are 95% intervals treating each day as one observation,
  because overlapping minutes are not independent. Minutes {ENTRY_START}&ndash;{ENTRY_END} ET.</p>
  {p3}
</div>

<footer>Built by scripts/chart_vwap_stretch.py from
data/backtest/underlying/{esc(args.symbol)}_1min.json. VWAP and the wiggle are
rebuilt from minute bars; the live engine accumulates tick by tick and its
in-memory tally restarts with the process, so the two disagree on sessions where
the engine restarted mid-day. Evidence is {len(days)} sessions &mdash; small.</footer>
</div></body></html>"""

    with open(out, "w") as fh:
        fh.write(html)
    print(f"wrote {os.path.relpath(out, REPO)}  ({len(html):,} bytes, {len(days)} sessions)")
    for label, name, n_min, n_days, m, lo, hi in rows:
        ci = f"({lo:+.2f} .. {hi:+.2f})" if lo is not None else ""
        print(f"  {name:<14}{label:>7}  {n_min:>6,} min  {n_days:>3}d  "
              f"{m:+.2f} bp {ci}" if m is not None else f"  {name:<14}{label:>7}  no data")
    if args.open:
        subprocess.run(["xdg-open", out], check=False)


if __name__ == "__main__":
    main()
