#!/usr/bin/env python3
"""Chart: static vs dynamic exits on the 2026-09-16 tape.

    ./venv/bin/python scripts/chart_dynamic_exits.py
    -> data/backtest/dynamic_exits.html   (open in a browser)

Companion to docs/dynamic-exits-math.md. Three panels, all from recorded data:

  1. The real 10:07 ET put trade: its recorded bid, and where three trailing-stop
     rules would have sold it (static 10% of peak, keep 70% of the gain, and a
     volatility trail).
  2. SPY through the day with two envelopes: how far a flat 15% option stop
     reaches (fixed width) versus a typical 30-minute move (widens and narrows).
  3. The chance random noise alone hits the stop, through the day: flat 15%
     versus a 1-sigma dynamic stop.

The volatility estimate in panels 2-3 is CAUSAL (trailing 30 minutes only), i.e.
what a live engine could have known at that minute. The math note's morning /
afternoon sigmas were after-the-fact windows, so values differ slightly.

Read-only.
"""
import json
import math
import os
import statistics
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import replay_session as rs  # noqa: E402

REPO = rs.REPO
STREAM = os.path.join(REPO, "logs", "livetest-2026-09-16", "stream-20260916-070615.jsonl")
OUT = os.path.join(REPO, "data", "backtest", "dynamic_exits.html")

PUT = "SPY260916P00760000"
ENTRY, DELTA = 2.52, 0.64
ARM = 1.15                        # trail arms at +15%
STATIC_GIVEBACK = 0.10
KEEP = 0.70
CHAND_K, SIGMA10_AM = 0.5, 0.45   # doc §5 figures, morning window
STOP_PCT = 0.15
SPY_STOP = STOP_PCT * ENTRY / DELTA   # $0.59: the put's 15% stop, in SPY dollars


def secs(hms):
    h, m, s = (hms.split(":") + ["0"])[:3]
    return int(h) * 3600 + int(m) * 60 + int(s)


def touch(k):
    return min(1.0, 2 * (1 - 0.5 * (1 + math.erf(k / math.sqrt(2))))) if k > 0 else 1.0


def panel_trade(quotes):
    pts = []
    for ts, bid, ask in quotes[PUT]:
        et = (ts + rs.ET_OFFSET).strftime("%H:%M:%S")
        if "10:07:01" <= et <= "10:37:51" and bid > 0:
            pts.append((secs(et), bid))
    peak, armed = 0.0, False
    rules = {"static": STATIC_GIVEBACK, "keep": KEEP, "chand": CHAND_K}
    lines = {k: [] for k in rules}
    exited = {}
    for x, bid in pts:
        peak = max(peak, bid)
        armed = armed or peak >= ENTRY * ARM - 1e-9
        levels = {
            "static": peak * (1 - STATIC_GIVEBACK),
            "keep": ENTRY + KEEP * (peak - ENTRY),
            "chand": peak - CHAND_K * DELTA * SIGMA10_AM,
        }
        for k, lvl in levels.items():
            if armed and k not in exited:
                lines[k].append(round(lvl, 4))
                if bid <= lvl:
                    exited[k] = (x, bid)
            else:
                lines[k].append(None)
    return dict(
        x=[p[0] for p in pts], bid=[p[1] for p in pts], lines=lines,
        exits={k: dict(x=v[0], y=v[1], pnl=round((v[1] - ENTRY) * 100)) for k, v in exited.items()},
        refs=dict(entry=ENTRY, static_stop=round(ENTRY * (1 - STOP_PCT), 3),
                  dynamic_stop=round(ENTRY - DELTA * 0.64, 3)),
        low=min(pts[: [p[0] for p in pts].index(secs("10:27:46"))], key=lambda p: p[1]))


def panel_structure():
    """Panels 4-5: the structure stop, on real trades (scripts/dynamic_exits_review.py)."""
    import dynamic_exits_review as dr
    trips = dr.load_trips()
    quotes, spy = dr.load_tape({t["sym"] for t in trips})

    rows, both, live_sum, struct_sum = [], 0, 0.0, 0.0
    for t in trips:
        et0 = t["entry_utc"] + rs.ET_OFFSET
        day = et0.date().isoformat()
        ticks = quotes.get(t["sym"], [])
        lv = dr.walk(ticks, t, "live", spy.get(day, {}))
        st = dr.walk(ticks, t, "struct", spy.get(day, {}))
        pnl = lambda r: round((r[0] - t["entry"]) * 100 * t["qty"]) if r else None
        lp, sp = pnl(lv), pnl(st)
        if lp is not None and sp is not None:
            both += 1
            live_sum += lp
            struct_sum += sp
        if lp != sp:
            rows.append(dict(day=day[5:], entry=et0.strftime("%H:%M"), sym=t["sym"], real=round(t["pnl_real"]),
                             live=lp, struct=sp,
                             live_why=lv[2] if lv else None, struct_why=st[2] if st else None))

    # The walkthrough trade: 09-04 11:07 put, the one the rule changed most.
    t = next(x for x in trips if x["sym"] == "SPY260904P00774000"
             and (x["entry_utc"] + rs.ET_OFFSET).strftime("%H:%M") == "11:07")
    day = "2026-09-04"
    trace = []
    st = dr.walk_struct(quotes[t["sym"]], t, spy[day], dr.SPY_OHLC[day], trace=trace)
    lv = dr.walk(quotes[t["sym"]], t, "live", spy[day])
    ohlc = dr.SPY_OHLC[day]
    mins = [m for m in sorted(ohlc) if "11:00" <= m <= "12:10"]
    swings = [e for e in trace if e["kind"] == "swing"]
    fire = next((e for e in trace if e["kind"] == "fire"), None)
    stop_line = []
    for m in mins:
        active = [e for e in swings if e["confirmed"] <= m]
        stop_line.append(round(active[-1]["stop"], 3) if active and m <= fire["minute"] else None)
    opt = [(secs((ts + rs.ET_OFFSET).strftime("%H:%M:%S")), bid) for ts, bid, ask in quotes[t["sym"]]
           if t["entry_utc"] < ts and (ts + rs.ET_OFFSET).strftime("%H:%M:%S") <= "12:05:30" and bid > 0]
    return dict(
        rows=rows, both=both, live_sum=round(live_sum), struct_sum=round(struct_sum),
        walk=dict(
            x=[secs(m) for m in mins], close=[ohlc[m][3] for m in mins], stop=stop_line,
            swings=[dict(x=secs(e["minute"]), y=e["pivot"], confirmed=e["confirmed"]) for e in swings],
            fire=dict(x=secs(fire["minute"]), y=fire["close"], stop=round(fire["stop"], 2)),
            entry=t["entry"], entry_x=secs((t["entry_utc"] + rs.ET_OFFSET).strftime("%H:%M:%S")),
            opt_x=[o[0] for o in opt], opt=[o[1] for o in opt],
            struct_exit=dict(x=secs(st[1].strftime("%H:%M:%S")), y=st[0],
                             pnl=round((st[0] - t["entry"]) * 100)),
            live_exit=dict(x=secs(lv[1].strftime("%H:%M:%S")), y=lv[0],
                           pnl=round((lv[0] - t["entry"]) * 100)),
        ))


def panel_day(bars):
    day = max(bars, key=lambda d: len(bars[d]))
    b = bars[day]
    hh = [h for h in sorted(b) if "09:30" <= h < "16:00"]
    closes = [b[h][1] for h in hh]
    rows = []
    for i, h in enumerate(hh):
        if not ("10:00" <= h < "15:46"):
            continue
        diffs = [closes[j] - closes[j - 1] for j in range(max(1, i - 29), i + 1)]
        sd30 = statistics.pstdev(diffs) * math.sqrt(30) if len(diffs) >= 20 else None
        if not sd30:
            continue
        k = SPY_STOP / sd30
        rows.append(dict(x=secs(h), spy=closes[i], sd30=round(sd30, 3), k=round(k, 3),
                         p_static=round(touch(k), 4), p_dyn=round(touch(1.0), 4)))
    return rows


CSS = """
.viz-root{color-scheme:light;--surface-1:#fcfcfb;--page:#f9f9f7;--text-primary:#0b0b0b;
--text-secondary:#52514e;--muted:#898781;--grid:#e1e0d9;--axis:#c3c2b7;
--border:rgba(11,11,11,.10);--static:#eb6834;--keep:#2a78d6;--vol:#1baf7a;--price:#52514e}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])) .viz-root{color-scheme:dark;
--surface-1:#1a1a19;--page:#0d0d0d;--text-primary:#fff;--text-secondary:#c3c2b7;--muted:#898781;
--grid:#2c2c2a;--axis:#383835;--border:rgba(255,255,255,.10);--static:#d95926;--keep:#3987e5;--vol:#199e70;--price:#c3c2b7}}
:root[data-theme="dark"] .viz-root{color-scheme:dark;--surface-1:#1a1a19;--page:#0d0d0d;--text-primary:#fff;
--text-secondary:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--axis:#383835;--border:rgba(255,255,255,.10);
--static:#d95926;--keep:#3987e5;--vol:#199e70;--price:#c3c2b7}
body{margin:0;background:var(--page)}
.viz-root{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;color:var(--text-primary);
background:var(--page);padding:24px 16px 48px;max-width:1040px;margin:0 auto}
h1{font-size:22px;margin:0 0 4px} .sub{color:var(--text-secondary);margin:0 0 24px;font-size:14px;line-height:1.5}
.card{background:var(--surface-1);border:1px solid var(--border);border-radius:12px;padding:16px 16px 12px;margin:0 0 20px}
.card h2{font-size:16px;margin:0 0 4px} .card p{margin:0 0 10px;color:var(--text-secondary);font-size:13px;line-height:1.5}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:12px;color:var(--text-secondary);margin:4px 0 8px}
.legend span{display:inline-flex;align-items:center;gap:6px}
.sw{width:14px;height:3px;border-radius:2px;display:inline-block}
.sw.band{height:10px;opacity:.28}
.chart{position:relative;width:100%} svg{display:block;width:100%;height:auto;overflow:visible}
.tick{fill:var(--muted);font-size:11px;font-variant-numeric:tabular-nums}
.lbl{font-size:11px;fill:var(--text-secondary)}
.tip{position:absolute;pointer-events:none;background:var(--surface-1);border:1px solid var(--border);
border-radius:8px;padding:8px 10px;font-size:12px;box-shadow:0 4px 16px rgba(0,0,0,.18);white-space:nowrap;
display:none;z-index:2}
.tip .t{color:var(--muted);margin-bottom:4px;font-variant-numeric:tabular-nums}
.tip .r{display:flex;gap:8px;align-items:center;line-height:1.6}
.tip .r b{font-variant-numeric:tabular-nums;min-width:56px;text-align:right}
.tip .r i{width:10px;height:3px;border-radius:2px;display:inline-block}
details{margin-top:8px;font-size:12px;color:var(--text-secondary)} summary{cursor:pointer}
.tw{overflow-x:auto} table{border-collapse:collapse;margin-top:6px;font-variant-numeric:tabular-nums}
th,td{padding:3px 10px;text-align:right;border-bottom:1px solid var(--border)} th:first-child,td:first-child{text-align:left}
.note{font-size:12px;color:var(--muted);margin-top:24px;line-height:1.5}
"""

JS = r"""
const D = JSON.parse(document.getElementById('data').textContent);
const css = n => getComputedStyle(document.querySelector('.viz-root')).getPropertyValue(n).trim();
const hms = s => { const h=Math.floor(s/3600), m=Math.floor(s%3600/60), x=s%60;
  return String(h).padStart(2,'0')+':'+String(m).padStart(2,'0')+(x?':'+String(x).padStart(2,'0'):''); };
const NS = 'http://www.w3.org/2000/svg';
if (location.hash==='#light'||location.hash==='#dark') document.documentElement.setAttribute('data-theme', location.hash.slice(1));
function nice(lo, hi, n){ const raw=(hi-lo)/n, mag=Math.pow(10,Math.floor(Math.log10(raw)));
  const step=[1,2,2.5,5,10].map(f=>f*mag).find(v=>v>=raw); const a=Math.floor(lo/step)*step, b=Math.ceil(hi/step)*step;
  const t=[]; for(let v=a; v<=b+step/2; v+=step) t.push(+v.toFixed(6)); return {y0:a,y1:b,ticks:t}; }
function el(tag, attrs, parent){ const e=document.createElementNS(NS,tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]); if(parent) parent.appendChild(e); return e; }
function nearest(xs, x){ let lo=0, hi=xs.length-1;
  while(hi-lo>1){ const m=(lo+hi)>>1; if(xs[m]<x) lo=m; else hi=m; }
  return (x-xs[lo] <= xs[hi]-x) ? lo : hi; }

function chart(root, cfg){
  const W=1000, H=cfg.h||340, M={l:52,r:120,t:12,b:28};
  root.innerHTML=''; const svg=el('svg',{viewBox:`0 0 ${W} ${H}`,role:'img','aria-label':cfg.aria},root);
  const tip=document.createElement('div'); tip.className='tip'; root.appendChild(tip);
  const xs=cfg.x, x0=xs[0], x1=xs[xs.length-1];
  const X=v=>M.l+(v-x0)/(x1-x0)*(W-M.l-M.r), Y=v=>M.t+(cfg.y1-v)/(cfg.y1-cfg.y0)*(H-M.t-M.b);
  const N=nice(cfg.y0,cfg.y1,cfg.yTicks); cfg.y0=N.y0; cfg.y1=N.y1;
  for(const v of N.ticks){
    el('line',{x1:M.l,x2:W-M.r,y1:Y(v),y2:Y(v),stroke:css('--grid'),'stroke-width':1},svg);
    el('text',{x:M.l-8,y:Y(v)+4,'text-anchor':'end',class:'tick'},svg).textContent=cfg.yfmt(v); }
  el('line',{x1:M.l,x2:W-M.r,y1:H-M.b,y2:H-M.b,stroke:css('--axis'),'stroke-width':1},svg);
  for(const t of cfg.xTicks){ el('text',{x:X(t),y:H-M.b+18,'text-anchor':'middle',class:'tick'},svg).textContent=hms(t); }
  for(const b of (cfg.bands||[])){ let d='';
    xs.forEach((v,i)=>{ if(b.hi[i]==null) return; d+=(d?'L':'M')+X(v)+','+Y(b.hi[i]); });
    for(let i=xs.length-1;i>=0;i--){ if(b.lo[i]==null) continue; d+='L'+X(xs[i])+','+Y(b.lo[i]); }
    el('path',{d:d+'Z',fill:css(b.color),'fill-opacity':b.op||0.18,stroke:'none'},svg); }
  for(const r of (cfg.refs||[])){
    el('line',{x1:M.l,x2:W-M.r,y1:Y(r.y),y2:Y(r.y),stroke:css(r.color||'--muted'),'stroke-width':1.5,'stroke-dasharray':'5 4'},svg);
    el('text',{x:W-M.r+6,y:Y(r.y)+(r.dy==null?4:r.dy),class:'lbl'},svg).textContent=r.label; }
  for(const s of cfg.series){ let d='';
    s.v.forEach((v,i)=>{ if(v==null){ return; } const p=X(xs[i])+','+Y(v);
      d += (i>0 && s.v[i-1]!=null) ? 'L'+p : 'M'+p; });
    el('path',{d,fill:'none',stroke:css(s.color),'stroke-width':s.w||2,'stroke-linejoin':'round','stroke-linecap':'round'},svg);
    if(s.label){ let li=s.v.length-1; while(li>0 && s.v[li]==null) li--;
      el('text',{x:Math.min(X(xs[li])+6,W-M.r+6),y:Y(s.v[li])+(s.dy||4),class:'lbl'},svg).textContent=s.label; } }
  for(const m of (cfg.markers||[])){
    el('circle',{cx:X(m.x),cy:Y(m.y),r:6,fill:css(m.color),stroke:css('--surface-1'),'stroke-width':2},svg);
    if(m.lx!=null){ el('line',{x1:X(m.x),y1:Y(m.y),x2:X(m.lx),y2:Y(m.ly)-4,stroke:css(m.color),'stroke-width':1},svg);
      el('text',{x:X(m.lx),y:Y(m.ly)+10,class:'lbl','text-anchor':'middle'},svg).textContent=m.label; }
    else el('text',{x:X(m.x)+(m.dx||8),y:Y(m.y)+(m.dy||-10),class:'lbl','text-anchor':m.anchor||'start'},svg).textContent=m.label; }
  const vline=el('line',{y1:M.t,y2:H-M.b,stroke:css('--axis'),'stroke-width':1,visibility:'hidden'},svg);
  const hit=el('rect',{x:M.l,y:M.t,width:W-M.l-M.r,height:H-M.t-M.b,fill:'transparent'},svg);
  function move(ev){ const box=svg.getBoundingClientRect(), sx=(ev.clientX-box.left)*W/box.width;
    const i=nearest(xs, x0+(sx-M.l)/(W-M.l-M.r)*(x1-x0)); const cx=X(xs[i]);
    vline.setAttribute('x1',cx); vline.setAttribute('x2',cx); vline.setAttribute('visibility','visible');
    tip.textContent=''; const t=document.createElement('div'); t.className='t'; t.textContent=hms(xs[i])+' ET'; tip.appendChild(t);
    for(const row of cfg.tip(i)){ if(row.v==null) continue; const r=document.createElement('div'); r.className='r';
      const sw=document.createElement('i'); sw.style.background=css(row.color||'--muted'); r.appendChild(sw);
      const b=document.createElement('b'); b.textContent=row.v; r.appendChild(b);
      const s=document.createElement('span'); s.textContent=row.name; r.appendChild(s); tip.appendChild(r); }
    tip.style.display='block'; const px=cx*box.width/W;
    tip.style.left=(px+tip.offsetWidth+16>box.width ? px-tip.offsetWidth-12 : px+12)+'px'; tip.style.top='8px'; }
  hit.addEventListener('pointermove',move);
  hit.addEventListener('pointerleave',()=>{ tip.style.display='none'; vline.setAttribute('visibility','hidden'); });
}

function render(){
  const T=D.trade, money=v=>'$'+v.toFixed(2);
  chart(document.getElementById('c1'),{ aria:'Put bid with three trailing stop rules', x:T.x, y0:2.0, y1:3.0, yTicks:5,
    yfmt:money, xTicks:[secs('10:10'),secs('10:15'),secs('10:20'),secs('10:25'),secs('10:30'),secs('10:35')],
    refs:[{y:T.refs.entry,label:'entry $2.52'},{y:T.refs.static_stop,label:'15% stop $2.14',color:'--static',dy:-2},
          {y:T.refs.dynamic_stop,label:'1σ stop $2.11',color:'--vol',dy:12}],
    series:[{v:T.bid,color:'--price',w:1.5,label:''},
            {v:T.lines.static,color:'--static',w:2.5},
            {v:T.lines.keep,color:'--keep',w:2.5},
            {v:T.lines.chand,color:'--vol',w:2.5}],
    markers:[mk('static','--static','give back 10% sells +$',secs('10:36'),2.38),
             mk('keep','--keep','keep 70% sells +$',secs('10:24'),2.30),
             mk('chand','--vol','vol trail sells +$',secs('10:31'),2.24)],
    tip:i=>[{name:'option bid',v:money(T.bid[i]),color:'--price'},
            {name:'give back 10% of peak',v:T.lines.static[i]!=null?money(T.lines.static[i]):null,color:'--static'},
            {name:'keep 70% of gain',v:T.lines.keep[i]!=null?money(T.lines.keep[i]):null,color:'--keep'},
            {name:'volatility trail',v:T.lines.chand[i]!=null?money(T.lines.chand[i]):null,color:'--vol'}] });
  function mk(k,color,txt,lx,ly){ const e=T.exits[k]; return {x:e.x,y:e.y,color,label:txt+e.pnl,lx,ly}; }

  const R=D.day, x=R.map(r=>r.x), spy=R.map(r=>r.spy);
  const lo=Math.min(...R.map(r=>r.spy-r.sd30)), hi=Math.max(...R.map(r=>r.spy+r.sd30));
  const dayTicks=[secs('10:00'),secs('11:00'),secs('12:00'),secs('13:00'),secs('14:00'),secs('15:00')];
  chart(document.getElementById('c2'),{ aria:'SPY with static and dynamic stop envelopes', x, y0:Math.floor(lo), y1:Math.ceil(hi), yTicks:6,
    yfmt:v=>'$'+v.toFixed(0), xTicks:dayTicks,
    bands:[{lo:R.map(r=>r.spy-r.sd30),hi:R.map(r=>r.spy+r.sd30),color:'--vol',op:0.20},
           {lo:R.map(r=>r.spy-D.spyStop),hi:R.map(r=>r.spy+D.spyStop),color:'--static',op:0.35}],
    series:[{v:spy,color:'--price',w:1.5,label:'SPY'}],
    tip:i=>[{name:'SPY',v:money(spy[i]),color:'--price'},
            {name:'15% stop reaches (SPY $)',v:'±'+money(D.spyStop),color:'--static'},
            {name:'typical 30-min move',v:'±'+money(R[i].sd30),color:'--vol'}] });

  chart(document.getElementById('c3'),{ aria:'Chance noise triggers the stop through the day', x, y0:0, y1:1, yTicks:4, h:260,
    yfmt:v=>Math.round(v*100)+'%', xTicks:dayTicks,
    series:[{v:R.map(r=>r.p_static),color:'--static',label:'flat 15%'},
            {v:R.map(r=>r.p_dyn),color:'--vol',label:'dynamic 1σ',dy:-6}],
    tip:i=>[{name:'flat 15% stop',v:Math.round(R[i].p_static*100)+'%',color:'--static'},
            {name:'dynamic 1σ stop',v:Math.round(R[i].p_dyn*100)+'%',color:'--vol'},
            {name:'flat stop is (σ away)',v:R[i].k.toFixed(2)}] });

  const W4=D.struct.walk;
  chart(document.getElementById('c4'),{ aria:'SPY with swing high and structure stop', x:W4.x,
    y0:Math.min(...W4.close)-0.3, y1:Math.max(...W4.close,W4.fire.stop)+0.4, yTicks:5,
    yfmt:v=>'$'+v.toFixed(2), xTicks:[secs('11:00'),secs('11:15'),secs('11:30'),secs('11:45'),secs('12:00')],
    series:[{v:W4.close,color:'--price',w:1.5,label:'SPY'},
            {v:W4.stop,color:'--keep',w:2.5}],
    markers:[...W4.swings.map(s=>({x:s.x,y:s.y,color:'--keep',label:'swing high (confirmed '+s.confirmed+')',lx:s.x+60,ly:s.y-0.55})),
             {x:W4.fire.x,y:W4.fire.y,color:'--static',label:'11:14 bar closes above the stop → sell',lx:W4.fire.x+1500,ly:W4.fire.y+0.25}],
    tip:i=>[{name:'SPY 1-min close',v:money(W4.close[i]),color:'--price'},
            {name:'structure stop',v:W4.stop[i]!=null?money(W4.stop[i]):null,color:'--keep'}] });

  chart(document.getElementById('c5'),{ aria:'Option bid with structure exit and 15% stop exit', x:W4.opt_x,
    y0:3.6, y1:5.0, yTicks:5, yfmt:money, xTicks:[secs('11:15'),secs('11:30'),secs('11:45'),secs('12:00')],
    refs:[{y:W4.entry,label:'entry $'+W4.entry.toFixed(2)},{y:W4.entry*0.85,label:'15% stop',color:'--static'}],
    series:[{v:W4.opt,color:'--price',w:1.5}],
    markers:[{x:W4.struct_exit.x,y:W4.struct_exit.y,color:'--keep',label:'structure stop sells $'+W4.struct_exit.y.toFixed(2)+' ('+W4.struct_exit.pnl+')',lx:W4.struct_exit.x+700,ly:3.72},
             {x:W4.live_exit.x,y:W4.live_exit.y,color:'--static',label:'15% stop sells $'+W4.live_exit.y.toFixed(2)+' ('+W4.live_exit.pnl+')',lx:W4.live_exit.x-900,ly:3.70}],
    tip:i=>[{name:'option bid',v:money(W4.opt[i]),color:'--price'}] });
}
function secs(s){ const [h,m]=s.split(':').map(Number); return h*3600+m*60; }
render();
addEventListener('resize',()=>{ clearTimeout(window.__r); window.__r=setTimeout(render,120); });
matchMedia('(prefers-color-scheme: dark)').addEventListener('change',render);
"""


def table(headers, rows):
    h = "".join("<th>%s</th>" % x for x in headers)
    b = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % c for c in r) for r in rows)
    return '<div class="tw"><table><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>' % (h, b)


def hms(s):
    return "%02d:%02d:%02d" % (s // 3600, s % 3600 // 60, s % 60)


def main():
    quotes = rs.load_quotes(STREAM)
    trade = panel_trade(quotes)
    day = panel_day(rs.spy_bars(STREAM))
    struct = panel_structure()
    fmt = lambda v: "?" if v is None else "%+d" % v
    t3 = table(["Day", "Entry", "Contract", "Real", "Live rule", "Structure stop", "Difference"],
               [[r["day"], r["entry"], r["sym"], "%+d" % r["real"],
                 "%s (%s)" % (fmt(r["live"]), r["live_why"] or "unresolved"),
                 "%s (%s)" % (fmt(r["struct"]), r["struct_why"] or "unresolved"),
                 fmt(r["struct"] - r["live"]) if r["live"] is not None and r["struct"] is not None else "—"]
                for r in struct["rows"]])
    W = struct["walk"]

    names = {"static": "Give back 10% of peak (live today)", "keep": "Keep 70% of the gain",
             "chand": "Volatility trail (peak − 0.5σ)"}
    t1 = table(["Rule", "Sold at", "Time (ET)", "Result"],
               [[names[k], "$%.2f" % e["y"], hms(e["x"]), "%+d" % e["pnl"]] for k, e in
                sorted(trade["exits"].items(), key=lambda kv: kv[1]["x"])])
    t2 = table(["ET", "SPY", "typical 30-min move", "flat 15% stop is", "noise hits flat", "noise hits 1σ"],
               [[hms(r["x"])[:5], "$%.2f" % r["spy"], "±$%.2f" % r["sd30"], "%.2fσ" % r["k"],
                 "%d%%" % round(r["p_static"] * 100), "%d%%" % round(r["p_dyn"] * 100)]
                for r in day if hms(r["x"]).endswith(("00:00", "15:00", "30:00", "45:00"))])

    am = next(r for r in day if hms(r["x"]).startswith("10:30"))
    pm = next(r for r in day if hms(r["x"]).startswith("14:30"))
    low = trade["low"]
    ex = trade["exits"]

    html = """<title>Dynamic Exits — 2026-09-16</title>
<style>%(css)s</style>
<div class="viz-root">
<h1>Static vs dynamic exits, on real trades</h1>
<p class="sub">2026-09-16, recorded tape. All times ET. Study chart for
<code>docs/dynamic-exits-math.md</code> — nothing in the engine was changed. Hover any chart for values.</p>

<div class="card">
<h2>1 · The 10:07 put: where each trailing stop would have sold it</h2>
<p>Bought at $2.52. It dipped to $%(low_y).2f at %(low_t)s — nowhere near either stop — then peaked at $2.91 (+15.5%%),
which armed the trail. The flat rule gave back almost everything: <b>+$%(p_static)d</b>. Keeping 70%% of the gain sold
at <b>+$%(p_keep)d</b>; the volatility trail at <b>+$%(p_chand)d</b>. The price line ends at the real exit because the
contract stopped being recorded once the position closed.</p>
<div class="legend"><span><i class="sw" style="background:var(--price)"></i>option bid</span>
<span><i class="sw" style="background:var(--static)"></i>give back 10%% of peak (static)</span>
<span><i class="sw" style="background:var(--keep)"></i>keep 70%% of the gain (dynamic)</span>
<span><i class="sw" style="background:var(--vol)"></i>volatility trail (dynamic)</span></div>
<div class="chart" id="c1"></div>
<details><summary>Table view</summary>%(t1)s</details>
</div>

<div class="card">
<h2>2 · Same stop, different day: a fixed 15%% versus how much SPY actually moves</h2>
<p>The orange band is how far the put's 15%% stop reaches, as SPY dollars — always ±$%(spy_stop).2f. The green band is a
typical 30-minute SPY move, measured from the trailing 30 minutes only (what a live engine would know). In the calm
morning they're about the same size. When SPY sold off after 14:45, a normal move grew several times wider than the
stop — so the flat stop was sitting inside ordinary noise.</p>
<div class="legend"><span><i class="sw" style="background:var(--price)"></i>SPY</span>
<span><i class="sw band" style="background:var(--static)"></i>reach of a flat 15%% stop (static)</span>
<span><i class="sw band" style="background:var(--vol)"></i>typical 30-minute move (dynamic)</span></div>
<div class="chart" id="c2"></div>
</div>

<div class="card">
<h2>3 · Chance random noise alone triggers the stop</h2>
<p>At 10:30 the flat stop sat %(am_k).2fσ away: <b>%(am_p)d%%</b> chance noise hits it. At 14:30 it sat %(pm_k).2fσ away:
<b>%(pm_p)d%%</b>. A dynamic 1σ stop holds <b>%(dyn_p)d%%</b> all day, because it widens and narrows with the market.
The catch is the dollar cost: in the afternoon that stop is far wider, so position size would have to shrink.</p>
<div class="legend"><span><i class="sw" style="background:var(--static)"></i>flat 15%% stop (static)</span>
<span><i class="sw" style="background:var(--vol)"></i>dynamic 1σ stop</span></div>
<div class="chart" id="c3"></div>
<details><summary>Table view (every 15 minutes)</summary>%(t2)s</details>
</div>

<div class="card">
<h2>4 · Structure stop, step by step: the 09-04 11:07 put</h2>
<p>Your idea, in its workable form. The stop follows SPY's <i>swing</i> points instead of a fixed %%: a 1-minute bar
whose high is above the 2 bars on each side is a swing high (for a put, SPY going UP is the danger, so highs matter;
for a call it is the mirror, swing lows). Once the 2 later bars close, the stop is placed a quarter of a typical
10-minute move beyond it, and it only ever moves in your favour. It fires when a 1-minute bar <b>closes</b> beyond it.
Here the swing formed at 11:08, the 11:14 bar closed 5¢ above the stop, and the option sold at the next tick.</p>
<div class="legend"><span><i class="sw" style="background:var(--price)"></i>SPY 1-minute close</span>
<span><i class="sw" style="background:var(--keep)"></i>structure stop (active once confirmed)</span></div>
<div class="chart" id="c4"></div>
</div>

<div class="card">
<h2>5 · The same trade, on the option — and all 28 real trades</h2>
<p>The structure stop sold at <b>$%(s_exit).2f</b> (%(s_pnl)+d) at 11:15. The live rule held on until 12:05 and hit the
15%% stop at <b>$%(l_exit).2f</b> (%(l_pnl)+d).</p>
<div class="legend"><span><i class="sw" style="background:var(--price)"></i>option bid</span>
<span><i class="sw" style="background:var(--keep)"></i>structure stop exit</span>
<span><i class="sw" style="background:var(--static)"></i>15%% stop exit (live rule)</span></div>
<div class="chart" id="c5"></div>
<p style="margin-top:12px">Across all 28 real round trips, on the %(both)d both rules could measure: live rule
<b>%(live_sum)+d</b>, structure stop <b>%(struct_sum)+d</b>. It changed only the trades below — every other trade came out
identical, including every winner it could measure. The rules were fixed before the test was run; the margin rests
on very few trades, and the 11:14 trigger cleared the stop by only 5¢.</p>
%(t3)s
</div>

<p class="note">Assumptions: delta held at 0.64 (it actually drifts, so dollar conversions are approximate); noise-hit
chance uses a driftless random walk, 2 × (1 − Φ(k)); the volatility trail uses the morning 10-minute σ of $0.45 from the
math note. The steps in panel 3 are big one-minute moves entering and leaving the 30-minute window. One day and one trade — a tighter trail can also sell a winner that would have kept running. Exits are a
live-engine change: test across every session before touching settings.</p>
<script type="application/json" id="data">%(data)s</script>
<script>%(js)s</script>
</div>
""" % dict(css=CSS, js=JS, t1=t1, t2=t2,
           data=json.dumps(dict(trade=trade, day=day, spyStop=round(SPY_STOP, 4), struct=struct)),
           s_exit=W["struct_exit"]["y"], s_pnl=W["struct_exit"]["pnl"], l_exit=W["live_exit"]["y"],
           l_pnl=W["live_exit"]["pnl"], both=struct["both"], live_sum=struct["live_sum"],
           struct_sum=struct["struct_sum"], t3=t3,
           low_y=low[1], low_t=hms(low[0]),
           p_static=ex["static"]["pnl"], p_keep=ex["keep"]["pnl"], p_chand=ex["chand"]["pnl"],
           spy_stop=SPY_STOP, am_k=am["k"], am_p=round(am["p_static"] * 100),
           pm_k=pm["k"], pm_p=round(pm["p_static"] * 100), dyn_p=round(am["p_dyn"] * 100))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        fh.write(html)
    print("wrote", os.path.relpath(OUT, REPO))
    print("exits:", {k: (hms(v["x"]), v["y"], v["pnl"]) for k, v in ex.items()})
    print("10:30 k=%.2f P=%.0f%% | 14:30 k=%.2f P=%.0f%% | sigma30 range %.2f-%.2f" % (
        am["k"], am["p_static"] * 100, pm["k"], pm["p_static"] * 100,
        min(r["sd30"] for r in day), max(r["sd30"] for r in day)))


if __name__ == "__main__":
    main()
