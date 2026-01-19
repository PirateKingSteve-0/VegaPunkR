"""
One-time Schwab OAuth authentication setup script.

Run this script to complete the OAuth flow and generate token.json.
After this, the API server will use the stored token automatically.
"""
import os
from schwab.auth import easy_client
from config import settings

print("=" * 60)
print("Schwab OAuth Authentication Setup")
print("=" * 60)
print()
print("This will open a browser window for you to authorize the app.")
print("The authorization will happen automatically - just approve the")
print("access in your browser when prompted.")
print()
print(f"Token will be saved to: {settings.SCHWAB_TOKEN_PATH}")
print()

# Delete existing token if present to force re-authentication
if os.path.exists(settings.SCHWAB_TOKEN_PATH):
    response = input("Token file already exists. Regenerate? (y/n): ").strip().lower()
    if response not in ['y', 'yes']:
        print("Exiting without changes.")
        exit(0)
    os.remove(settings.SCHWAB_TOKEN_PATH)
    print("Removed existing token file.")

try:
    # easy_client handles the full OAuth flow with built-in callback server
    client = easy_client(
        api_key=settings.SCHWAB_APP_KEY,
        app_secret=settings.SCHWAB_APP_SECRET,
        callback_url=settings.SCHWAB_CALLBACK_URL,
        token_path=settings.SCHWAB_TOKEN_PATH
    )

    print()
    print("✅ Authentication successful!")
    print(f"✅ Token saved to: {settings.SCHWAB_TOKEN_PATH}")
    print()
    print("You can now start the API server and it will use this token.")
    print("The token's access token expires hourly but will auto-refresh.")
    print("The refresh token lasts 7 days - re-authenticate before then.")

except Exception as e:
    print()
    print(f"❌ Authentication failed: {e}")
    print()
    print("Make sure you:")
    print("1. Have the correct APP_KEY and APP_SECRET in your .env file")
    print("2. The callback URL matches what's registered in Schwab Developer Portal")
    print("3. Port 8182 (or your callback port) is available")
    print("4. You approve the authorization in the browser window")
