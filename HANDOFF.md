# HANDOFF

Where the last chat stopped, so any new chat, machine or window can pick up. **Read the newest entry
first.** Detail lives in `JOURNAL.md` (findings), `TODO.md` (work), `BRAINSTORM.md` (decisions); this
file only points at them.

**Rules:** newest entry on top · keep the last 5, delete older (JOURNAL has the history) · ~10 lines
each · written when the owner says **"checkpoint"** · times in ET · never paste findings here, link
them. "Settled" lists conclusions already reached, so the next chat does not re-run them.

```
## <YYYY-MM-DD Day HH:MM ET> · <machine> · <branch>
State:   <clean/dirty, pushed?, engine running?>
Open:    - <question asked, not answered> (rec: <recommended option>)
Settled: - <conclusion reached — don't redo>
Next:    <the one thing to start with>
```

---

## 2026-09-29 Tue 02:57 ET · Lulusia (laptop) · dev
State:   DIRTY, not committed (owner: "not yet"). App RUNNING since Mon 22:49 PT as `python app.py --env prod --log`,
         **without --no-reload**: every .py save restarts the live engine. Last reload 02:45 ET, running the final
         reviewed code. No open positions. Log folder now livetest-2026-09-29/ (rollover fix working).
Open:    - Restart with `--no-reload` before 09:30 ET? (rec: yes; until then, nobody saves a .py under api/)
         - Commit + push: sizing (account_state + order/risk/executor + test + design doc), logging fix + gate_review,
           docs (TODO/STRATEGIES/startup guide/JOURNAL/HANDOFF). (rec: 3 commits, after Tuesday looks sane)
Settled: - Sizing mode B built: size on start-of-day equity, cap buys at cash left; 4 engine-guard passes, last
           "safe to run live"; 56 checks + suite green. Design: docs/sizing-basis-design-2026-09-29.md. Mode A = future setting.
         - Don't trade paper and live the same ET day (no mode column on trades; TODO D6).
         - Weekend research all noise, incl. ORB re-test (STRATEGIES X1–X8); see JOURNAL 09-25..29.
Next:    Tuesday's first live run of mode B: check `Account state refreshed … cash left ~$1,550` in the engine log,
         watch for `Entry size capped` / `Insufficient cash left`. If anything's off, stop and set the files aside.

## 2026-09-27 Sun 11:54 ET · Lulusia (laptop) · dev
State:   clean, pushed at b0173e6. Engine not running. `data/trade_replays/` rebuilt through 09-25 (gitignored).
Open:    - Write the 09-26/27 analyses (below) into JOURNAL + TODO? Not yet written anywhere but this chat. (rec: yes)
         - Pending TODO items, none written yet: same-day-only expiry rule; record-only TSLA via
           `max_position_size_usd: 1`; zero-value traps (`max_positions: 0` → 1 or 3, `max_contracts: 0` → 1,
           `max_position_size_usd: 0` → no cap); candle-shape features as a G4 candidate; account daily cap showed
           two values ($73.76 vs $77.53); IWM chain returned only 0/1 deltas after ~11:00 ET 09-25; engine
           log and stream land in the wrong day folder when started the evening before; architecture diagram update.
Settled: - Weekday: Fri −$177 / 12 trades is chance (38% by shuffle); Fridays are not choppier (median efficiency 0.10).
         - Exits: breakeven stop is noise (flips between split halves); exit shadow best rule +$52 / 20 trades, noise.
           Correction: the earlier "~−7R recoverable" claim was wrong.
         - SPY calls: raising delta and don't-chase both point the wrong way on 12 trades. On the tape, call and
           put signals are both coin flips (31 sessions, 10:00–11:30 ET).
         - Don't-chase on Fridays would not help: it blocks −$15 and allows −$162. All days: blocked +$412 vs allowed +$21.
         - Order flow (8 sessions): confirmation / absorption / air pocket predict nothing. Re-run at ~20 sessions.
           Measure push against the day's running average, because buyers out-trade sellers every day.
         - Bottom line: the sample is the bottleneck (E11), not a missing filter.
Next:    JOURNAL write-up of the above, then the pending TODO list. Scratch scripts to save into `scripts/`
         are in the session scratchpad (flow_build, flow_test, be, tape); they need re-creating from this chat
         if it is gone.
