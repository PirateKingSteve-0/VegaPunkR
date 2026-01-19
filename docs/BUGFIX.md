# Bug Fix: Async Handler Functions

## Issue
The multi-stream manager was throwing an error:
```
ValueError: handler must be a coroutine function
```

## Root Cause
The Alpaca SDK requires all WebSocket handlers to be **async coroutine functions** (defined with `async def`), but the initial implementation used lambda functions which are regular (synchronous) functions.

## Solution
Changed all handler subscriptions from:
```python
# ❌ WRONG - Lambda is not async
self.crypto_stream.subscribe_trades(
    lambda trade: self._handle_trade(trade, 'crypto'),
    *symbols
)
```

To:
```python
# ✅ CORRECT - Proper async handler
async def trade_handler(trade):
    await self._handle_trade(trade, 'crypto')

self.crypto_stream.subscribe_trades(trade_handler, *symbols)
```

## Files Fixed
- [api/utils/multi_stream.py](utils/multi_stream.py)
  - `_run_stock_stream()` - Fixed trade and quote handlers
  - `_run_crypto_stream()` - Fixed trade and quote handlers
  - `_run_news_stream()` - Fixed news handler
  - `_run_option_stream()` - Fixed trade and quote handlers

## Status
✅ **FIXED** - All handlers are now proper async coroutine functions

## Testing
Run the multi-stream test to verify:
```bash
cd api
python3 test_multi_stream.py
# Choose option 2 (Convenience function)
```

The streams should now connect successfully without the "handler must be a coroutine function" error.

## Note for Future Development
When working with the Alpaca SDK's WebSocket streams, **always** use async handlers:
```python
# Pattern to follow
async def my_handler(data):
    # Your async code here
    await some_async_operation(data)

stream.subscribe_trades(my_handler, "SYMBOL")
```
