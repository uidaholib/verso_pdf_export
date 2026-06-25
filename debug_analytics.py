import os
import requests
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("ANALYTICS_API_KEY")

# Esploro Analytics endpoint (from original project instructions)
ANALYTICS_URL = (
    "https://analytics12-na.esploro.exlibrisgroup.com/analytics/saw.dll"
    "?Go&Path=%2fshared%2fUniversity%20of%20Idaho%2fReports%2fnormTesting%2fassetsWithPDFs"
    "&Options=rmf"
)

print(f"API_KEY found: {'yes' if API_KEY else 'NO - check .env'}\n")
print(f"URL: {ANALYTICS_URL}\n")

# Attempt 1: API key as Authorization header
print("--- Attempt 1: Authorization header ---")
resp = requests.get(
    ANALYTICS_URL,
    headers={
        "Accept": "application/xml",
        "Authorization": f"apikey {API_KEY}",
    },
    timeout=120,
)
print(f"HTTP status: {resp.status_code}")
print(f"Content-Type: {resp.headers.get('Content-Type', 'unknown')}")
print(resp.text[:500])

print("\n--- Attempt 2: apikey query param ---")
resp2 = requests.get(
    ANALYTICS_URL,
    params={"apikey": API_KEY},
    headers={"Accept": "application/xml"},
    timeout=120,
)
print(f"HTTP status: {resp2.status_code}")
print(f"Content-Type: {resp2.headers.get('Content-Type', 'unknown')}")
print(resp2.text[:500])

print("\n--- Attempt 3: api_key query param ---")
resp3 = requests.get(
    ANALYTICS_URL,
    params={"api_key": API_KEY},
    headers={"Accept": "application/xml"},
    timeout=120,
)
print(f"HTTP status: {resp3.status_code}")
print(f"Content-Type: {resp3.headers.get('Content-Type', 'unknown')}")
print(resp3.text[:500])