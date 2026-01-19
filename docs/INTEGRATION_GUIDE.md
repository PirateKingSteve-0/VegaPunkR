# Integration Guide - Enhanced Options Data

Quick guide to integrate Phase 1 options components with your strategy execution.

## Quick Start (1 Line Change!)

In `services/strategy_worker.py`, replace:

```python
# OLD:
from api.services.market_data.options import get_options_market_data_service
options_service = get_options_market_data_service()

# NEW:
from services.market_data.options.enhanced_service import get_enhanced_options_service  
options_service = get_enhanced_options_service(enable_realtime=False)
```

Done! You now have enhanced contract selection.

## Full Integration

See the comprehensive integration code in:
- `api/services/market_data/options/enhanced_service.py` - Drop-in service
- `api/services/market_data/options/example_usage.py` - Usage examples  
- `api/tests/test_options_integration.py` - Test suite

## Enable Real-time (Optional)

When ready for websocket streaming:

```python
# Change to True
options_service = get_enhanced_options_service(enable_realtime=True)
```

## Test It

```bash
cd api
python tests/quick_test_options.py
```

For detailed docs, see [OPTIONS_DATA_INTEGRATION_PHASE1.md](./OPTIONS_DATA_INTEGRATION_PHASE1.md)
