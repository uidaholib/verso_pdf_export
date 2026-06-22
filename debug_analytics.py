import os
import requests
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("VERSO_API_KEY")

# Correct endpoint: Alma API gateway, not the raw Oracle BI UI
ANALYTICS_BASE = "https://api-na.hosted.exlibrisgroup.com/almaws/v1/analytics/reports"
ANALYTICS_PATH = "/shared/University of Idaho/Reports/normTesting/assetsWithPDFs"

print(f"API_KEY found: {'yes' if API_KEY else 'NO - check .env'}\n")
print(f"URL: {ANALYTICS_BASE}")
print(f"Path: {ANALYTICS_PATH}\n")

resp = requests.get(
    ANALYTICS_BASE,
    params={
        "apikey": API_KEY,
        "path": ANALYTICS_PATH,
    },
    headers={"Accept": "application/xml"},
    timeout=120,
)

print(f"HTTP status: {resp.status_code}")
print(f"Content-Type: {resp.headers.get('Content-Type', 'unknown')}\n")
print("=== First 3000 chars of response ===")
print(resp.text[:3000])