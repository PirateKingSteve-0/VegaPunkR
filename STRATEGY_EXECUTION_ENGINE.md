# Strategy Execution Engine

Complete implementation of automated strategy execution with paper trading and live trading modes.

## 🏗️ Architecture

The Strategy Execution Engine consists of 5 core components working together:

```
┌─────────────────────────────────────────────────────────────┐
│                   Background Worker                          │
│              (strategy_worker.py)                            │
│  • Runs every 60s for strategy execution                    │
│  • Runs every 30s for position monitoring                   │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────┐
│               Strategy Executor                              │
│           (strategy_executor.py)                             │
│  • Orchestrates execution flow                               │
│  • Manages strategy state (running/stopped)                 │
│  • Coordinates all components                               │
└──────┬──────────┬──────────┬──────────┬────────────────────┘
       │          │          │          │
       ▼          ▼          ▼          ▼
   ┌──────┐  ┌───────┐  ┌───────┐  ┌──────────┐
   │ Risk │  │Signal │  │Order  │  │Trading   │
   │Manager│  │Gen.  │  │Manager│  │Client    │
   └──────┘  └───────┘  └───────┘  │Manager   │
                                    └─────┬────┘
                                          │
                      ┌───────────────────┴────────────────┐
                      │                                    │
                      ▼                                    ▼
              ┌──────────────┐                  ┌──────────────┐
              │Alpaca Paper  │                  │Schwab Live   │
              │Trading API   │                  │Trading API   │
              └──────────────┘                  └──────────────┘
```

## 📦 Components

### 1. Risk Manager ([api/engine/risk_manager.py](api/engine/risk_manager.py))

**Purpose:** Pre-trade validation and risk controls

**Key Features:**
- ✅ Position sizing based on account size and risk parameters
- ✅ Pre-trade validation (daily loss limits, max positions, drawdown)
- ✅ Daily loss limit enforcement (default 5% of account)
- ✅ Maximum drawdown monitoring (default 10% of account)
- ✅ Position limit checks
- ✅ Risk event logging to database
- ✅ Paper vs live mode validation

**Usage Example:**
```python
from api.engine.risk_manager import RiskManager

risk_manager = RiskManager(db)

# Calculate position size
qty = risk_manager.calculate_position_size(
    user=current_user,
    strategy=strategy,
    current_price=450.25
)

# Validate pre-trade
risk_check = risk_manager.validate_pre_trade(
    user=current_user,
    strategy=strategy,
    symbol="SPY",
    qty=2,
    estimated_price=450.25,
    side="buy"
)

if risk_check.approved:
    # Place trade
else:
    print(f"Trade rejected: {risk_check.reason}")
```

### 2. Signal Generator ([api/engine/signal_generator.py](api/engine/signal_generator.py))

**Purpose:** Technical indicator calculations and signal detection

**Supported Indicators:**
- ✅ EMA (Exponential Moving Average)
- ✅ VWAP (Volume Weighted Average Price)
- ✅ RSI (Relative Strength Index)
- ✅ Volume spike detection
- ✅ Delta filtering (for options)
- ✅ Liquidity checks (open interest, bid-ask spread)
- ✅ $TICK indicator support

**Entry Signal Conditions:**
- Price vs EMA (above/below)
- Price vs VWAP (above/below)
- Volume spike threshold
- Delta range (for options)
- Open interest minimum
- Bid-ask spread maximum
- Confirmation requirements

**Exit Signal Conditions:**
- ✅ Take profit percentage
- ✅ Stop loss percentage
- ✅ Trailing stops (with activation threshold)
- ✅ Time-based exits (max hold time)
- ✅ Market close exits (for 0DTE)

**Usage Example:**
```python
from api.engine.signal_generator import SignalGenerator

signal_gen = SignalGenerator()

# Check for entry signal
entry_signal = signal_gen.check_entry_signal(
    strategy=strategy,
    symbol="SPY",
    current_price=450.25,
    current_volume=1000000,
    additional_data={
        'bid': 450.24,
        'ask': 450.26,
        'delta': 0.65,
        'open_interest': 5000
    }
)

if entry_signal:
    print(f"Entry signal: {entry_signal.action} at {entry_signal.price}")
    print(f"Reason: {entry_signal.reason}")
    print(f"Confidence: {entry_signal.confidence}")
```

### 3. Order Manager ([api/engine/order_manager.py](api/engine/order_manager.py))

**Purpose:** Order lifecycle management and position tracking

**Key Features:**
- ✅ Order execution via TradingClientManager (auto-routes paper/live)
- ✅ Position entry tracking (creates/updates positions)
- ✅ Position exit tracking (calculates P&L)
- ✅ Trade record creation
- ✅ Multi-response format handling (Alpaca vs Schwab)
- ✅ Partial fill support

**Usage Example:**
```python
from api.engine.order_manager import OrderManager

order_manager = OrderManager(db)

# Execute a signal
result = await order_manager.execute_signal(
    user=current_user,
    strategy=strategy,
    signal=entry_signal,
    qty=2
)

if result.success:
    print(f"Order filled: {result.filled_qty} @ ${result.filled_price}")
else:
    print(f"Order failed: {result.message}")
```

### 4. Strategy Executor ([api/engine/strategy_executor.py](api/engine/strategy_executor.py))

**Purpose:** Main orchestration engine

**Key Features:**
- ✅ Coordinates all components (Risk, Signal, Order)
- ✅ Strategy state management (running/stopped)
- ✅ Entry signal detection and execution
- ✅ Exit signal detection and position closure
- ✅ Error handling and auto-stop after 5 consecutive errors
- ✅ Real-time P&L tracking

**Execution Flow:**
1. Check if strategy is active
2. Validate market data
3. Check for entry signals (if room for positions)
4. Generate signal via SignalGenerator
5. Calculate position size via RiskManager
6. Run pre-trade risk checks
7. Execute order via OrderManager
8. Monitor open positions for exit signals
9. Update position prices for P&L tracking

**Usage Example:**
```python
from api.engine.strategy_executor import StrategyExecutor

executor = StrategyExecutor(db)

# Execute one tick of strategy logic
result = await executor.execute_strategy_tick(
    user=current_user,
    strategy=strategy,
    market_data={
        'symbol': 'SPY',
        'price': 450.25,
        'volume': 1000000,
        'bid': 450.24,
        'ask': 450.26,
        'delta': 0.65,
        'open_interest': 5000
    }
)

# Start/stop strategy
executor.start_strategy(strategy.id)
executor.stop_strategy(strategy.id)

# Get status
status = executor.get_strategy_status(strategy.id)
```

### 5. Trading Safeguards ([api/engine/trading_safeguards.py](api/engine/trading_safeguards.py))

**Purpose:** Additional safety checks for paper and live trading

**Paper Trading Safeguards:**
- ✅ Strategy parameter validation
- ✅ Simulated slippage (0.1%)
- ✅ Simulated commissions ($0.65/contract)
- ✅ Warning messages for unrealistic expectations

**Live Trading Safeguards:**
- ✅ Multi-level confirmations required
- ✅ Market hours checking (9:30 AM - 4:00 PM ET)
- ✅ Rate limiting (max 10 orders/minute)
- ✅ Account balance verification
- ✅ Emergency stop mechanism
- ✅ Large position warnings

**Usage Example:**
```python
from api.engine.trading_safeguards import TradingSafeguardsValidator

validator = TradingSafeguardsValidator(db)

approved, messages = validator.validate_before_execution(
    user=current_user,
    strategy=strategy,
    estimated_capital=1000.0
)

if approved:
    print("All safeguards passed")
    for msg in messages:
        print(f"  - {msg}")
else:
    print(f"Safeguards failed: {messages}")
```

### 6. Background Worker ([api/services/strategy_worker.py](api/services/strategy_worker.py))

**Purpose:** Continuous strategy monitoring and execution

**Key Features:**
- ✅ Runs every 60s for strategy execution
- ✅ Runs every 30s for position monitoring
- ✅ Uses APScheduler for lightweight scheduling
- ✅ Fetches market data (mock for now - implement real data)
- ✅ Executes all active strategies automatically
- ✅ Comprehensive error handling and logging

**Running the Worker:**

```bash
# Start as standalone process
python api/services/strategy_worker.py

# Or integrate with FastAPI app startup (recommended)
```

## 🔌 API Endpoints

### Execution Control ([api/routers/execution.py](api/routers/execution.py))

#### Start Strategy Execution
```http
POST /api/v1/execution/strategies/{strategy_id}/start
```
Enables automated execution for a strategy.

**Response:**
```json
{
  "success": true,
  "message": "Strategy 1 started",
  "started_at": "2024-01-15T10:30:00",
  "strategy": {
    "id": 1,
    "name": "SPY 0DTE Scalping",
    "type": "scalping_0dte",
    "is_paper_trading": true
  },
  "trading_mode": "paper"
}
```

#### Stop Strategy Execution
```http
POST /api/v1/execution/strategies/{strategy_id}/stop
```
Stops automated execution (does not close positions).

#### Get Execution Status
```http
GET /api/v1/execution/strategies/{strategy_id}/status
```
Returns current execution state.

**Response:**
```json
{
  "strategy_id": 1,
  "is_running": true,
  "started_at": "2024-01-15T10:30:00",
  "last_check_at": "2024-01-15T10:35:00",
  "error_count": 0,
  "last_error": null,
  "strategy": {
    "id": 1,
    "name": "SPY 0DTE Scalping",
    "type": "scalping_0dte",
    "is_active": true,
    "is_paper_trading": true
  }
}
```

#### Get Risk Summary
```http
GET /api/v1/execution/strategies/{strategy_id}/risk-summary
```
Returns current risk metrics.

**Response:**
```json
{
  "strategy_id": 1,
  "strategy_name": "SPY 0DTE Scalping",
  "today_pnl": 125.50,
  "today_pnl_pct": 1.26,
  "daily_loss_limit": 500.00,
  "daily_loss_limit_pct": 5.0,
  "daily_loss_remaining": 625.50,
  "open_positions": 2,
  "max_positions": 3,
  "unrealized_pnl": 45.00,
  "account_size": 10000.00,
  "risk_status": "OK"
}
```

#### Execute Strategy Tick (Manual - Testing Only)
```http
POST /api/v1/execution/strategies/{strategy_id}/execute-tick
```
Manually trigger one execution cycle (for testing).

**Request Body:**
```json
{
  "symbol": "SPY",
  "price": 450.25,
  "volume": 1000000,
  "bid": 450.24,
  "ask": 450.26,
  "delta": 0.65,
  "open_interest": 5000,
  "tick_value": 850
}
```

**Response:**
```json
{
  "strategy_id": 1,
  "timestamp": "2024-01-15T10:35:00",
  "signals_generated": [
    {
      "type": "entry",
      "symbol": "SPY",
      "action": "buy",
      "confidence": 0.85,
      "reason": "Entry conditions met: ema, vwap, volume_ratio"
    }
  ],
  "orders_placed": [
    {
      "symbol": "SPY",
      "side": "buy",
      "qty": 2,
      "price": 450.26,
      "order_id": "abc123"
    }
  ],
  "positions_closed": [],
  "errors": []
}
```

#### Get Active Strategies
```http
GET /api/v1/execution/active-strategies
```
Lists all active strategies with execution status.

## 🔒 Paper vs Live Trading

The system automatically handles paper and live trading based on `user.selected_trading_mode`:

### Paper Trading
- **API:** Alpaca Paper Trading
- **Routing:** Automatic via `TradingClientManager`
- **Safeguards:**
  - Parameter validation
  - Simulated slippage (0.1%)
  - Simulated commissions ($0.65/contract)
  - Unrealistic expectation warnings

### Live Trading
- **API:** Schwab Live Trading
- **Routing:** Automatic via `TradingClientManager`
- **Safeguards:**
  - Confirmations required
  - Market hours check
  - Rate limiting (10 orders/min)
  - Account balance verification
  - Emergency stop mechanism
  - Paper/live mode mismatch prevention

**Mode Switching:**
```http
POST /api/v1/system/trading-mode
{
  "mode": "live"  # or "paper"
}
```

## 🚀 Getting Started

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Set Up Environment Variables
```bash
# Alpaca Paper Trading (for paper mode)
ALPACA_PAPER_API_KEY=your_key
ALPACA_PAPER_SECRET_KEY=your_secret

# Schwab Live Trading (for live mode)
SCHWAB_API_KEY=your_key
SCHWAB_API_SECRET=your_secret
SCHWAB_CALLBACK_URL=your_callback
```

### 3. Start the API
```bash
uvicorn api.app:app --reload
```

### 4. Start the Background Worker
```bash
python api/services/strategy_worker.py
```

Or integrate worker startup with FastAPI:
```python
# In app.py
from api.services.strategy_worker import start_worker, stop_worker

@app.on_event("startup")
async def startup_event():
    start_worker()

@app.on_event("shutdown")
async def shutdown_event():
    stop_worker()
```

### 5. Create and Activate a Strategy

1. Clone a strategy template:
```http
POST /api/v1/strategies/templates/spy_0dte_scalping/clone
```

2. Activate the strategy:
```http
PUT /api/v1/strategies/{strategy_id}
{
  "is_active": true
}
```

3. Start execution:
```http
POST /api/v1/execution/strategies/{strategy_id}/start
```

4. Monitor execution:
```http
GET /api/v1/execution/strategies/{strategy_id}/status
GET /api/v1/execution/strategies/{strategy_id}/risk-summary
```

## 📊 Monitoring

### Real-time Monitoring
- Check execution status: `GET /execution/strategies/{id}/status`
- View risk metrics: `GET /execution/strategies/{id}/risk-summary`
- Query trade history: `GET /trades?strategy_id={id}`
- View positions: `GET /positions?strategy_id={id}`

### Logs
The system logs all execution activity:
- Strategy ticks
- Signal generation
- Order placements
- Risk checks
- Errors and warnings

### Risk Events
All risk violations are logged to the database:
```http
GET /api/v1/risk-events?strategy_id={id}
```

## ⚠️ Important Notes

### Current Limitations

1. **Market Data:** Currently using mock data in `strategy_worker.py`
   - **TODO:** Implement real Alpaca WebSocket streaming
   - **TODO:** Add options data provider integration

2. **Options Support:** Framework supports options but needs:
   - Real options chain data
   - Greeks calculation
   - Options-specific order types

3. **Backtesting:** Not yet implemented
   - Strategy execution engine is ready
   - Need historical data replay functionality

### Production Recommendations

1. **Worker Deployment:**
   - For single-server: Use APScheduler (current)
   - For multi-server: Upgrade to Celery + Redis

2. **Market Data:**
   - Implement Alpaca WebSocket streaming
   - Add data caching layer (Redis)
   - Set up data quality monitoring

3. **Error Handling:**
   - Add Discord/Slack notifications
   - Implement retry logic with exponential backoff
   - Set up dead letter queue for failed orders

4. **Monitoring:**
   - Add Prometheus metrics
   - Set up Grafana dashboards
   - Configure alerts for critical events

5. **Database:**
   - Enable TimescaleDB hypertables for time-series data
   - Set up read replicas for analytics
   - Implement data retention policies

## 🧪 Testing

### Unit Testing
```bash
pytest api/tests/test_risk_manager.py
pytest api/tests/test_signal_generator.py
pytest api/tests/test_order_manager.py
```

### Integration Testing
```bash
# Test full execution flow
curl -X POST http://localhost:8000/api/v1/execution/strategies/1/execute-tick \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "SPY",
    "price": 450.25,
    "volume": 1000000,
    "bid": 450.24,
    "ask": 450.26
  }'
```

### Paper Trading Testing
1. Switch to paper mode
2. Activate a strategy
3. Start execution
4. Monitor for 1 hour
5. Review trades and P&L

## 📝 Next Steps

### Phase 1: Complete Integration
- [ ] Implement real market data streaming
- [ ] Connect Alpaca WebSocket to strategy worker
- [ ] Add options chain data provider
- [ ] Implement Greeks calculation

### Phase 2: Backtesting
- [ ] Build historical data replay engine
- [ ] Add backtesting endpoints
- [ ] Generate backtest reports
- [ ] Strategy optimization

### Phase 3: Production Hardening
- [ ] Add monitoring and alerting
- [ ] Implement retry mechanisms
- [ ] Set up multi-server deployment (Celery)
- [ ] Load testing and performance optimization

### Phase 4: Advanced Features
- [ ] Multi-leg options strategies
- [ ] Portfolio-level risk management
- [ ] Machine learning signal enhancement
- [ ] Advanced order types (stop-limit, brackets)

## 📚 Related Documentation

- [Strategy Templates](api/strategy_templates.py) - Pre-built 0DTE strategies
- [API Documentation](http://localhost:8000/docs) - FastAPI interactive docs
- [Database Models](api/models.py) - SQLAlchemy models
- [Trading Client Manager](api/engine/trading_client_manager.py) - Broker API integration

## 🆘 Support

For issues or questions:
1. Check logs in console output
2. Review risk events: `GET /api/v1/risk-events`
3. Check strategy status: `GET /api/v1/execution/strategies/{id}/status`
4. Verify trading mode: `GET /api/v1/system/environment`

---

**Status:** ✅ Core implementation complete - Ready for paper trading testing
