# Multi-Database & Trading Mode Setup Guide

## Overview

VegaPunkR now supports **multi-database environments** and **trading mode switching** without server restarts:

- **3 Databases**: Dev, Test, Prod (switch instantly via UI)
- **2 Trading Modes**: Paper (Alpaca) and Live (Schwab) (hot-swap via UI)
- **No Downtime**: All switches happen at runtime

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│            EC2 Server (Single Instance)                  │
│      https://vegapunk.yourdomain.com                    │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  UI Controls (Top Bar)                                   │
│  ┌────────────────────────────────────────────┐        │
│  │ Environment: [Dev] [Test] [Prod]          │        │
│  │ Trading Mode: [Paper] [Live]              │        │
│  └────────────────────────────────────────────┘        │
│                                                          │
│  Backend (Auto-Routes)                                   │
│  ├─ Dev  → vegapunk_dev (port 5432)                    │
│  ├─ Test → vegapunk_test (port 5433)                   │
│  └─ Prod → vegapunk_prod (port 5434)                   │
│                                                          │
│  ├─ Paper → Alpaca Paper Trading API                   │
│  └─ Live  → Schwab Live Trading API                    │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

---

## Setup Instructions

### 1. Start All Databases

```bash
# Start all three databases
cd docker
docker-compose up -d

# Verify all containers are running
docker ps

# Expected output:
# vegapunk_db_dev   (port 5432)
# vegapunk_db_test  (port 5433)
# vegapunk_db_prod  (port 5434)
```

### 2. Run Migrations on Each Database

You need to run migrations on **each database separately**:

```bash
cd api

# Migrate Dev database
DATABASE_URL=postgresql://user:pass@localhost:5432/vegapunk_dev alembic upgrade head

# Migrate Test database
DATABASE_URL=postgresql://user:pass@localhost:5433/vegapunk_test alembic upgrade head

# Migrate Prod database
DATABASE_URL=postgresql://user:pass@localhost:5434/vegapunk_prod alembic upgrade head
```

**What this does:**
- Creates all tables (users, strategies, positions, trades, etc.)
- Adds indexes for performance
- Applies the new `selected_environment` and `selected_trading_mode` columns

### 3. Seed Initial Data (Optional)

If you want to pre-populate databases with test data or strategy templates:

```bash
# Seed Dev database
DATABASE_URL=postgresql://user:pass@localhost:5432/vegapunk_dev python manage_users.py

# Seed Test database (optional)
DATABASE_URL=postgresql://user:pass@localhost:5433/vegapunk_test python manage_users.py

# Prod database - DO NOT seed with test data!
```

### 4. Start Backend Server

```bash
cd api
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

The server now maintains connections to **all 3 databases simultaneously** and routes queries based on user selection.

### 5. Start Frontend

```bash
cd ui
npm start
```

---

## Usage

### Switching Environments (Database)

**In the UI:**
1. Log in to your account
2. See the Environment Controls at the top
3. Click **Dev**, **Test**, or **Prod**
4. Switch happens **instantly** (no reload required)

**What happens:**
- All subsequent API calls route to the selected database
- Data is isolated between environments
- No server restart needed

**Use Cases:**
- **Dev**: Experiment with new strategies, test features
- **Test**: Validate paper trading strategies before production
- **Prod**: Live trading with real strategies

### Switching Trading Modes (Paper/Live)

**In the UI:**
1. Click **Paper** or **Live** button
2. For **Live mode**, confirm the warning dialog
3. Switch happens **instantly**

**What happens:**
- **Paper Mode**: Orders route to Alpaca Paper Trading API
- **Live Mode**: Orders route to Schwab Live Trading API (⚠️ **REAL MONEY**)
- Trading client hot-swaps without server restart

**Safety Features:**
- Live mode requires explicit confirmation
- Warning banner shows when in live mode
- Visual indicators (red badge) for live trading

---

## API Endpoints

### Get Current Environment Settings

```bash
GET /api/v1/system/environment

Response:
{
  "environment": "dev",
  "trading_mode": "paper",
  "database": "vegapunk_dev",
  "trading_api": "Alpaca Paper",
  "can_toggle_trading_mode": true,
  "warning": null
}
```

### Switch Environment

```bash
POST /api/v1/system/environment
Content-Type: application/json

{
  "environment": "test"
}

Response:
{
  "success": true,
  "environment": "test",
  "database": "vegapunk_test",
  "message": "Environment switched to test (no restart required)"
}
```

### Switch Trading Mode

```bash
POST /api/v1/system/trading-mode
Content-Type: application/json

{
  "mode": "live"
}

Response:
{
  "success": true,
  "trading_mode": "live",
  "trading_api": "Schwab Live",
  "message": "Trading mode switched to live (no restart required)",
  "warning": "⚠️ Live trading uses real money!"
}
```

---

## Database Details

### Development Database (`vegapunk_dev`)

- **Port**: 5432
- **Storage**: Persistent volume (`timescale_data_dev`)
- **Purpose**: Feature development, experimentation
- **Characteristics**: Can be reset/cleaned without affecting prod

### Test Database (`vegapunk_test`)

- **Port**: 5433
- **Storage**: In-memory (tmpfs) - **data lost on restart**
- **Purpose**: Strategy validation, paper trading testing
- **Characteristics**: Fast, isolated, disposable

### Production Database (`vegapunk_prod`)

- **Port**: 5434
- **Storage**: Persistent volume (`timescale_data_prod`)
- **Purpose**: Live trading, real strategies
- **Characteristics**: Protected, backed up, persistent

---

## Configuration

### Environment Variables (`.env`)

```bash
# Database URLs
DATABASE_DEV_URL=postgresql://user:pass@localhost:5432/vegapunk_dev
DATABASE_TEST_URL=postgresql://user:pass@localhost:5433/vegapunk_test
DATABASE_PROD_URL=postgresql://user:pass@localhost:5434/vegapunk_prod

# Alpaca API Keys
ALPACA_PAPER_API_KEY=your_paper_key
ALPACA_PAPER_SECRET_KEY=your_paper_secret

# Schwab API Keys (for live trading)
APP_KEY=your_schwab_app_key
APP_SECRET=your_schwab_app_secret
CALLBACK_URL=https://127.0.0.1:8182
TOKEN_PATH=token.json
```

### User Preferences

Each user's environment and trading mode selections are stored in the database:

```sql
SELECT
  email,
  selected_environment,
  selected_trading_mode
FROM users;
```

**This means:**
- Each user can work in different environments simultaneously
- Preferences persist across sessions
- No conflicts between users

---

## Trading Client Manager

The `TradingClientManager` handles hot-swapping between APIs:

```python
from api.engine import trading_manager

# Get appropriate client based on user's trading mode
client = trading_manager.get_client(current_user)

# Place order (automatically routes to correct API)
order = await trading_manager.place_order(
    user=current_user,
    symbol="SPY",
    qty=1,
    side="buy",
    order_type="market"
)

# Get account info (from appropriate API)
account = await trading_manager.get_account(current_user)
```

**Under the hood:**
- Paper mode → Uses `alpaca.trading.client.TradingClient`
- Live mode → Uses `schwab_integration.client.SchwabClient`
- Clients are cached and reused for performance

---

## Frontend Integration

### System Service (TypeScript)

```typescript
import { SystemService } from './services/system.service';

// Get current settings
this.systemService.getEnvironmentSettings().subscribe(settings => {
  console.log('Environment:', settings.environment);
  console.log('Trading Mode:', settings.trading_mode);
});

// Switch environment
this.systemService.setEnvironment('prod').subscribe(response => {
  console.log('Switched to:', response.environment);
});

// Switch trading mode
this.systemService.setTradingMode('live').subscribe(response => {
  console.log('Warning:', response.warning);
});
```

### Environment Controls Component

Add to any page (typically in header/navbar):

```typescript
import { EnvironmentControlsComponent } from './components/environment-controls/environment-controls.component';

@Component({
  standalone: true,
  imports: [EnvironmentControlsComponent],
  template: `
    <app-environment-controls></app-environment-controls>
  `
})
```

---

## Safety Checks

### Before Going Live

**Checklist:**

1. ✅ Test all strategies in **Test database** with **Paper mode**
2. ✅ Validate P&L calculations are accurate
3. ✅ Confirm fee calculations match broker statements
4. ✅ Test risk management limits (stop loss, daily loss)
5. ✅ Verify Schwab authentication works
6. ✅ Run at least 2 weeks of paper trading in **Prod database**
7. ✅ Review all logs for errors

### Live Trading Safeguards

When `trading_mode = "live"`:

- ⚠️ **Visual indicators**: Red badges, warning banners
- ⚠️ **Confirmation dialogs**: Must confirm before switching
- ⚠️ **Logging**: All orders logged with "LIVE TRADING" prefix
- ⚠️ **Discord alerts**: Prod webhook receives notifications

---

## Troubleshooting

### Database Connection Issues

```bash
# Check if all databases are running
docker ps | grep vegapunk

# Restart databases
docker-compose restart

# Check logs
docker logs vegapunk_db_dev
docker logs vegapunk_db_test
docker logs vegapunk_db_prod
```

### Migration Errors

```bash
# Check current migration status
alembic current

# Rollback last migration
alembic downgrade -1

# Re-run migrations
alembic upgrade head
```

### Environment Not Switching

```bash
# Check user preferences
psql -h localhost -p 5432 -U user -d vegapunk_dev
SELECT * FROM users;

# Manually update (for testing)
UPDATE users SET selected_environment = 'dev' WHERE id = 1;
```

### Trading Client Errors

```bash
# Check logs for client initialization
tail -f api/logs/trading.log

# Verify API keys
echo $ALPACA_PAPER_API_KEY
echo $APP_KEY
```

---

## Deployment (EC2)

### Environment Variables on EC2

```bash
# On EC2, update .env with production URLs
DATABASE_DEV_URL=postgresql://user:pass@ec2-instance:5432/vegapunk_dev
DATABASE_TEST_URL=postgresql://user:pass@ec2-instance:5433/vegapunk_test
DATABASE_PROD_URL=postgresql://user:pass@ec2-instance:5434/vegapunk_prod
```

### Database Backups

```bash
# Backup Prod database (CRITICAL!)
docker exec vegapunk_db_prod pg_dump -U user vegapunk_prod > backup_$(date +%Y%m%d).sql

# Restore from backup
docker exec -i vegapunk_db_prod psql -U user vegapunk_prod < backup_20251120.sql
```

### Monitoring

```bash
# Check database sizes
docker exec vegapunk_db_prod psql -U user -d vegapunk_prod -c "
  SELECT pg_size_pretty(pg_database_size('vegapunk_prod'));
"

# Check active connections
docker exec vegapunk_db_prod psql -U user -d vegapunk_prod -c "
  SELECT count(*) FROM pg_stat_activity;
"
```

---

## Next Steps for Alpaca Integration

Now that the infrastructure is ready, you can proceed with implementing the strategy execution engine:

1. **Signal Generator**: Monitors Alpaca data streams, generates signals
2. **Order Executor**: Takes signals, routes to appropriate API (Paper/Live)
3. **Position Sync**: Reconciles positions between broker and database
4. **Risk Manager**: Enforces limits before order execution

See `JOURNAL.md` for the full Alpaca integration checklist.

---

## Summary

✅ **Multi-Database**: Switch between Dev/Test/Prod instantly
✅ **Trading Modes**: Toggle Paper/Live without restart
✅ **Hot-Swapping**: All clients managed at runtime
✅ **Safety First**: Confirmations, warnings, visual indicators
✅ **Production Ready**: Persistent storage, backups, monitoring

**You're now ready to start Phase 1: Paper Trading with Alpaca!**
