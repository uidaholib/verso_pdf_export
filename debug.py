"""
debug.py — VERSO API connection diagnostic tool

Checks:
  1. .env file exists and VERSO_API_KEY is loaded
  2. The CSV file exists and has the expected 'Asset Id' column
  3. Constructs a sample API URL and fires a real request
  4. Validates the response shape the main script expects
"""

import os
import sys
import requests
import pandas as pd
from dotenv import load_dotenv

# ── Configuration ─────────────────────────────────────────────────────────────
CSV_FILENAME = "assetsWithPDFs.csv"
API_BASE_URL = "https://api-na.hosted.exlibrisgroup.com/esploro/v1/assets/"
ENV_VAR_NAME = "VERSO_API_KEY"

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
INFO = "\033[94m[INFO]\033[0m"
WARN = "\033[93m[WARN]\033[0m"

all_passed = True


def check(label, condition, detail=""):
    global all_passed
    status = PASS if condition else FAIL
    print(f"  {status} {label}")
    if detail:
        print(f"         {detail}")
    if not condition:
        all_passed = False
    return condition


# ── 1. .env and API key ───────────────────────────────────────────────────────
print("\n── Step 1: Environment & API key ────────────────────────────────────────")

env_file_exists = os.path.isfile(".env")
check(".env file found in current directory", env_file_exists,
      "Create a .env file here if it's missing.")

load_dotenv()
api_key = os.getenv(ENV_VAR_NAME)

key_loaded = bool(api_key)
check(f"{ENV_VAR_NAME} is set in environment", key_loaded,
      f"Add  {ENV_VAR_NAME}=your_key_here  to your .env file.")

if key_loaded:
    masked = api_key[:4] + "*" * (len(api_key) - 8) + api_key[-4:] if len(api_key) > 8 else "****"
    print(f"  {INFO} Key preview: {masked}  (length: {len(api_key)})")


# ── 2. CSV file ───────────────────────────────────────────────────────────────
print("\n── Step 2: CSV file ─────────────────────────────────────────────────────")

csv_exists = os.path.isfile(CSV_FILENAME)
check(f"CSV file '{CSV_FILENAME}' found", csv_exists,
      f"Place {CSV_FILENAME} in the same directory as this script.")

df = None
sample_id = None

if csv_exists:
    try:
        df = pd.read_csv(CSV_FILENAME)
        check("CSV loaded successfully", True, f"{len(df)} rows found.")

        has_col = "Asset Id" in df.columns
        check("'Asset Id' column present", has_col,
              f"Columns found: {list(df.columns)}")

        if has_col:
            first_valid = df["Asset Id"].dropna().head(1)
            has_rows = not first_valid.empty
            check("At least one non-null Asset Id exists", has_rows)
            if has_rows:
                sample_id = int(first_valid.iloc[0])
                print(f"  {INFO} Sample Asset Id: {sample_id}")

    except Exception as e:
        check("CSV loaded successfully", False, str(e))


# ── 3. API request ────────────────────────────────────────────────────────────
print("\n── Step 3: API connectivity ─────────────────────────────────────────────")

if not key_loaded:
    print(f"  {WARN} Skipping API test — no API key found.")
elif sample_id is None:
    print(f"  {WARN} Skipping API test — no sample Asset Id available.")
else:
    target_url = f"{API_BASE_URL}{sample_id}"
    print(f"  {INFO} Request URL: {target_url}?apikey=****")

    try:
        headers = {"Accept": "application/json"}
        response = requests.get(
            target_url,
            params={"apikey": api_key},
            headers=headers,
            timeout=10
        )

        check(f"HTTP request completed (status {response.status_code})",
              response.status_code == 200,
              "Non-200 response — check your key, network access, and Asset Id.")

        if response.status_code == 200:
            # Validate JSON
            try:
                data = response.json()
                check("Response is valid JSON", True)

                # Validate shape the main script expects
                has_records_key = "records" in data
                check("Response contains 'records' key", has_records_key,
                      f"Top-level keys found: {list(data.keys())}")

                if has_records_key:
                    is_list = isinstance(data["records"], list)
                    check("'records' is a list", is_list)

                    record_count = len(data["records"])
                    print(f"  {INFO} Records returned: {record_count}")

                    if record_count > 0:
                        first = data["records"][0]
                        has_files = "files" in first
                        check("First record contains 'files' key (optional)",
                              has_files,
                              "Key absent — this asset may simply have no files attached.")

            except Exception as e:
                check("Response is valid JSON", False, str(e))
                print(f"  {INFO} Raw response (first 300 chars): {response.text[:300]}")

        else:
            print(f"  {INFO} Response body (first 300 chars): {response.text[:300]}")

    except requests.exceptions.ConnectionError:
        check("Network connection to API host", False,
              "Cannot reach api-na.hosted.exlibrisgroup.com — check firewall / VPN.")
    except requests.exceptions.Timeout:
        check("Request completed within timeout", False,
              "Request timed out after 10 seconds.")
    except Exception as e:
        check("API request raised no exceptions", False, str(e))


# ── Summary ───────────────────────────────────────────────────────────────────
print("\n── Summary ──────────────────────────────────────────────────────────────")
if all_passed:
    print(f"  {PASS} All checks passed — the main script should connect successfully.\n")
else:
    print(f"  {FAIL} One or more checks failed — review the output above and fix before running the main script.\n")

sys.exit(0 if all_passed else 1)