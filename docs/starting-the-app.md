# Starting the App

The single reference for every way to start the two apps: the **backend** (`api/app.py`: API +
trading engine + market stream) and the **UI** (Angular, `ui/`). Plus the read-only tools that run
beside them. Written 2026-09-20; supersedes the cheat-sheet in `docs/monday-runbook.md` (July) and the
env-var form in `README.md`.

---

## TL;DR — a live trading day

```bash
# terminal 1 — backend, real money, code frozen
venv/bin/python api/app.py --env prod --log --no-reload

# terminal 2 — UI
cd ui && npm start                  # → http://localhost:4200
```

Before 10:00 ET (06:30 PT, when entries open), check the banner the backend prints says
`DB environment : prod   <-- REAL MONEY DB`.

---

## 1. Backend — `api/app.py`

Run from the repo root (`venv/bin/python api/app.py …`) or from `api/` (`../venv/bin/python app.py …`).
Both work.

### Flags

| Flag | Values | Default | Effect |
|---|---|---|---|
| `--env` | `dev`, `test`, `prod` | `$APP_ENV`, else `dev` | Which database the **whole process** uses: API, engine worker, streams. Fixed at launch. |
| `--log` | — | off (`$LIVE_TEST_LOGGING`) | Writes dated engine + JSONL logs to `logs/livetest-<ET-date>/` |
| `--no-reload` | — | reload **on** | Turns off the auto-reloader. With reload on, saving any `.py` under `api/` hot-swaps engine code, **including under an open position**. |
| `--port` | int | `8000` | Listen port. **The UI only talks to `:8000`**. See §3. |

`python api/app.py --help` prints the same.

**Which setting wins:** a flag beats the environment variable, which beats the default `dev`. So the
older form `APP_ENV=prod LIVE_TEST_LOGGING=1 python api/app.py` still works and is identical to
`--env prod --log`. Prefer the flags: they show up in shell history and `ps`, and a forgotten env var
doesn't.

Before the server starts, the app prints what it resolved to:

```
  DB environment : prod   <-- REAL MONEY DB
  File logging   : on
  Auto-reload    : off
  Port           : 8000
```

and at startup it logs (into the engine log file too, when `--log` is on):

```
🗄️  Process DB environment: APP_ENV=prod → prod
```

### The commands

| Purpose | Command |
|---|---|
| **Live trading day** (recommended) | `venv/bin/python api/app.py --env prod --log --no-reload` |
| Live, but still editing code (reloads on save) | `venv/bin/python api/app.py --env prod --log` |
| Development | `venv/bin/python api/app.py` *(= `--env dev`)* |
| Development with log files | `venv/bin/python api/app.py --log` |
| Test database | `venv/bin/python api/app.py --env test` |
| Old env-var form (still works) | `APP_ENV=prod LIVE_TEST_LOGGING=1 venv/bin/python api/app.py` |

Stop with **Ctrl+C**. On a live day, stopping the backend stops **every** exit. The stop loss,
trailing stop, take profit and the 15:45 ET forced exit all run inside this process, and nothing
waits at the broker (TODO H4). Don't stop it with a position open unless you mean to manage that
position by hand.

### ⚠️ `dev` is not a safe sandbox

The database choice (`--env`) and the broker choice are **separate**. The broker account (live or
paper) comes from each user's Environment / Trading-Mode setting in the UI, stored on the user row.
**DEV user 1 is set to live trading** (JOURNAL 2026-09-05). So a plain `python api/app.py` during
market hours runs active DEV strategies against the **real** account, recorded in the dev database.
For real trading, always launch with `--env prod`. For a dry run, set the user to paper/sandbox
first.

### Where the databases are

| `--env` | Database | Where |
|---|---|---|
| `dev` | vegapunk dev | AWS RDS (us-west-1), shared by laptop and PC |
| `prod` | vegapunk prod | AWS RDS (us-west-1), shared by laptop and PC |
| `test` | vegapunk_test | **local Docker**, `localhost:5433` (in memory, wiped on stop) |

URLs come from `DATABASE_DEV_URL` / `DATABASE_TEST_URL` / `DATABASE_PROD_URL` in the root `.env`.
dev and prod don't need Docker. Only `--env test` needs the local container (the test suite uses in-memory SQLite and doesn't):

```bash
docker compose -f docker/docker-compose.yml up -d timescaledb_test
```

Because dev and prod are shared between machines, **run one backend per database at a time**
across laptop *and* PC. Two engines on the same database would both trade the same strategies.

API: <http://localhost:8000>, Swagger docs: <http://localhost:8000/docs>. It listens on `0.0.0.0`,
so other devices on the LAN can reach it too.

---

## 2. UI — `ui/`

| Purpose | Command |
|---|---|
| **Normal** (dev server, live reload) | `cd ui && npm start` *(= `ng serve`, development config)* |
| Dev server with the production build config | `cd ui && npx ng serve --configuration production` |
| One-off build to `ui/dist/` | `cd ui && npm run build` |
| Rebuild on save, no server | `cd ui && npm run watch` |
| First time / after a dependency change | `cd ui && npm install` |

Node comes from nvm (default v22).

**Opening it from another device.** The dev server listens on `0.0.0.0:4200` and accepts the hosts
listed in `ui/angular.json` → `serve.options.allowedHosts`: `localhost`, `127.0.0.1`,
`Lulusia.local`, `192.168.1.7`. From a phone or the other machine, open
`http://Lulusia.local:4200` or `http://192.168.1.7:4200`. A new hostname has to be added to that
list first, or the dev server refuses it.

The UI finds the API by taking **the host the page was served from + `:8000`**
(`ui/src/environments/environment.ts`). One build works from every device, and the API must be on
port 8000 on that same machine.

The UI's Environment toggle changes which database the UI **reads**. It does **not** change what the
engine trades against. That is fixed by the backend's `--env` at launch.

---

## 3. Two backends at once (dev + prod side by side)

`--port` makes this possible for the **API**:

```bash
venv/bin/python api/app.py --env prod --log --no-reload            # :8000 (UI talks to this one)
venv/bin/python api/app.py --env dev  --port 8001                  # :8001 (Swagger / curl only)
```

Caveats:
- The UI is hardwired to `:8000`, so only the backend on 8000 is reachable from the UI. Reach the
  other one through <http://localhost:8001/docs> or curl. (TODO: "Configurable server port").
- **Each backend runs its own engine worker, Tradier streams and email scheduler.** A dev backend
  with active strategies and a live-mode user will trade too (see the ⚠️ above). Deactivate DEV
  strategies or switch the DEV user to paper before running the two together.

---

## 4. Beside the backend (read-only, optional)

None of these place or cancel orders.

| Tool | Command | What it does |
|---|---|---|
| Morning check | `venv/bin/python scripts/morning_check.py --env PROD` (`--no-broker` to skip broker calls) | Duplicate open rows, DB-vs-broker position mismatches, strategy direction vs what it actually holds. Run before the open. |
| Live-test monitor | `cd api && ../venv/bin/python -m live_test.monitor --env prod --interval 60` | Compares broker and DB every 60 s and flags anomalies. Always writes `reconcile-*.jsonl`. `--once` for a single pass. |

Logs from `--log` land in `logs/livetest-<ET-date>/`: `engine-*.log` (human-readable),
`orders-*.jsonl` (fills), `broker_http-*.jsonl` (raw broker calls), `stream-*.jsonl` (ticks), and
`reconcile-*.jsonl` (monitor).

---

## Tests

```bash
scripts/run_tests.sh          # offline tests only (in-memory SQLite) — the commit gate
scripts/run_tests.sh -q       # same, failures + summary only
scripts/run_tests.sh --all    # also test_api (needs the backend on :8000) and test_database (RDS)
```
