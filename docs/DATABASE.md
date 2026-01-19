# Database Setup Guide

## Overview

This project uses **PostgreSQL with TimescaleDB** for efficient time-series data storage, particularly for the trades table.

## Database Models

- **User**: User accounts with trading preferences
- **Strategy**: Trading strategies with parameters
- **Position**: Currently open positions
- **Trade**: Historical trades (TimescaleDB hypertable)
- **PerformanceMetrics**: Strategy performance tracking
- **RiskEvent**: Risk management event logs

## Quick Start

### 1. Start the Database

```bash
cd docker
docker compose up -d
```

**Note**: You may need to verify your Docker Hub email first if you see an authentication error.

### 2. Initialize the Database

Choose one of these methods:

#### Option A: Using the setup script (Recommended)
```bash
cd api
python setup_db.py init
```

This will:
- Create all tables
- Set up TimescaleDB hypertable for trades
- Handle extension installation

#### Option B: Using Alembic migrations
```bash
cd api
alembic upgrade head
```

### 3. Verify Setup

```bash
# Check if tables were created
docker exec -it vegapunk_db psql -U user -d vegapunk -c "\dt"
```

## Environment Variables

Your `.env` file should contain:

```env
DATABASE_URL=postgresql://user:pass@localhost:5432/vegapunk
TIMESCALE_HOST=localhost
TIMESCALE_PORT=5432
TIMESCALE_DB=vegapunk
TIMESCALE_USER=user
TIMESCALE_PASSWORD=pass
```

## Database Management

### Create a Migration

After modifying models:

```bash
cd api
alembic revision --autogenerate -m "Description of changes"
```

Review the generated migration in `alembic/versions/`, then apply it:

```bash
alembic upgrade head
```

### Rollback a Migration

```bash
alembic downgrade -1  # Rollback one migration
alembic downgrade <revision>  # Rollback to specific revision
```

### Reset Database (⚠️ Deletes all data)

```bash
python setup_db.py reset
```

### View Migration History

```bash
alembic current   # Show current revision
alembic history   # Show all migrations
```

## TimescaleDB Features

The `trades` table is configured as a hypertable partitioned by `timestamp`. This provides:

- Efficient time-series queries
- Automatic data partitioning
- Better performance for large datasets
- Built-in compression options (can be enabled later)

### Useful TimescaleDB Queries

```sql
-- Check hypertable info
SELECT * FROM timescaledb_information.hypertables;

-- Get trades in last 24 hours
SELECT * FROM trades
WHERE timestamp > NOW() - INTERVAL '24 hours';

-- Aggregate trades by hour
SELECT time_bucket('1 hour', timestamp) AS hour,
       symbol,
       COUNT(*) as trade_count,
       SUM(pnl) as total_pnl
FROM trades
WHERE timestamp > NOW() - INTERVAL '7 days'
GROUP BY hour, symbol
ORDER BY hour DESC;
```

## Troubleshooting

### Database Connection Issues

1. Check if container is running:
   ```bash
   docker ps | grep vegapunk_db
   ```

2. Check logs:
   ```bash
   docker logs vegapunk_db
   ```

3. Test connection:
   ```bash
   docker exec -it vegapunk_db psql -U user -d vegapunk
   ```

### TimescaleDB Extension Not Found

If you see errors about TimescaleDB extension:

1. Verify you're using the TimescaleDB image (not plain PostgreSQL)
2. Manually install extension:
   ```sql
   CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
   ```

### Migration Conflicts

If you have migration conflicts:

```bash
# Check current state
alembic current

# Stamp database to specific revision
alembic stamp head

# Or reset and recreate
python setup_db.py reset
```

## Production Considerations

### Security
- Change default passwords in `.env`
- Use secrets management (AWS Secrets Manager, etc.)
- Enable SSL connections
- Restrict database access by IP

### Performance
- Add indexes on frequently queried columns
- Enable TimescaleDB compression for old data
- Set up retention policies
- Configure connection pooling

### Backups
```bash
# Backup
docker exec vegapunk_db pg_dump -U user vegapunk > backup.sql

# Restore
docker exec -i vegapunk_db psql -U user vegapunk < backup.sql
```

## Next Steps

1. Start the database: `cd docker && docker compose up -d`
2. Initialize tables: `cd api && python setup_db.py init`
3. Create test data (optional)
4. Build your API endpoints using the models
