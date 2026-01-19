"""
Integration test - verify enhanced service works with strategy_worker
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from database import SessionLocal
from models import Strategy, User
from services.strategy_worker import StrategyWorker


async def test_enhanced_integration():
    """Test that enhanced service is integrated correctly."""

    print("=" * 70)
    print("  INTEGRATION TEST - Enhanced Options Service")
    print("=" * 70)

    db = SessionLocal()

    try:
        # Get a test strategy
        strategy = db.query(Strategy).filter(
            Strategy.is_active == True
        ).first()

        if not strategy:
            print("\n⚠️  No active strategy found")
            print("   Create an active strategy first to test")
            return

        print(f"\n📊 Testing with Strategy: {strategy.name} (ID: {strategy.id})")
        print(f"   Instruments: {strategy.instruments}")
        print(f"   Asset Type: {strategy.params_json.get('asset_type', 'options')}")

        # Create worker instance
        worker = StrategyWorker()

        print("\n🔍 Fetching market data...")

        # Get user
        user = db.query(User).filter(User.id == strategy.user_id).first()

        if not user:
            print("❌ User not found")
            return

        # Get first instrument
        symbol = strategy.instruments[0] if strategy.instruments else "SPY"

        # Fetch market data using new enhanced service
        market_data = await worker._fetch_market_data(user, symbol, strategy)

        if market_data:
            print("✅ Market data fetched successfully!")
            print(f"\n📈 Results:")
            print(f"   Contract: {market_data.get('symbol')}")
            print(f"   Price: ${market_data.get('price', 0):.2f}")
            print(f"   Delta: {market_data.get('delta', 0):.4f}")
            print(f"   Gamma: {market_data.get('gamma', 0):.4f}")
            print(f"   Open Interest: {market_data.get('open_interest', 'N/A')}")
            print(f"   Data Source: {market_data.get('data_source', 'unknown')}")

            # Verify it's using the enhanced service
            source = market_data.get('data_source')
            if source in ['rest', 'realtime']:
                print(f"\n✅ SUCCESS! Using enhanced service (source: {source})")
                return True
            else:
                print(f"\n⚠️  Warning: Unexpected data source: {source}")
                return False
        else:
            print("❌ No market data returned")
            print("   This may be normal if market is closed")
            return False

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        db.close()
        print("\n" + "=" * 70)


if __name__ == "__main__":
    print("\nRunning worker integration test...\n")
    result = asyncio.run(test_enhanced_integration())
    sys.exit(0 if result else 1)
