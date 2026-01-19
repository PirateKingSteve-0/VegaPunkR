# VegaPunkR Project Health Check

**Date:** November 20, 2025
**Reviewed By:** Claude Code

---

## 1) Alignment with JOURNAL.md

The codebase is **largely aligned** with the journal. Key documented features that ARE implemented:

| Journal Feature | Status | Location |
|-----------------|--------|----------|
| Database Layer (6 models) | Implemented | `api/models.py` |
| FastAPI Backend with JWT | Implemented | `api/app.py`, `api/auth.py` |
| All CRUD Routers (8) | Implemented | `api/routers/` |
| Strategy Templates (8) | Implemented | `api/strategy_templates.py` |
| Angular 20 Frontend | Implemented | `ui/` |
| Schwab Integration | Implemented | `api/schwab_integration/` |
| Strategy Execution Engine | Implemented | `api/engine/` (6 modules) |
| Background Worker | Implemented | `api/services/strategy_worker.py` |
| Multi-database setup | Implemented | `docker/docker-compose.yml` |
| Risk Management | Implemented | `api/engine/risk_manager.py` |

---

## 2) Missing Parts from Journal

### High Priority (documented but incomplete/missing)

| Feature | Journal Status | Actual Status |
|---------|---------------|---------------|
| **Stock market data service** | Mentioned in TODOs | Stub only - `strategy_worker.py:252-254` |
| **Crypto market data service** | Mentioned in TODOs | Stub only - `strategy_worker.py:257-259` |
| **WebSocket real-time updates** | Listed in "Future Enhancements" | Alpaca SDK bundled but not wired to frontend |
| **Backtesting framework** | Listed in "Strategy Engine" priorities | Not implemented |
| **Frontend services** (position, trade, performance, risk) | Listed as "Ready for Implementation" | Partially done - services exist but may not be wired |
| **Chart.js integration** | Listed in frontend priorities | Installed but placeholders only |
| **Export to CSV** | Listed in user features | Not implemented |
| **Discord notifications** | Mentioned in .env | No notification service found |

### Lower Priority (nice-to-have from journal)

- Mobile app (React Native/Flutter)
- ML strategy optimization
- Multi-broker (Interactive Brokers)
- Social trading features
- Dark mode support

---

## 3) Folder Structure Suggestions

### Current Issues & Recommendations

#### A. Bundled Alpaca SDK (57+ files)

```
api/alpaca/  <-- Contains full SDK copy
```

**Problem:** SDK bundled in repo instead of using pip package
**Fix:** Remove folder, add `alpaca-py` to requirements.txt

#### B. Inconsistent docs location

```
api/docs/DATABASE.md
api/docs/MULTI_DATABASE_SETUP.md
api/docs/TESTING.md
api/SETUP_COMPLETE.md       <-- Not in docs/
SETUP.md                    <-- Root level
JOURNAL.md                  <-- Root level
STRATEGY_EXECUTION_ENGINE.md <-- Root level
```

**Fix:** Consolidate all docs to `docs/` folder at root

#### C. Empty/stub service directories

```
api/services/market_data/stocks/__init__.py   <-- Empty
api/services/market_data/crypto/__init__.py   <-- Empty
```

**Fix:** Either implement or remove until needed

#### D. Suggested improved structure

```
VegaPunkR/
├── docs/                    <-- All documentation
│   ├── JOURNAL.md
│   ├── SETUP.md
│   └── ...
├── api/
│   ├── routers/             <-- Keep as-is (well organized)
│   ├── engine/              <-- Keep as-is (well organized)
│   ├── services/
│   │   ├── strategy_worker.py
│   │   └── market_data/     <-- Clean up stubs
│   ├── integrations/        <-- Rename from schwab_integration
│   │   └── schwab/
│   └── tests/               <-- Keep as-is
├── ui/                      <-- Keep as-is
└── docker/                  <-- Keep as-is
```

---

## 4) Low-Effort Optimizations

### A. Database connection leak potential in strategy_worker.py

**Current (line 107-137):**
```python
db = SessionLocal()
try:
    active_strategies = db.query(Strategy).filter(...)
    # ... async gather that creates MORE sessions
finally:
    db.close()
```

**Issue:** Parent session stays open while child async tasks run with their own sessions

**Quick Fix:** Close parent session BEFORE spawning async tasks:
```python
db = SessionLocal()
try:
    strategy_ids = [s.id for s in db.query(Strategy.id).filter(...)]
finally:
    db.close()  # Close immediately

results = await asyncio.gather(*[self._execute_single_strategy(sid) for sid in strategy_ids])
```

### B. N+1 query in monitor_positions (line 294-298)

**Current:**
```python
for position in open_positions:
    user = db.query(User).filter(User.id == position.user_id).first()
    strategy = db.query(Strategy).filter(Strategy.id == position.strategy_id).first()
```

**Quick Fix:** Use JOIN or eager loading:
```python
from sqlalchemy.orm import joinedload

open_positions = db.query(Position).options(
    joinedload(Position.user),
    joinedload(Position.strategy)
).filter(Position.qty > 0).all()
```

### C. Add indexes to commonly-filtered columns

In `api/models.py`, add:
```python
# On Strategy
__table_args__ = (Index('ix_strategy_is_active', 'is_active'),)

# On Position
__table_args__ = (Index('ix_position_qty', 'qty'),)
```

### D. Remove deprecated Python 3.9 references

Journal mentions Python 3.9, but project upgraded to 3.13. Updates needed:
- `JOURNAL.md` line 312 mentions Python 3.9
- Consider adding `.python-version` file with `3.13`

### E. Type hint improvements in engine modules

Many functions lack return type hints. Adding them enables better IDE support and catches bugs:

```python
# Current
def execute_strategy_tick(self, user, strategy, market_data):

# Better
def execute_strategy_tick(
    self, user: User, strategy: Strategy, market_data: Dict[str, Any]
) -> Dict[str, Any]:
```

---

## Summary

| Area | Score | Notes |
|------|-------|-------|
| Journal Alignment | 85% | Core features implemented |
| Missing Features | ~6-8 items | Mostly data services + backtesting |
| Folder Structure | Needs cleanup | Bundled SDK, scattered docs |
| Optimization Potential | Easy wins available | DB queries, indexes |

The codebase is well-architected overall. The main technical debt is:
1. Bundled Alpaca SDK (should use pip package)
2. Incomplete market data services for stocks/crypto
3. Scattered documentation files

---

## Recommended Next Steps

1. **Quick Wins (< 1 hour)**
   - Apply N+1 query fix in `monitor_positions`
   - Close DB session before async gather in `execute_all_strategies`
   - Add database indexes

2. **Medium Effort (1-4 hours)**
   - Consolidate documentation to `docs/` folder
   - Remove bundled Alpaca SDK, use pip package
   - Add type hints to engine modules

3. **Larger Efforts (future sessions)**
   - Implement stock/crypto market data services
   - Build backtesting framework
   - Wire up WebSocket to frontend for real-time updates
