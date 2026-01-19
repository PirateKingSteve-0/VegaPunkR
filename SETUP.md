# VegaPunkR Setup Guide

## Prerequisites

- Python 3.13+ (for schwab-py support)
- PostgreSQL (for database)
- API Keys: Alpaca Paper Trading, Alpaca Live (optional), Schwab (optional)

## Installation

### 1. Create Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate  # On Unix/MacOS
```

### 2. Install Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Create a `.env` file in the project root:

```env
# Alpaca API Keys
ALPACA_PAPER_API_KEY=your_paper_api_key_here
ALPACA_PAPER_SECRET_KEY=your_paper_secret_key_here
ALPACA_LIVE_API_KEY_ID=your_live_api_key_here  # Optional
ALPACA_LIVE_API_SECRET_KEY=your_live_secret_key_here  # Optional

# Database URLs
DATABASE_DEV_URL=postgresql://user:password@localhost/vegapunkr_dev
DATABASE_TEST_URL=postgresql://user:password@localhost/vegapunkr_test
DATABASE_PROD_URL=postgresql://user:password@localhost/vegapunkr_prod

# Schwab API (Optional - requires Python 3.10+)
APP_KEY=your_schwab_app_key
APP_SECRET=your_schwab_app_secret
CALLBACK_URL=http://localhost:8080/callback
TOKEN_PATH=./schwab_token.json
```

## Running Tests

### Websocket Streaming Tests

**Important:** Stock/Options/News streams require a paid Alpaca subscription. Crypto streams work with free accounts.

```bash
# Activate virtual environment
source venv/bin/activate

# Run quick multi-stream test (10 seconds)
cd api/tests
python test_quick_multi.py

# Run full multi-stream test with options
python test_multi_stream.py

# Test options streaming (requires paid subscription)
python test_multiple_symbols.py
```

### Alternative: Using PYTHONPATH

```bash
# From project root
PYTHONPATH=api python3 api/tests/test_quick_multi.py
```

## Troubleshooting

### ModuleNotFoundError: No module named 'pytz'

Make sure you're using the virtual environment:
```bash
source venv/bin/activate
pip install -r requirements.txt
```

### Auth Error (Code 402)

This means the stream requires a paid Alpaca subscription:
- **Works with free account:** Crypto streams
- **Requires paid subscription:** Stock, Options, News streams

### Wrong Python Version

Check your Python version:
```bash
python --version  # Should be 3.13+
```

If needed, create venv with specific version:
```bash
/usr/local/bin/python3.13 -m venv venv
```

## Project Structure

```
VegaPunkR/
├── api/
│   ├── engine/          # Strategy execution engine (Phase 1)
│   ├── alpaca/          # Alpaca SDK (bundled)
│   ├── utils/           # Utilities (market hours, streaming)
│   ├── tests/           # Test scripts
│   ├── models.py        # Database models
│   ├── config.py        # Configuration
│   └── database.py      # Database connection
├── docker/              # Docker setup
├── ui/                  # Frontend (Angular)
├── requirements.txt     # Python dependencies
├── .env                 # Environment variables (create this)
└── venv/                # Virtual environment (git ignored)
```

## Next Steps

1. Set up PostgreSQL database
2. Run database migrations with Alembic
3. Start implementing Phase 1: Strategy Execution Engine
4. Test with paper trading account
