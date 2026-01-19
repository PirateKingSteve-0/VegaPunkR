"""
Test script to verify new API endpoints are properly configured.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app


def test_app_loads():
    """Test that the app loads successfully."""
    assert app is not None
    print("✓ App loads successfully")


def test_routes_exist():
    """Verify all expected routes are registered."""
    routes = [route.path for route in app.routes]

    # Positions endpoints
    assert "/api/v1/positions" in routes
    assert "/api/v1/positions/{position_id}" in routes
    assert "/api/v1/positions/summary/overview" in routes
    print("✓ Positions endpoints registered")

    # Trades endpoints
    assert "/api/v1/trades" in routes
    assert "/api/v1/trades/{trade_id}" in routes
    assert "/api/v1/trades/{trade_id}/close" in routes
    assert "/api/v1/trades/summary/stats" in routes
    print("✓ Trades endpoints registered")

    # Performance endpoints
    assert "/api/v1/performance" in routes
    assert "/api/v1/performance/{metrics_id}" in routes
    assert "/api/v1/performance/calculate/{strategy_id}" in routes
    assert "/api/v1/performance/summary/{strategy_id}" in routes
    print("✓ Performance endpoints registered")

    # Risk events endpoints
    assert "/api/v1/risk-events" in routes
    assert "/api/v1/risk-events/{event_id}" in routes
    assert "/api/v1/risk-events/summary/stats" in routes
    assert "/api/v1/risk-events/summary/alerts" in routes
    print("✓ Risk events endpoints registered")


def test_openapi_schema():
    """Verify OpenAPI schema is properly configured."""
    openapi_schema = app.openapi()

    # Check paths exist
    paths = openapi_schema.get("paths", {})
    assert len(paths) > 0

    # Check that new endpoints are in the schema
    new_paths = [p for p in paths.keys() if any(x in p for x in ['/positions', '/trades', '/performance', '/risk-events'])]
    assert len(new_paths) >= 15, f"Expected at least 15 new endpoints, found {len(new_paths)}"

    print("✓ OpenAPI schema properly configured")


if __name__ == "__main__":
    print("\n=== Testing New API Endpoints ===\n")

    try:
        test_app_loads()
        test_routes_exist()
        test_openapi_schema()

        print("\n✅ All tests passed! New endpoints are properly configured.\n")

        # Print summary
        routes = [route.path for route in app.routes]
        new_endpoints = [r for r in routes if any(x in r for x in ['/positions', '/trades', '/performance', '/risk-events'])]

        print(f"Total new endpoints added: {len(new_endpoints)}")
        print("\nEndpoint breakdown:")
        print(f"  - Positions: {len([p for p in new_endpoints if '/positions' in p])}")
        print(f"  - Trades: {len([p for p in new_endpoints if '/trades' in p])}")
        print(f"  - Performance: {len([p for p in new_endpoints if '/performance' in p])}")
        print(f"  - Risk Events: {len([p for p in new_endpoints if '/risk-events' in p])}")

        print("\n📝 Next steps:")
        print("  1. Start the API server: python3 app.py")
        print("  2. Visit http://localhost:8000/docs to see all endpoints")
        print("  3. Test endpoints with authentication token")

    except AssertionError as e:
        print(f"\n❌ Test failed: {e}\n")
        raise
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}\n")
        raise
