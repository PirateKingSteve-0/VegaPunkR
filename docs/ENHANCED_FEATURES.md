# Enhanced Alpaca API Features

New utilities added to improve your Alpaca integration with market hours detection and multi-streaming capabilities.

## New Features

### 1. Market Hours Detection

Automatically detect US market hours and determine which streams are available.

**Location:** [utils/market_hours.py](utils/market_hours.py)

**Features:**
- Timezone-aware detection (handles EDT/EST)
- Holiday detection (2024-2025)
- Weekend detection
- Pre-market/after-hours detection
- Simple API for stream availability

**Quick Usage:**

```python
from utils.market_hours import is_market_open, get_market_status, get_available_streams

# Simple check
if is_market_open():
    print("Markets are open!")

# Detailed status
status = get_market_status()
print(f"Current ET time: {status['current_time_et']}")
print(f"Message: {status['message']}")

# Check which streams are available
available = get_available_streams()
print(f"Can stream stocks: {available['stocks']}")
print(f"Can stream options: {available['options']}")
print(f"Can stream crypto: {available['crypto']}")  # Always True
print(f"Can stream news: {available['news']}")      # Always True
```

**Test it:**
```bash
cd api
python test_market_hours.py
```

---

### 2. Multi-Stream Manager

Stream data from multiple Alpaca feeds simultaneously using async/await.

**Location:** [utils/multi_stream.py](utils/multi_stream.py)

**Features:**
- Simultaneous streaming from stocks, crypto, news, and options
- Market-hours aware (automatically disables stock/options when closed)
- Built on official Alpaca SDK (async/await)
- Auto-stop when data received from all streams
- Track latest prices across all assets
- Clean summary reports

**Quick Usage:**

```python
import asyncio
from utils.multi_stream import stream_all_markets
from alpaca.data.enums import OptionsFeed

async def main():
    await stream_all_markets(
        api_key="your_key",
        secret_key="your_secret",
        stock_symbols=["AAPL", "MSFT"],
        crypto_symbols=["BTC/USD", "ETH/USD"],
        news_symbols=["*"],  # All news
        option_symbols=["AAPL251219C00230000"],
        auto_stop=True  # Stop after receiving data from all
    )

asyncio.run(main())
```

**Advanced Usage:**

```python
import asyncio
from utils.multi_stream import MultiStreamManager
from alpaca.data.enums import OptionsFeed

async def main():
    manager = MultiStreamManager(
        api_key="your_key",
        secret_key="your_secret",
        options_feed=OptionsFeed.INDICATIVE
    )

    await manager.start_streams(
        stock_symbols=["AAPL", "MSFT", "GOOGL"],
        crypto_symbols=["BTC/USD", "ETH/USD", "DOGE/USD"],
        news_symbols=["AAPL", "MSFT"],
        option_symbols=["AAPL251219C00230000"],
        auto_stop_on_data=False  # Stream continuously
    )

    # Access data
    print(f"Latest prices: {manager.latest_prices}")
    print(f"Message counts: {manager.message_counts}")

asyncio.run(main())
```

**Test it:**
```bash
cd api
python test_multi_stream.py
```

---

## Integration with Existing Code

### Update your existing test.py

You can enhance your existing [test.py](test.py) with market hours awareness:

```python
import asyncio
import os
from dotenv import load_dotenv
from alpaca.data.live import OptionDataStream
from alpaca.data.enums import OptionsFeed
from utils.market_hours import is_market_open, get_market_status

load_dotenv()

async def main():
    # Check market status first
    status = get_market_status()
    print(f"Market Status: {status['message']}")

    if not is_market_open():
        print("Warning: Markets are closed. Option data may be limited.")
        print("Consider using crypto/news streams instead.")

    # Continue with your existing code
    stream = OptionDataStream(
        api_key=os.getenv("ALPACA_PAPER_API_KEY"),
        secret_key=os.getenv("ALPACA_PAPER_SECRET_KEY"),
        feed=OptionsFeed.INDICATIVE,
        raw_data=False
    )
    # ... rest of your code
```

---

## Dependencies

Add to your requirements.txt (if not already present):

```txt
pytz>=2023.3
```

Install:
```bash
pip install pytz
```

---

## File Structure

```
api/
├── utils/
│   ├── __init__.py              # Package exports
│   ├── market_hours.py          # Market hours detection
│   └── multi_stream.py          # Multi-stream manager
├── test_market_hours.py         # Market hours test
├── test_multi_stream.py         # Multi-stream test
├── test.py                      # Your existing option stream test
└── ENHANCED_FEATURES.md         # This file
```

---

## Key Differences from alpaca-data-main

Our implementation is **better** because:

1. **Built on Official SDK**: Uses official `alpaca-py` async WebSocket streams
2. **True Async/Await**: No threading, cleaner and more efficient
3. **Type Safety**: Works with Pydantic models from Alpaca SDK
4. **Production Ready**: Professional error handling and reconnection logic
5. **Simpler**: Less code, easier to understand and maintain

vs. `alpaca-data-main` which:
- Uses threading and `websocket-client` (older approach)
- Custom wrapper around official SDK (extra layer)
- Dictionary-based data (no type safety)

---

## Examples

### Example 1: Check Market Hours Before Streaming

```python
from utils.market_hours import is_market_open, get_available_streams

available = get_available_streams()

if available['stocks']:
    # Start stock stream
    pass

if available['options']:
    # Start options stream
    pass

# Crypto and news are always available
# Start crypto stream
# Start news stream
```

### Example 2: Multi-Stream with Auto-Stop

```python
import asyncio
from utils.multi_stream import stream_all_markets

# This will stream until data is received from all available streams
async def main():
    await stream_all_markets(
        api_key="...",
        secret_key="...",
        stock_symbols=["AAPL"],
        crypto_symbols=["BTC/USD"],
        news_symbols=["*"],
        option_symbols=["AAPL251219C00230000"],
        auto_stop=True
    )

asyncio.run(main())
```

### Example 3: Continuous Multi-Stream

```python
import asyncio
from utils.multi_stream import MultiStreamManager

async def main():
    manager = MultiStreamManager(api_key="...", secret_key="...")

    # Stream continuously until Ctrl+C
    await manager.start_streams(
        crypto_symbols=["BTC/USD", "ETH/USD"],
        news_symbols=["*"],
        auto_stop_on_data=False
    )

asyncio.run(main())
```

---

## Testing

Run all tests:

```bash
# Test market hours detection
python api/test_market_hours.py

# Test multi-streaming (interactive menu)
python api/test_multi_stream.py

# Test your original options stream
python api/test.py
```

---

## Next Steps

1. **Try the market hours test:** `python api/test_market_hours.py`
2. **Try multi-streaming:** `python api/test_multi_stream.py`
3. **Integrate into your code:** Use the examples above
4. **Optional:** Delete `alpaca-data-main` directory (no longer needed)

---

## Notes

- **Market hours:** 9:30 AM - 4:00 PM ET, Monday-Friday (excluding holidays)
- **Crypto/News:** Available 24/7
- **Options feed:** INDICATIVE (free) vs OPRA (paid subscription required)
- **Auto-stop:** Useful for testing, disable for production monitoring

---

## Support

- Official Alpaca docs: https://docs.alpaca.markets/
- Your existing files: [test.py](test.py), [README.md](README.md), [NEWS_WEBSOCKET_README.md](NEWS_WEBSOCKET_README.md)
