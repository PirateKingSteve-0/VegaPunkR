import asyncio
import os
import logging
from typing import Dict, Union
from dotenv import load_dotenv

from alpaca.data.live import NewsDataStream
from alpaca.data.models.news import News

# Enable logging to see what's happening
logging.basicConfig(level=logging.DEBUG)

# Load environment variables
load_dotenv()

async def news_handler(data: Union[News, Dict]):
    # Handle news: e.g., log, analyze sentiment, or insert to database
    if isinstance(data, News):
        print(f"\n{'='*80}")
        print(f"News ID: {data.id}")
        print(f"Headline: {data.headline}")
        print(f"Source: {data.source}")
        print(f"Author: {data.author}")
        print(f"Symbols: {', '.join(data.symbols)}")
        print(f"Created: {data.created_at}")
        print(f"Summary: {data.summary[:200]}...")
        print(f"URL: {data.url}")
        print(f"{'='*80}\n")
    else:
        print(f"Received raw news data: {data}")

async def main():
    print("Starting Alpaca news data stream test...")
    print("=" * 80)
    print("IMPORTANT: News data requires a paid subscription to Alpaca's data feed.")
    print("Error code 402 means 'subscription required' - news is not available in free tier.")
    print("=" * 80)
    print(f"API Key: {os.getenv('ALPACA_PAPER_API_KEY')[:8]}...")

    # Init stream for news
    # NOTE: News websocket requires a paid subscription
    # Set paper=True to use sandbox environment (requires sandbox subscription)
    # Set paper=False to use production environment (requires live subscription)
    stream = NewsDataStream(
        api_key=os.getenv("ALPACA_PAPER_API_KEY"),
        secret_key=os.getenv("ALPACA_PAPER_SECRET_KEY"),
        raw_data=False,  # Use models for structured data
        paper=True  # Use sandbox environment for paper trading
    )

    print("Stream object created successfully")

    # Subscribe to news for specific symbols
    # You can use "*" to get all news, or specify symbols like "AAPL", "TSLA", etc.
    symbols = ["AAPL", "TSLA", "NVDA", "MSFT"]  # Or use "*" for all news
    print(f"Subscribing to news for: {', '.join(symbols)}...")
    stream.subscribe_news(news_handler, *symbols)

    print("Connecting to Alpaca news websocket...")
    print("Press Ctrl+C to stop")

    # Run forever (in prod, integrate with FastAPI lifespan or Rust Tokio loop)
    try:
        # Use _run_forever() since we're already in an async context
        await stream._run_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        await stream.close()
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        await stream.close()

if __name__ == "__main__":
    asyncio.run(main())
