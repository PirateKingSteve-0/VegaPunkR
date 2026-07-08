# AWS RDS PostgreSQL — Setup & Operations

How the VegaPunkR database runs on AWS, how to connect, how to migrate/change it,
and how to see what's connected. Companion to the play-by-play in
[../JOURNAL.md](../JOURNAL.md) (July 8, 2026 entry).

> **Security note:** This file is committed to git. **Never** put the master
> password, `RESEND_API_KEY`, or any secret in here. The password lives only in
> each machine's gitignored `.env`. The endpoint/username below are *not* secrets
> on their own — access is gated by the security group allowlist **and** the password.

---

## 1. What's running

| Thing | Value |
|-------|-------|
| Service | AWS RDS for **PostgreSQL 16.14** |
| Instance id | `vegapunkr-db` |
| Endpoint | `vegapunkr-db.c5ugmsk2a241.us-west-1.rds.amazonaws.com` |
| Port | `5432` |
| Region | `us-west-1` |
| Instance class | `db.t4g.micro` (2 vCPU / 1 GB, ARM/Graviton) |
| Storage | 20 GiB gp3, 3000 IOPS baseline, **autoscaling off** |
| Availability | Single-AZ (no standby) |
| Master user | `vegapunk` |
| Databases | `vegapunkr_dev`, `vegapunkr_prod` |
| Encryption | At rest, default `aws/rds` KMS key |
| Backups | Automated, 7-day retention |
| Deletion protection | **On** |
| Public access | Yes (gated by security group) |

**Databases inside the one instance:**
- `vegapunkr_dev` — development / shared working data (migrated from local; ~610 trades).
- `vegapunkr_prod` — live-trading data (schema only; was empty at cutover).
- The **test** DB stays **local** (ephemeral tmpfs Docker container on port 5433) — not in RDS.

> ⚠️ **Name gotcha:** username is `vegapunk` (no `r`); the host and database names
> are `vegapunkr...` / `vegapunkr_dev` (with `r`). Mixing these up is the #1 connection error.

---

## 2. How the app connects

`api/config.py` calls `load_dotenv()` on import, then `api/database.py` builds one
SQLAlchemy engine per environment from these `.env` keys:

```bash
# .env  (gitignored — real password inline, URL-safe chars only)
DATABASE_DEV_URL=postgresql://vegapunk:<RDS_PASSWORD>@vegapunkr-db.c5ugmsk2a241.us-west-1.rds.amazonaws.com:5432/vegapunkr_dev?sslmode=require
DATABASE_PROD_URL=postgresql://vegapunk:<RDS_PASSWORD>@vegapunkr-db.c5ugmsk2a241.us-west-1.rds.amazonaws.com:5432/vegapunkr_prod?sslmode=require
DATABASE_URL=postgresql://vegapunk:<RDS_PASSWORD>@vegapunkr-db.c5ugmsk2a241.us-west-1.rds.amazonaws.com:5432/vegapunkr_dev?sslmode=require
DATABASE_TEST_URL=postgresql://user:pass@localhost:5433/vegapunk_test   # stays local
```

Notes:
- `?sslmode=require` forces TLS (RDS supports it; the CA is AWS-managed).
- Password must avoid `@ : / ? # [ ] %` (they collide with URL syntax). `- _ . ! *` are safe.
- Prefer supplying the password via **`PGPASSWORD`** for one-off CLI commands so it never
  lands in shell history or a connection string (see §5).

**Quick connection test** (run from `api/`, uses the app's own config path):

```bash
python -c "
from config import settings, Environment
from database import engines
from sqlalchemy import text
print('DEV host:', settings.DATABASE_DEV_URL.split('@')[-1])
with engines[Environment.DEV].connect() as c:
    print('trades:', c.execute(text('SELECT count(*) FROM trades')).scalar())
"
# Expect: DEV host: vegapunkr-db...vegapunkr_dev?sslmode=require ; trades: 610
```

---

## 3. Access control (security group)

The DB is **not** open to the internet. Inbound is controlled by security group
`vegapunkr-db-sg`:

- One rule: **PostgreSQL / TCP 5432** from your home public IP as a `/32`
  (at cutover: `68.5.183.199/32`).
- Both PC and laptop share the home public IP, so one rule covers both **on the home network**.

### When you can't connect (hangs then times out)
Almost always the allowlist. Your public IP changed (ISP rotation) or you're on a
different network.

```bash
curl https://checkip.amazonaws.com          # get your current public IP
```
Then: **EC2 → Security Groups → `vegapunkr-db-sg` → Inbound rules → Edit** → update/add
`PostgreSQL 5432` from `<new-ip>/32`.

### Better long-term: Tailscale
The IP allowlist breaks on IP rotation and off-network use. If that becomes annoying,
install **Tailscale** on the RDS-side access path and both machines to get a stable
private IP with **no exposed port**. (Note: you can't install Tailscale *on* RDS itself —
it's a managed box — so this needs a small EC2 jump host in the same VPC. Deferred for now.)

---

## 4. Viewing logs & database connections

You can't see the DB connection from **browser dev tools** — those only show
browser↔API traffic. The API-server↔RDS hop is server-side. Use these instead:

### A. AWS Console — is anything connected? (visual)
**RDS → Databases → `vegapunkr-db` → Monitoring tab → "DB Connections" graph.**
- When the app runs, the count climbs (SQLAlchemy pools: `pool_size` 10 dev / 15 prod).
- Baseline of 1–3 is RDS's own internal `rdsadmin` — look for the *increase*.
- CloudWatch is ~1-minute granularity, so give it a minute.

### B. AWS Console — what's it doing? (near real-time)
**RDS → Performance Insights → `vegapunkr-db`.** Shows active sessions, the actual SQL,
and which database (`vegapunkr_dev` vs `vegapunkr_prod`). Free 7-day retention is enabled.

### C. psql — exactly who is connected right now (most precise)
```bash
export PGPASSWORD=<RDS_PASSWORD>
RDS="postgresql://vegapunk@vegapunkr-db.c5ugmsk2a241.us-west-1.rds.amazonaws.com:5432/vegapunkr_dev?sslmode=require"
psql "$RDS" -c "
SELECT datname, client_addr, application_name, state, query_start
FROM pg_stat_activity
WHERE datname LIKE 'vegapunkr%' AND client_addr IS NOT NULL;"
```
Rows with `client_addr` = your home public IP are your app talking to RDS. Zero rows =
nothing is connected (e.g. app still on localhost, or not running).

### D. Postgres logs
**RDS → `vegapunkr-db` → Logs & events tab → Logs.** Viewable in-console for free
(we did **not** enable CloudWatch log export, which would add cost). To get connection
logging in the logs, you'd set `log_connections`/`log_disconnections` in a **custom DB
parameter group** and attach it — not enabled by default.

---

## 5. Common operations

All examples assume:
```bash
export PGPASSWORD=<RDS_PASSWORD>          # keeps the pw out of URLs / history
RDS_DEV="postgresql://vegapunk@vegapunkr-db.c5ugmsk2a241.us-west-1.rds.amazonaws.com:5432/vegapunkr_dev?sslmode=require"
RDS_PROD="postgresql://vegapunk@vegapunkr-db.c5ugmsk2a241.us-west-1.rds.amazonaws.com:5432/vegapunkr_prod?sslmode=require"
```
> For interactive use you can also `read -rs -p "RDS password: " PGPASSWORD; export PGPASSWORD`
> so the password is never typed on a visible command line.

### Open a shell
```bash
psql "$RDS_DEV"
```

### Inspect
```bash
psql "$RDS_DEV" -c "\dt"                              # list tables
psql "$RDS_DEV" -c "\l"                               # list databases
psql "$RDS_DEV" -c "SELECT count(*) FROM trades;"
```

### ⚠️ Schema changes — build with create_all, NOT plain Alembic
**Alembic in this repo is behind `models.py`** (no migration creates `system_events`),
so `alembic upgrade head` produces an **incomplete** schema. Until that's fixed, build a
fresh schema from the models:

```bash
cd api
DATABASE_DEV_URL="$RDS_DEV" DATABASE_URL="$RDS_DEV" python -c "
from database import engines
from config import Environment
from models import Base
Base.metadata.create_all(engines[Environment.DEV])   # idempotent: only creates missing tables
print('ok:', sorted(Base.metadata.tables.keys()))
"
```
To rebuild from scratch (empty DB only!), add `Base.metadata.drop_all(e)` before `create_all`.

**Tech debt to fix:** autogenerate a migration to bring Alembic up to `models.py`
(minimum: add `system_events`), then decide whether Alembic or `create_all` is canonical.

---

## 6. Migrating data (local → RDS, or dev → prod)

This is the validated procedure (proven with a local dress-rehearsal at cutover). The two
non-obvious hazards are (a) TimescaleDB internals in local dumps and (b) RDS blocking
`--disable-triggers`.

### Step 1 — dump the source (data only)
```bash
# from a LOCAL Timescale DB, exclude alembic_version so the target keeps its own
pg_dump "postgresql://user:pass@localhost:5435/vegapunk_dev" \
  --data-only --exclude-table=alembic_version -Fc -f ~/dump.dump
```

### Step 2 — restore into RDS (public schema only)
```bash
pg_restore --data-only --disable-triggers --schema=public -d "$RDS_DEV" ~/dump.dump
```
- `--schema=public` **drops the `_timescaledb_catalog.*` internal tables** a hypertable
  dump includes (they don't exist on plain RDS and would error).
- **Expect ~14 `permission denied ... is a system trigger` errors** on RDS — harmless.
  RDS's `rds_superuser` can't toggle internal FK triggers, but `pg_dump` orders data
  parent-before-child so the `COPY`s succeed anyway. Sequences carry over automatically.

### Step 2b — if data genuinely loads out of FK order
Only needed if a future schema has FK cycles that parent-first ordering can't satisfy.
Convert the dump to SQL and disable FK enforcement the RDS-allowed way:
```bash
pg_restore --data-only --schema=public -f data.sql ~/dump.dump
# prepend this line to data.sql, then run in ONE session:
#   SET session_replication_role = replica;
psql "$RDS_DEV" -1 -f data.sql
```
`session_replication_role = replica` is permitted for `rds_superuser` (unlike
`ALTER TABLE ... DISABLE TRIGGER ALL`).

### Step 3 — verify counts + sequences
```bash
psql "$RDS_DEV" -c "
SELECT 'trades' t, count(*) FROM trades
UNION ALL SELECT 'system_events', count(*) FROM system_events ORDER BY 1;"

psql "$RDS_DEV" -c "SELECT sequencename, last_value FROM pg_sequences WHERE schemaname='public' ORDER BY 1;"
```
If a sequence is behind its table's `max(id)` (rare), fix explicitly:
```bash
psql "$RDS_DEV" -c "SELECT setval(pg_get_serial_sequence('trades','id'),
  GREATEST((SELECT COALESCE(MAX(id),1) FROM trades),1), (SELECT COUNT(*)>0 FROM trades));"
```

---

## 7. Rollback

Local Docker DBs are left intact, and each `.env` DB line has its original localhost URL
as a `# local rollback:` comment beneath it. To revert a machine to local:
1. In `.env`, swap the three RDS URLs back to the commented localhost values.
2. `docker compose -f docker/docker-compose.yml up -d` (if not already running).
3. Re-run the §2 connection test — `DEV host:` should show `localhost:5435`.

---

## 8. Cost & guardrails

Roughly **~$15/mo**: db.t4g.micro (~$12) + 20 GiB gp3 (~$2) + backups. Deliberately kept
low by avoiding Multi-AZ, RDS Proxy, Enhanced Monitoring, DevOps Guru, CloudWatch log
export, and provisioned IOPS above the free 3000 baseline. If you ever see the bill jump,
check: storage autoscaling (should be off), provisioned IOPS, and whether Multi-AZ got
enabled.

---

## 9. Operational rules (don't skip)

- **⚠️ Run the live trading engine on ONE machine only.** Both machines share the same
  `positions`/`trades` rows; two `stream_driven_worker`s = double-fired real orders. The
  `_pending_buy_reservations` ledger is process-scoped and **not** shared across machines.
- **Off the home network?** Add that machine's public IP to `vegapunkr-db-sg` (or use the
  Tailscale path in §3).
- **Secrets stay in `.env` (gitignored).** If the engine ever moves into AWS, switch the
  DB password to **SSM Parameter Store** (`SecureString`, free) instead of baking it in.
- **Test a restore someday.** 7-day automated backups exist but a point-in-time restore
  has never been exercised.
