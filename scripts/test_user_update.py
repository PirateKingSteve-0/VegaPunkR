#!/usr/bin/env python3
"""
Test script to verify user settings update endpoint is working.

Run this to confirm the PATCH /auth/me endpoint can update user settings.
"""

import sys
import requests
import json
from getpass import getpass

API_URL = "http://localhost:8000/api/v1"

def test_user_update():
    """Test updating user settings via API"""
    print("=" * 60)
    print("User Settings Update Test")
    print("=" * 60)
    print()

    # Login to get auth token
    email = input("Enter your email: ").strip()
    password = getpass("Enter your password: ")

    print("\n1. Logging in...")
    login_response = requests.post(
        f"{API_URL}/auth/login",
        data={"username": email, "password": password}
    )

    if login_response.status_code != 200:
        print(f"❌ Login failed: {login_response.text}")
        return False

    token = login_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    print("✅ Login successful")

    # Get current user data
    print("\n2. Fetching current user data...")
    me_response = requests.get(f"{API_URL}/auth/me", headers=headers)

    if me_response.status_code != 200:
        print(f"❌ Failed to fetch user data: {me_response.text}")
        return False

    current_user = me_response.json()
    print("✅ Current user data:")
    print(f"   Email: {current_user['email']}")
    print(f"   Name: {current_user['name']}")
    print(f"   Account Size: ${current_user.get('account_size_usd', 0):,.2f}")
    print(f"   Max Trade %: {current_user.get('max_trade_percentage', 0.02) * 100:.2f}%")
    print(f"   Daily Loss Limit: {current_user.get('daily_loss_limit_pct', 5)}%")
    print(f"   Trading Window: {current_user.get('trading_window_enabled', False)}")

    # Prompt for test update
    print("\n3. Testing update...")
    print("Let's try updating account_size_usd to $1000.00")

    if input("Proceed with test update? (y/n): ").lower() != 'y':
        print("Test cancelled")
        return False

    # Send update
    update_payload = {
        "account_size_usd": 1000.00,
        "max_trade_percentage": 0.03,  # 3%
        "daily_loss_limit_pct": 5.0
    }

    print(f"\nSending PATCH to {API_URL}/auth/me")
    print(f"Payload: {json.dumps(update_payload, indent=2)}")

    update_response = requests.patch(
        f"{API_URL}/auth/me",
        json=update_payload,
        headers=headers
    )

    print(f"\nResponse status: {update_response.status_code}")
    print(f"Response body: {json.dumps(update_response.json(), indent=2)}")

    if update_response.status_code != 200:
        print(f"\n❌ Update failed!")
        return False

    updated_user = update_response.json()
    print("\n✅ Update successful!")
    print(f"   Account Size: ${updated_user.get('account_size_usd', 0):,.2f}")
    print(f"   Max Trade %: {updated_user.get('max_trade_percentage', 0.02) * 100:.2f}%")

    # Verify by fetching again
    print("\n4. Verifying changes persisted...")
    verify_response = requests.get(f"{API_URL}/auth/me", headers=headers)

    if verify_response.status_code != 200:
        print(f"❌ Failed to verify: {verify_response.text}")
        return False

    verified_user = verify_response.json()

    if verified_user['account_size_usd'] == 1000.00:
        print("✅ Changes verified in database!")
    else:
        print(f"❌ Changes NOT persisted. Got: ${verified_user['account_size_usd']}")
        return False

    print("\n" + "=" * 60)
    print("✅ All tests passed! The endpoint is working correctly.")
    print("=" * 60)
    return True


if __name__ == "__main__":
    try:
        success = test_user_update()
        sys.exit(0 if success else 1)
    except requests.exceptions.ConnectionError:
        print("\n❌ ERROR: Could not connect to API")
        print("Make sure the FastAPI backend is running on http://localhost:8000")
        print("Run: cd /Users/pirateking/Github/VegaPunkR/api && python app.py")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
