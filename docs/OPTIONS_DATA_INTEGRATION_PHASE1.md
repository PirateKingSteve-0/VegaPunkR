# Options Data Integration - Phase 1 Complete

## Overview

Phase 1 of the Options Data Integration has been completed, providing comprehensive real-time and historical options data capabilities including:

✅ **Websocket Handler Updates** - Capture delta, gamma, volume, OI in real-time
✅ **Option Chain Fetcher** - Advanced filtering and strike selection
✅ **Strike Selection Logic** - Delta-based contract selection with scoring

---

## Components

### 1. Enhanced Websocket Handler

**Files Modified:**
- `api/alpaca/data/live/websocket.py`
- `api/alpaca/data/live/option.py`
- `api/alpaca/data/models/snapshots.py`
- `api/alpaca/data/mappings.py`

**What Changed:**
- Added `snapshots` handler to base DataStream class
- Added `subscribe_snapshots()` and `unsubscribe_snapshots()` methods to OptionDataStream
- Enhanced OptionsSnapshot model to include `open_interest` field
- Added snapshot message type routing in websocket dispatcher

**Capabilities:**
- Real-time option greeks (delta, gamma, theta, vega, rho) via snapshot messages
- Implied volatility updates
- Volume tracking from trade messages
- Bid/ask updates from quote messages
- Open interest from snapshots (updated less frequently)

### 2. Real-time Options Aggregator

**File:** `api/services/market_data/options/realtime_aggregator.py`

**Features:**
- Aggregates real-time data from multiple websocket channels
- Tracks cumulative volume from trade messages
- Maintains current bid/ask from quote messages
- Updates greeks from snapshot messages
- Provides callback mechanism for data updates
- Thread-safe data access with async locks

**Usage Example:**
```python
from services.market_data.options.realtime_aggregator import RealtimeOptionsAggregator

async def data_callback(data):
    print(f"Delta: {data.delta}, Volume: {data.volume}")

aggregator = RealtimeOptionsAggregator(
    api_key=api_key,
    secret_key=secret_key,
    data_callback=data_callback
)

await aggregator.start()
await aggregator.subscribe("SPY250117C00590000")
```

### 3. Enhanced Option Chain Fetcher

**File:** `api/services/market_data/options/chain_fetcher.py`

**Features:**
- Fetch complete option chains for any underlying
- Advanced filtering by:
  - Delta range (min/max/target)
  - Open interest
  - Bid-ask spread
  - Implied volatility
  - Strike price
  - Option type (call/put/both)
- Intelligent contract scoring algorithm
- 0DTE contract detection
- Comprehensive caching (5-minute TTL by default)
- OCC symbol parsing

**Usage Example:**
```python
from services.market_data.options.chain_fetcher import OptionChainFetcher, OptionType

fetcher = OptionChainFetcher(api_key, secret_key)

# Simple selection
contract = fetcher.select_best_contract(
    underlying="SPY",
    delta_min=0.60,
    delta_max=0.85,
    min_open_interest=3000,
    option_type=OptionType.CALL
)

# Get 0DTE contracts
dte_contracts = fetcher.get_0dte_contracts(
    underlying="SPY",
    delta_min=0.65,
    delta_max=0.75
)
```

### 4. Strike Selection Logic

**Location:** `api/services/market_data/options/chain_fetcher.py` (OptionChainFetcher class)

**Algorithm:**

The strike selection uses a multi-factor scoring system:

1. **Delta Matching** (0-1.0 points)
   - Prefers contracts closer to target delta (middle of range)
   - Normalized distance from target

2. **Open Interest** (0-0.5 points)
   - Higher OI = better liquidity
   - Max bonus at 100,000 OI

3. **Bid-Ask Spread** (0-0.3 points)
   - Tighter spreads preferred
   - Penalizes wide markets

4. **Implied Volatility** (0-0.2 points)
   - Rewards reasonable IV (0.2-0.8)
   - Avoids extreme IV values

**Total Score:** 0-2.0 points (higher is better)

### 5. Data Models

**RealtimeOptionData:**
```python
@dataclass
class RealtimeOptionData:
    symbol: str
    timestamp: datetime

    # Pricing
    bid: Optional[float]
    ask: Optional[float]
    last_price: Optional[float]

    # Greeks
    delta: Optional[float]
    gamma: Optional[float]
    theta: Optional[float]
    vega: Optional[float]
    rho: Optional[float]

    # Volume & Interest
    volume: int  # Aggregated from trades
    trade_count: int
    open_interest: Optional[int]

    # Volatility
    implied_volatility: Optional[float]
```

**SelectedContract:**
```python
@dataclass
class SelectedContract:
    symbol: str
    snapshot: OptionsSnapshot
    score: float

    underlying: str
    strike: float
    expiration: date
    option_type: str

    # All greeks + IV + OI + pricing
```

---

## Integration with Existing Code

### Strategy Execution

The existing `api/services/market_data/options/service.py` already uses option chain fetching and strike selection. The new components provide:

1. **Enhanced real-time capabilities** via `realtime_aggregator.py`
2. **More advanced filtering** via `chain_fetcher.py`
3. **Better contract scoring** with multi-factor algorithm

### Migration Path

**Option 1:** Keep existing implementation, use new components for new features

**Option 2:** Gradually migrate to new chain_fetcher:
```python
# Old way (existing)
from services.market_data.options.service import OptionsMarketDataService
service = OptionsMarketDataService()
contract = await service.select_contract(underlying, params)

# New way (enhanced)
from services.market_data.options.chain_fetcher import OptionChainFetcher
fetcher = OptionChainFetcher(api_key, secret_key)
contract = fetcher.select_best_contract(
    underlying=underlying,
    delta_min=params['delta_min'],
    delta_max=params['delta_max'],
    min_open_interest=params['min_open_interest']
)
```

---

## Data Sources

### Real-time Data (Websocket)
- **Trades:** Price, size (for volume aggregation)
- **Quotes:** Bid, ask, bid_size, ask_size
- **Snapshots:** Greeks, IV, latest trade/quote

### Historical Data (REST API)
- **Option Chain:** All contracts for underlying
- **Snapshots:** Current state with greeks
- **Bars:** OHLCV historical data
- **Open Interest:** Updated daily (not real-time)

---

## Caching Strategy

### Chain Fetcher
- **Option chains:** 5 minutes TTL
- **Contract selections:** 5 minutes TTL
- **Configurable:** Pass `cache_ttl_seconds` to constructor

### Real-time Aggregator
- **No caching:** Always current data
- **In-memory state:** Per-symbol aggregation

---

## Performance Considerations

1. **Websocket overhead:** Minimal - event-driven
2. **Volume aggregation:** O(1) per trade message
3. **Chain fetching:** Cached to reduce API calls
4. **Filtering:** O(n) where n = contracts in chain (~100-500)
5. **Memory:** ~1KB per tracked symbol in aggregator

---

## Example Usage

See `api/services/market_data/options/example_usage.py` for complete examples:

1. **Real-time streaming** with callbacks
2. **Option chain fetching** with various filters
3. **Combined usage** for strategy execution
4. **Open interest updates** (periodic)

---

## Testing

To test the implementation:

```bash
# Test chain fetching
cd api
python -c "
from services.market_data.options.chain_fetcher import OptionChainFetcher
from config import settings
fetcher = OptionChainFetcher(settings.ALPACA_PAPER_API_KEY, settings.ALPACA_PAPER_SECRET_KEY)
contract = fetcher.select_best_contract('SPY', delta_min=0.6, delta_max=0.8)
print(contract.to_dict() if contract else 'No contract found')
"

# Test real-time aggregator (run for 30 seconds)
cd api
python services/market_data/options/example_usage.py
```

---

## Next Steps (Phase 2+)

Potential enhancements:

- [ ] Greeks calculation/verification
- [ ] Volatility surface construction
- [ ] Multi-leg strategy support (spreads, iron condors)
- [ ] Historical greeks data storage
- [ ] ML-based contract selection
- [ ] Risk metrics (position greeks aggregation)

---

## API Reference

### OptionChainFetcher

```python
OptionChainFetcher(api_key: str, secret_key: str, cache_ttl_seconds: int = 300)

Methods:
  - get_chain(underlying, expiration_date, use_cache) -> Dict[str, OptionsSnapshot]
  - get_filtered_chain(underlying, expiration_date, strike_filter, use_cache) -> List[SelectedContract]
  - select_best_contract(underlying, expiration_date, delta_min, delta_max, ...) -> Optional[SelectedContract]
  - get_0dte_contracts(underlying, delta_min, delta_max, min_open_interest) -> List[SelectedContract]
  - clear_cache()
```

### RealtimeOptionsAggregator

```python
RealtimeOptionsAggregator(api_key, secret_key, feed, data_callback)

Methods:
  - start() -> None
  - stop() -> None
  - subscribe(*symbols) -> None
  - unsubscribe(*symbols) -> None
  - get_data(symbol) -> Optional[RealtimeOptionData]
  - get_all_data() -> Dict[str, RealtimeOptionData]
  - set_open_interest(symbol, open_interest) -> None
```

---

## Summary of Files

### New Files Created:
1. `api/services/market_data/options/realtime_aggregator.py` - Real-time data aggregation
2. `api/services/market_data/options/chain_fetcher.py` - Enhanced chain fetching and filtering
3. `api/services/market_data/options/example_usage.py` - Usage examples
4. `docs/OPTIONS_DATA_INTEGRATION_PHASE1.md` - This documentation

### Modified Files:
1. `api/alpaca/data/live/websocket.py` - Added snapshot handler support
2. `api/alpaca/data/live/option.py` - Added subscribe_snapshots method
3. `api/alpaca/data/models/snapshots.py` - Added open_interest field
4. `api/alpaca/data/mappings.py` - Added openInterest mapping

---

## Questions?

For issues or questions about the options data integration, please refer to:
- Alpaca Options API Docs: https://docs.alpaca.markets/docs/options-data
- This documentation
- Example usage file: `api/services/market_data/options/example_usage.py`
