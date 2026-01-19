"""
Schwab Token Refresh Utility

Proactively refreshes the Schwab OAuth token before it expires.
Run this periodically (e.g., every 5-6 days) to avoid expiration.

Token lifespan: 7 days
Recommended refresh interval: Every 5-6 days
"""
import os
import json
from datetime import datetime, timedelta
from schwab import auth
from config import settings


def check_token_status():
    """Check current token status and expiration."""
    if not os.path.exists(settings.SCHWAB_TOKEN_PATH):
        print("❌ No token file found")
        print(f"   Expected location: {settings.SCHWAB_TOKEN_PATH}")
        print("   Run schwab_auth_setup.py to authenticate")
        return False

    try:
        with open(settings.SCHWAB_TOKEN_PATH, 'r') as f:
            token_data = json.load(f)

        if 'expires_at' not in token_data:
            print("⚠️  Warning: Token file missing expiration data")
            return False

        expires_at = datetime.fromtimestamp(token_data['expires_at'])
        now = datetime.now()
        time_remaining = expires_at - now

        print("=" * 60)
        print("Schwab Token Status")
        print("=" * 60)
        print(f"Token file: {settings.SCHWAB_TOKEN_PATH}")
        print(f"Expires at: {expires_at.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Time remaining: {time_remaining}")
        print()

        if time_remaining < timedelta(0):
            print("❌ Token has EXPIRED")
            print("   Run schwab_auth_setup.py to re-authenticate")
            return False
        elif time_remaining < timedelta(days=1):
            print("⚠️  Token expires in less than 1 day - REFRESH RECOMMENDED")
            return True
        elif time_remaining < timedelta(days=2):
            print("⚠️  Token expires in less than 2 days - consider refreshing")
            return True
        else:
            print(f"✅ Token is valid for {time_remaining.days} more days")
            return True

    except Exception as e:
        print(f"❌ Error checking token: {e}")
        return False


def refresh_token():
    """Refresh the Schwab OAuth token."""
    print("\n" + "=" * 60)
    print("Refreshing Schwab Token")
    print("=" * 60)

    try:
        # Load and re-save the client (this triggers auto-refresh)
        client = auth.client_from_token_file(
            token_path=settings.SCHWAB_TOKEN_PATH,
            api_key=settings.SCHWAB_APP_KEY,
            app_secret=settings.SCHWAB_APP_SECRET
        )

        # Make a simple API call to verify token works
        response = client.get_account_numbers()

        if response.status_code == 200:
            print("✅ Token refreshed successfully!")

            # Check new expiration
            with open(settings.SCHWAB_TOKEN_PATH, 'r') as f:
                token_data = json.load(f)

            new_expires_at = datetime.fromtimestamp(token_data['expires_at'])
            print(f"   New expiration: {new_expires_at.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"   Valid for: {(new_expires_at - datetime.now()).days} days")
            return True
        else:
            print(f"❌ Token refresh failed: HTTP {response.status_code}")
            return False

    except Exception as e:
        print(f"❌ Error refreshing token: {e}")
        print("   You may need to re-authenticate using schwab_auth_setup.py")
        return False


def main():
    """Main function."""
    print("\n" + "=" * 60)
    print("Schwab Token Refresh Utility")
    print("=" * 60)
    print()

    # Check current status
    token_valid = check_token_status()

    if not token_valid:
        return

    # Ask user if they want to refresh
    print()
    response = input("Do you want to refresh the token now? (y/n): ").strip().lower()

    if response in ['y', 'yes']:
        refresh_token()
    else:
        print("Token not refreshed")

    print("\n" + "=" * 60)
    print("💡 Tip: Schedule this script to run every 5-6 days")
    print("   Example cron job (runs every 5 days at 3am):")
    print("   0 3 */5 * * cd /path/to/api && python3 schwab_token_refresh.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
