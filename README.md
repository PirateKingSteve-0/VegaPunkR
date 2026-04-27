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
python api/app.py
```

API available at:
- http://localhost:8000
- Swagger docs: http://localhost:8000/docs

### 6. Run the Frontend

```bash
cd ui
npm install
npm start
```

UI available at http://localhost:4200

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