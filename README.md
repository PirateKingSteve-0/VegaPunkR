# VegaPunkR

A trading bot platform with a Python FastAPI backend and Angular frontend.

## Tech Stack

- **Backend:** Python 3.13+, FastAPI, SQLAlchemy, Alembic
- **Frontend:** Angular 20, TypeScript
- **Database:** PostgreSQL/TimescaleDB
- **Brokers:** Alpaca, Schwab, Tradier

## Local Setup

### Prerequisites

- Python 3.13+
- Node.js / npm
- Docker

### 1. Start the Databases

```bash
docker compose -f docker/docker-compose.yml up -d
```

This starts three TimescaleDB instances:
| Environment | Port |
|-------------|------|
| Development | 5435 |
| Test        | 5433 |
| Production  | 5434 |

### 2. Set Up Python Environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Copy `.env.example` to `.env` and fill in your API credentials:
- Alpaca API keys
- Schwab OAuth credentials (optional)
- Tradier API keys (optional)

### 4. Initialize the Database

```bash
cd api
python setup_db.py init
```

### 5. Run the Backend

```bash
venv/bin/python api/app.py   # defaults to the dev database (--env dev)
```

API available at:
- http://localhost:8000
- Swagger docs: http://localhost:8000/docs

> See [Starting the App](#starting-the-app-daily) below for the dev-vs-prod
> distinction — which database the process talks to is fixed at launch by
> `--env` (or `APP_ENV`), so it matters which command you use.

### 6. Run the Frontend

```bash
cd ui
npm install
npm start
```

UI available at http://localhost:4200

## Starting the App (Daily)

**Full reference: [`docs/starting-the-app.md`](docs/starting-the-app.md)**: every launch flag,
dev/test/prod, LAN access to the UI, two backends side by side, and the read-only tools that run
beside them.

```bash
# Backend: pick ONE
venv/bin/python api/app.py --env prod --log --no-reload   # LIVE day: prod DB, dated logs, code frozen
venv/bin/python api/app.py                                # development: dev DB (the default)
venv/bin/python api/app.py --env test                     # test DB (local Docker, :5433)

# Frontend (second terminal)
cd ui && npm start                                        # → http://localhost:4200
```

dev and prod live on AWS RDS, so no Docker is needed. Only the test database is local:
`docker compose -f docker/docker-compose.yml up -d timescaledb_test`.

### Choosing dev vs prod — `APP_ENV`

**`--env` (or the `APP_ENV` variable) selects the database for the entire
process, and it is fixed at launch. You cannot switch it at runtime.** Valid
values are `dev` (default), `test`, and `prod`. For `APP_ENV`, anything
unrecognized falls back to `dev`. A flag beats `APP_ENV`, which beats the
default, so `APP_ENV=prod python api/app.py` still works.

On startup the backend logs which database it pinned to — always eyeball this
line to confirm you launched what you meant to:

```
🗄️  Process DB environment: APP_ENV=dev → dev
```

> ⚠️ **Why this matters for live trading.** The UI's per-user
> Environment / Trading-Mode switch only changes the **broker client**, *not*
> the database. If the process is running on `dev` but you flip a user to
> "live" in the UI, real broker orders get recorded against the **dev**
> database (split-brain). For an actual live run, launch a **dedicated**
> process with `--env prod` so the API, engine worker, and broker all agree.
> See `docs/starting-the-app.md`.

### Related environment variables

| Variable            | Values                          | Effect                                              |
|---------------------|---------------------------------|-----------------------------------------------------|
| `APP_ENV`           | `dev` (default), `test`, `prod` | Which database the whole process uses               |
| `TRADIER_ENV`       | `sandbox` (default), `live`     | Which Tradier broker keys / base URL are used       |
| `LIVE_TEST_LOGGING` | `1` to enable                   | Writes date-stamped engine logs to file (off by default); same as `--log` |

## Project Structure

```
VegaPunkR/
├── api/                 # FastAPI backend
│   ├── app.py          # Main entry point
│   ├── routers/        # API endpoints
│   ├── services/       # Business logic
│   └── models.py       # Database models
├── ui/                  # Angular frontend
├── docker/              # Docker configuration
└── docs/                # Documentation
```