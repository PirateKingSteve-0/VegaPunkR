# Alpaca Options Data Streaming Setup

## Overview
This directory contains the official Alpaca SDK integration with enhanced utilities for:
- Real-time websocket streaming (stocks, options, crypto, news)
- Historical data retrieval
- **NEW:** Market hours detection with timezone awareness
- **NEW:** Multi-stream manager for simultaneous connections

See [ENHANCED_FEATURES.md](ENHANCED_FEATURES.md) for detailed documentation on new features.

## Environment Setup

### 1. Environment Variables
All API credentials are stored in `.env` (already in `.gitignore`):

```bash
# Alpaca API Keys (Paper Trading)
ALPACA_PAPER_API_KEY=your_key_here
ALPACA_PAPER_SECRET_KEY=your_secret_here

# Environment Mode: paper, live, or sandbox
ALPACA_ENV=paper
```

### 2. Available Endpoints

| Type | Environment | Endpoint |
|------|-------------|----------|
| Market Data Stream | Live | `wss://stream.data.alpaca.markets` |
| Trading Stream | Paper | `wss://paper-api.alpaca.markets/stream` |
| Trading Stream | Live | `wss://api.alpaca.markets/stream` |
| Historical Data | All | `https://data.alpaca.markets` |

## Rate Limits

**WebSocket Limits:**
- **1 concurrent connection** per account
- Connection limit exceeded = HTTP 429 error
- Must close existing connections before opening new ones

**API Limits (Paper Trading):**
- 200 requests/minute
- 10 requests/second (burst)

## Quick Start

### New Features (Enhanced)

**Market Hours Detection:**
```bash
python3 test_market_hours.py
```

**Multi-Stream Manager:**
```bash
python3 test_multi_stream.py
```

**Enhanced Options Stream (with market hours check):**
```bash
python3 test_enhanced.py
```

## Scripts

### `test.py` - Real-time WebSocket Streaming
Connects to live options data stream (only works during market hours).

```bash
python3 api/test.py
```

**When it works:**
- Monday-Friday: 9:30 AM - 4:00 PM ET
- During pre-market/after-hours (limited data)

**When it doesn't work:**
- Weekends
- Market holidays
- Outside trading hours (no data will stream, but connection stays open)

**Expected behavior when markets are closed:**
- Connection established ✓
- No data streaming (normal - wait for market hours)

### `test_historical.py` - Historical Data Retrieval
Fetches historical options data (works anytime, even when markets are closed).

```bash
python3 api/test_historical.py
```

**Use this to:**
- Verify API credentials
- Test data access outside market hours
- Get snapshots of latest option prices

### `kill_connections.sh` - Connection Management
Kills all running websocket connections.

```bash
./api/kill_connections.sh
```

**When to use:**
- Hit connection limit (429 error)
- Need to restart websocket
- Multiple test processes running

## Common Issues

### 1. "connection limit exceeded"
**Cause:** Already have 1 active websocket connection
**Solution:**
```bash
./api/kill_connections.sh
# Wait 30-60 seconds
python3 api/test.py
```

### 2. "No data streaming"
**Cause:** Markets are closed or no trades/quotes for subscribed symbols
**Solution:**
- Check market hours (M-F 9:30 AM - 4:00 PM ET)
- Use `test_historical.py` to verify API works
- Subscribe to more active option contracts

### 3. "invalid syntax (400)"
**Cause:** Invalid option symbol format
**Solution:** Use correct OCC format:
- Format: `SYMBOL` + `YYMMDD` + `C/P` + `Strike Price (8 digits)`
- Example: `AAPL250117C00150000` = AAPL Jan 17, 2025 $150 Call

## Option Symbol Format

```
AAPL 25 01 17 C 00150000
 │    │  │  │  │    │
 │    │  │  │  │    └─ Strike: $150.00 (8 digits, implied decimal)
 │    │  │  │  └────── Type: C=Call, P=Put
 │    │  │  └───────── Day: 17
 │    │  └──────────── Month: 01 (January)
 │    └─────────────── Year: 25 (2025)
 └──────────────────── Symbol: AAPL
```

## Feed Types

| Feed | Description | Cost | Data Quality |
|------|-------------|------|--------------|
| `INDICATIVE` | Delayed/indicative quotes | Free | Good for testing |
| `OPRA` | Real-time OPRA feed | Paid subscription | Production quality |

Default: `INDICATIVE` (set in `test.py`)

## Next Steps

1. **Test during market hours** (Monday 9:30 AM ET):
   ```bash
   python3 api/test.py
   ```

2. **For production**, consider:
   - Upgrading to OPRA feed for real-time data
   - Implementing reconnection logic
   - Adding data persistence (TimescaleDB)
   - Integrating with FastAPI/Rust services

3. **Subscribe to different symbols**:
   Edit `test.py` line 43-44 to change subscribed options

## Documentation
- [Alpaca Options Data Docs](https://docs.alpaca.markets/docs/options-data)
- [WebSocket API Reference](https://docs.alpaca.markets/docs/websocket-streaming)
- [Rate Limits](https://alpaca.markets/support/usage-limit-api-calls)
