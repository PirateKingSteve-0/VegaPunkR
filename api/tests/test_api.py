"""Quick API test script."""
import requests

BASE_URL = "http://localhost:8000"

# Test health
response = requests.get(f"{BASE_URL}/")
print("Health check:", response.json())

# Test login
login_data = {
    "username": "kingofpirates92@gmail.com",
    "password": "Kaidasparrow5264!"
}
response = requests.post(f"{BASE_URL}/api/v1/auth/login", data=login_data)
print("\nLogin response:", response.status_code)
print(response.json())

if response.status_code == 200:
    token = response.json()["access_token"]
    print(f"\n✓ Login successful! Token: {token[:50]}...")

    # Test /me endpoint
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(f"{BASE_URL}/api/v1/auth/me", headers=headers)
    print("\n/me response:")
    print(response.json())
else:
    print("\n✗ Login failed!")
