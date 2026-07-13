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
python api/app.py            # defaults to the dev database (APP_ENV=dev)
```

API available at:
- http://localhost:8000
- Swagger docs: http://localhost:8000/docs

> See [Starting the App](#starting-the-app-daily) below for the dev-vs-prod
> distinction — which database the process talks to is fixed at launch by
> `APP_ENV`, so it matters which command you use.

### 6. Run the Frontend

```bash
cd ui
npm install
npm start
```

UI available at http://localhost:4200

## Starting the App (Daily)

Once the initial setup above is done, this is the day-to-day startup. You need
three things running: the databases, the backend, and the frontend.

```bash
# 1. Databases (once per machine boot — leave them running)
docker compose -f docker/docker-compose.yml up -d

# 2. Activate the Python environment
source venv/bin/activate

# 3. Backend — pick ONE, depending on which environment you want
python api/app.py                  # DEV   → vegapunk_dev DB  (port 5435)  [default]
APP_ENV=prod python api/app.py     # PROD  → vegapunk_prod DB (port 5434)  [live]
APP_ENV=test python api/app.py     # TEST  → vegapunk_test DB (port 5433)

# 4. Frontend (in a second terminal)
cd ui && npm start                 # → http://localhost:4200
```

### Choosing dev vs prod — `APP_ENV`

**`APP_ENV` selects the database for the entire process, and it is fixed at
launch — you cannot switch it at runtime.** Valid values are `dev` (default),
`test`, and `prod`; anything unrecognized falls back to `dev`.

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
> process with `APP_ENV=prod` so the API, engine worker, and broker all agree.
> See `docs/live-test-plan-2026-07-13.md`.

### Related environment variables

| Variable            | Values                          | Effect                                              |
|---------------------|---------------------------------|-----------------------------------------------------|
| `APP_ENV`           | `dev` (default), `test`, `prod` | Which database the whole process uses               |
| `TRADIER_ENV`       | `sandbox` (default), `live`     | Which Tradier broker keys / base URL are used       |
| `LIVE_TEST_LOGGING` | `1` to enable                   | Writes date-stamped engine logs to file (off by default) |

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