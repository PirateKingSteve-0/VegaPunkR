# VegaPunkR Database Setup Complete ✓

## What's Been Created

### 1. Database Models ([models.py](models.py))
- **User** - User accounts with trading preferences
- **Strategy** - Trading strategies with parameters
- **Position** - Open positions tracking
- **Trade** - Complete trade history (optimized for TimescaleDB)
- **PerformanceMetrics** - Strategy performance analytics
- **RiskEvent** - Risk management event logging

### 2. Database Instance
- **Container**: `vegapunk_db` (TimescaleDB on PostgreSQL 16)
- **Status**: Running ✓
- **Connection**: `postgresql://user:pass@localhost:5432/vegapunk`
- **Tables Created**: All 6 tables with proper relationships and indexes

### 3. Migration System (Alembic)
- **Location**: [alembic/](alembic/)
- **Current Revision**: `f3c0b907af67` (Initial schema)
- **Config**: Reads from `.env` file automatically

### 4. Management Tools

#### User Management ([manage_users.py](manage_users.py))
```bash
# Create user
python3 manage_users.py create --email EMAIL --name NAME --password PASS [OPTIONS]

# List users
python3 manage_users.py list

# Update user
python3 manage_users.py update --email EMAIL [OPTIONS]

# Delete user
python3 manage_users.py delete --email EMAIL
```

#### Database Setup ([setup_db.py](setup_db.py))
```bash
python3 setup_db.py init      # Create all tables
python3 setup_db.py migrate   # Run Alembic migrations
python3 setup_db.py reset     # Drop and recreate (⚠️ deletes data)
```

### 5. Admin User Created ✓
- **Email**: kingofpirates92@gmail.com
- **Username**: pirateking
- **Role**: admin
- **Account Size**: $5,000
- **Risk Tolerance**: medium
- **Max Trade %**: 2%
- **Timezone**: America/Los_Angeles

## Quick Start

### Daily Usage

```bash
# Start database
cd docker && docker compose up -d

# Stop database
cd docker && docker compose down

# View logs
docker logs vegapunk_db
```

### Making Schema Changes

```bash
# 1. Edit models.py
# 2. Generate migration
cd api
alembic revision --autogenerate -m "Description of changes"

# 3. Review migration file in alembic/versions/
# 4. Apply migration
alembic upgrade head
```

### Using the Models in Your Code

```python
from models import User, Strategy, Position, Trade
from database import SessionLocal, get_db

# Create session
db = SessionLocal()

# Query users
user = db.query(User).filter(User.email == "kingofpirates92@gmail.com").first()

# Create a strategy
strategy = Strategy(
    user_id=user.id,
    name="My Strategy",
    params_json={"ma_short": 50, "ma_long": 200},
    instruments=["AAPL", "TSLA"]
)
db.add(strategy)
db.commit()

# Query positions
positions = db.query(Position).filter(Position.user_id == user.id).all()

# Don't forget to close
db.close()

# Or use context manager (recommended)
with SessionLocal() as db:
    user = db.query(User).first()
    # ... do work ...
    # automatically closed
```

### FastAPI Integration Example

```python
from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from database import get_db
from models import User, Strategy

app = FastAPI()

@app.get("/users/{user_id}")
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    return user

@app.get("/strategies")
def list_strategies(db: Session = Depends(get_db)):
    strategies = db.query(Strategy).filter(Strategy.is_active == True).all()
    return strategies
```

## Files Created

```
api/
├── models.py              # SQLAlchemy models
├── database.py            # Database connection & session
├── setup_db.py           # Database setup utility
├── manage_users.py       # User management CLI
├── DATABASE.md           # Detailed database guide
├── SETUP_COMPLETE.md     # This file
├── alembic/              # Migration system
│   ├── env.py            # Configured for your project
│   └── versions/         # Migration files
└── alembic.ini           # Alembic config

docker/
└── docker-compose.yml    # TimescaleDB container

requirements.txt          # Python dependencies
.env                      # Environment variables
```

## Next Steps

1. **Build your API endpoints** - Use FastAPI or Flask with the models
2. **Create strategies** - Use `manage_users.py` patterns to create strategy management
3. **Integrate with Alpaca** - Connect your trading logic to store trades
4. **Set up monitoring** - Add logging, alerts, and performance tracking

## Troubleshooting

### Database not starting
```bash
docker ps  # Check if running
docker logs vegapunk_db  # View logs
```

### Connection issues
- Verify `.env` has correct `DATABASE_URL`
- Check database is running: `docker ps | grep vegapunk_db`
- Test connection: `docker exec vegapunk_db psql -U user -d vegapunk -c "SELECT 1"`

### Migration issues
```bash
alembic current  # Check current revision
alembic history  # View all migrations
alembic stamp head  # Force stamp to current revision
```

## Documentation

- [DATABASE.md](DATABASE.md) - Complete database setup guide
- [Alembic Docs](https://alembic.sqlalchemy.org/) - Migration system
- [SQLAlchemy Docs](https://docs.sqlalchemy.org/) - ORM documentation
- [TimescaleDB Docs](https://docs.timescale.com/) - Time-series features

---

**Setup completed on**: 2025-11-18
**Admin user**: pirateking
**Database version**: PostgreSQL 16 + TimescaleDB
