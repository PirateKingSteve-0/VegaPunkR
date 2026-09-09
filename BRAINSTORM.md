# BRAINSTORM

Open questions, options weighed, and decisions that shaped a design — the reasoning that would
otherwise be lost between sessions.

`TODO.md` is what we intend to build. This is why it looks the way it does. Keep entries short;
once something becomes work, it moves to `TODO.md` and this keeps only the decision.

---

## Storing the broker-confirm PDFs — S3, or nothing? *(2026-09-07)*

**Decision: store no PDF bytes.** Related: TODO.md I2.

Cost was never the issue. Confirms are ~350 KB, one per trading day — 90 MB/yr, about **$0.03/yr**
on S3 Standard in us-west-1, ~$0.26/yr after a decade. It never becomes a line item, and we already
run RDS in that region so S3 is not a new vendor.

S3 *is* the standard pattern for documents (blob in object storage, metadata row in the DB; never
large binaries in Postgres). The reasons not to here:

- **PII surface.** Confirms carry name, home address and account number. A bucket means a policy,
  public-access blocks, encryption config and an IAM credential that all have to stay right forever.
- **Second copy of something that already has a custodian.** Apex and Tradier retain these; the
  portal is the archive. We would be duplicating a re-downloadable file.
- **We do not serve documents back.** S3-for-PDFs is standard when the job is "let the user retrieve
  their files". Here the PDF is an input to a parse, not an asset.

**Open — the one real counter-argument: re-parseability.** Without the bytes, a parser fix means
re-uploading. Cheaper answer than a bucket: keep the extracted *text* (~4.9 KB per confirm, ~1.6 KB
gzipped, **~0.4 MB/yr** in Postgres) as a `source_text` column on `BrokerDocument`. Full re-parse
capability, no object storage, and stripping the cover page drops the name and address before
anything is written. Not yet adopted.

---

## Economic-event awareness — not a news feed, and not a day flag *(2026-09-07)*

**Decision: an economic-event calendar with per-release timestamps. Report-only. Morning summary at
09:00 ET *and* per-event logging through the session.** Supersedes the news-outlook sketch in TODO.md.

### Why a calendar, not a news feed

Two unrelated things get called "news":

- **Scheduled events** — CPI, PPI, NFP, FOMC. Published months ahead by the Fed and BLS.
- **Story news** — narrative headlines with sentiment, from a paid vendor.

SPY is ~500 names, so one company's story is diluted to nothing and partly offset by another's. The
book is structurally immune to single-name news and structurally fully exposed to macro. *(Caveat:
index concentration has eroded this — the top 10 are ~35–40% of SPY and NVDA earnings is now an
index-level event, not a single-stock one.)*

Magnitudes are the opposite of intuition: a stock moves 5–10% on its own earnings, SPY ~1% on CPI.
Single-name news is far bigger **per stock**; macro is far bigger **per portfolio**, because it hits
every position in the same direction in the same second and deletes diversification exactly when it
was needed. For a single-underlying SPY book only the second one exists.

**A news vendor's real job is the UNSCHEDULED event** — an FDA decision, a surprise merger, an 11:40
guidance cut. Scheduled events come free from a calendar. For SPY that unscheduled category is
essentially empty, which is why the vendor half kept evaluating as weak: not bad vendors, just
nothing for them to catch here. Deferred, not rejected — it becomes real the day the book holds
single names.

### TradingView is not a source

Every TradingView "API" is one where **TradingView is the client and we are the server**: the
Charting Library's Datafeed API and the Broker Integration API are interfaces *we* implement for
*them* to call; widgets are display-only iframes. The one outbound path is Pine Script alerts →
webhook, which carries our own chart condition, not headlines.

This is a **licensing wall, not a technical gap.** They license news from Reuters / Dow Jones /
Benzinga under contracts permitting display to a logged-in TradingView user, not redistribution. A
public news API would be reselling Dow Jones's product. Same for exchange data. Scraping is the part
of that wall that gets an account banned. "TradingView has good news" means "TradingView pays for
good news" — and for the *calendar* specifically, the upstream source is free and public, so there is
nobody to pay.

### Windows, not days — and which windows actually reach us

The naive design flags a whole day. Nobody serious does that: the market does not have a bad *day*
because of CPI, it has a violent *five minutes*. The unit is a window around the release timestamp.

That matters because releases land at different times, and this book enters after
`entry_after_open_minutes` and is flat by 15:45:

| Release | Lands | Do we hold through it? |
|---|---|---|
| FOMC decision 14:00 + presser 14:30 | mid-session | **Yes — dead centre** |
| ISM / consumer sentiment / JOLTS 10:00 | mid-morning | **Yes** |
| CPI / PPI / NFP 08:30 | pre-open | **No — resolves before entry** |

So danger to *this* book ranks **FOMC 14:00 > 10:00 releases >> CPI 08:30** — the reverse of the
intuition that made 08:30 the design's anchor. CPI is the famous one, but we are never in a position
when it prints; we enter *after* the IV crush, not into it. The Fed is the one we hold long premium
straight through, which is the classic way to be right on direction and still lose.

### What v1 records

**Both halves, one event list:**

- **09:00 ET morning summary** — what is scheduled today, on the `email_report_scheduler.py`
  two-stage anchor (03:00 cron reads Tradier `markets/calendar`, then a one-shot at
  `open.start − 30min`). Holidays fall out for free; a flat `CronTrigger(hour=9)` would fire on them.
- **Per-event logging through the session** — every release stamped with its exact time.

**Store timestamps, not dates.** A row saying *"today had CPI"* can never test a window size. A row
saying *"CPI released 2026-09-11 08:30:00 ET"* lets us go back through fills and ask whether trades
opened within 15 / 30 / 60 minutes of a release did worse, and let the data choose the window. We
already capture MFE/MAE per trade, so the test can measure how hard those trades went against us
before resolving, not just whether they lost.

The verdict is **per-day, not per-strategy** — a CPI print is true for every strategy at once. The
per-strategy column sketched in TODO reads the day's row rather than computing its own.

**Why record before acting:** this question cannot be answered retroactively. Trades ≤ id 2905 are
untrustworthy under CP-1 and the 174 post-cutoff churn trades drag everything until filtered; clean
history starts after the 2026-08-25 fixes, so roughly one CPI and one FOMC exist to look at. That is
an anecdote. The value of v1 is **starting the clock.** Same data-first pattern as B2 (entry-drift)
and A1 (GFV reservations).

### Calendar source — a checked-in file, not a vendor

FOMC dates publish a year ahead; BLS publishes an annual release schedule. ~20 entries, seeded once a
year in a repo YAML with exact release times. Cannot rate-limit, cannot be down at 08:59, reviewable
in a diff, free. A vendor econ-calendar API (Finnhub, FMP, Trading Economics) adds a key and a
network dependency to fetch data that changes annually.

**What a vendor would genuinely add is consensus forecasts.** The date is free; the *expectation* is
not — and price reacts to `actual − consensus`, not to the event. An in-line CPI is a non-event; a
two-tenths miss is a 1% move on the identical calendar entry. Report-only needs dates only, so v1
pays nothing. Consensus becomes worth buying the day we want to *predict* rather than *observe*.
*Open:* whether to cross-check the annual seed against a free vendor, or trust the release schedules.

### Deferred, and what it would inherit

`avoid_economic_news: True` is set in all eight templates (`strategy_templates.py:99,148,198,247,297,
346,395,444`) and **nothing in the tree reads it** — the engine advertises this behavior and does not
have it. The calendar is what that param was waiting for, but wiring it up is a gate, so it belongs
to the deferred phase.

If a blackout window ever ships it is a new entry gate and inherits the engine rules: compose
most-restrictive-wins with the bounds at `signal_generator.py:289` (`entry_after_open_minutes` ∧
`user.trading_window_start` ∧ forced-exit time), never widen any of them, and let `side='sell'`
through so a blackout cannot trap an open position.

### Already in the tree

- `services/email_report_scheduler.py` — the two-stage anchor to copy.
- `engine/signal_generator.py:60` `resolve_direction()` — **closes TODO's "strategy-direction mapping
  is the real design problem"**; direction is already a validated `params_json` field with one
  resolver, no `bias` column needed. Moot for a per-day verdict, but it unblocks the story-news half
  if that is ever built.
- `stream_driven_worker.py:304` — `strategy.instruments[0]`, one underlying per strategy.
