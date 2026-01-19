# Alpaca News WebSocket Implementation

## Overview

The news websocket is **fully implemented and working**. The implementation provides real-time streaming of market news from Alpaca's news feed.

## Implementation Files

- **[api/alpaca/data/live/news.py](api/alpaca/data/live/news.py)** - NewsDataStream class
- **[api/alpaca/data/models/news.py](api/alpaca/data/models/news.py)** - News data models
- **[api/test_news.py](api/test_news.py)** - Example usage and test file

## Requirements

**IMPORTANT**: News data requires a **paid subscription** to Alpaca's data feed.

- Error code 402 = "subscription required"
- News is NOT available in the free tier
- Both sandbox and production environments require a subscription

## Usage

```python
from alpaca.data.live import NewsDataStream
from alpaca.data.models.news import News

async def news_handler(data: News):
    print(f"Headline: {data.headline}")
    print(f"Source: {data.source}")
    print(f"Symbols: {', '.join(data.symbols)}")
    print(f"Summary: {data.summary}")

stream = NewsDataStream(
    api_key="your_api_key",
    secret_key="your_secret_key",
    paper=True,  # Use sandbox or production
    raw_data=False  # Return parsed News objects
)

# Subscribe to news for specific symbols
stream.subscribe_news(news_handler, "AAPL", "TSLA", "NVDA")

# Or subscribe to ALL news
stream.subscribe_news(news_handler, "*")

# Run the stream
await stream._run_forever()
```

## Available Methods

### `subscribe_news(handler, *symbols)`
Subscribe to news for specific symbols or "*" for all news.

**Parameters:**
- `handler`: Async callback function that receives News objects
- `*symbols`: Ticker symbols to subscribe to, or "*" for all

### `unsubscribe_news(*symbols)`
Unsubscribe from news for specific symbols.

**Parameters:**
- `*symbols`: Ticker symbols to unsubscribe from

## News Data Model

```python
class News:
    id: int                    # News article ID
    headline: str              # Headline/title
    source: str                # Source (e.g. "Benzinga")
    author: str                # Article author
    summary: str               # Summary text
    content: str               # Full content (may contain HTML)
    url: Optional[str]         # Article URL
    symbols: List[str]         # Related ticker symbols
    created_at: datetime       # Creation timestamp
    updated_at: datetime       # Last update timestamp
```

## WebSocket Endpoints

- **Production**: `wss://stream.data.alpaca.markets/v1beta1/news`
- **Sandbox**: `wss://stream.data.sandbox.alpaca.markets/v1beta1/news`

The endpoint is automatically selected based on the `paper` parameter:
- `paper=True` → Uses sandbox endpoint
- `paper=False` → Uses production endpoint

## Testing

To test the news websocket:

```bash
cd api
python3 test_news.py
```

**Note**: You will receive a 402 error if you don't have a paid news subscription.

## Integration with Your Project

The news websocket follows the same pattern as the stock/crypto/option websockets:

1. Create a `NewsDataStream` instance
2. Subscribe to news with a handler function
3. Run the stream with `stream.run()` or `await stream._run_forever()`
4. Process incoming news in your handler

You can integrate this into:
- FastAPI lifespan events
- Background tasks
- Rust Tokio async runtime (via FFI)
- TimescaleDB for storage
- Polars for analysis

## Subscription Required

If you see this error:
```
ERROR:alpaca.data.live.websocket:Auth error: auth failed (code: 402)
```

This means you need to:
1. Subscribe to Alpaca's news data feed
2. Use API keys that have news access enabled
3. Contact Alpaca support to enable news on your account

## Next Steps

The implementation is complete and ready to use. To actually receive news data, you'll need to:

1. **Upgrade your Alpaca account** to include news data access
2. **Update your API keys** if needed (ensure they have news permissions)
3. **Configure the stream** with the appropriate `paper` parameter
4. **Integrate** with your trading/analysis pipeline
