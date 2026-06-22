import pandas as pd
import time
import requests
import json
import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from dotenv import load_dotenv
from tqdm import tqdm
import logging

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------
load_dotenv()
timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
DEBUG_MODE = False
DF_SUBSET_SIZE = 5  # Number of records to process in debug mode

# CSV filenames (root of the repo – always overwritten each run)
CSV_ALL       = "assetsWithPDFs.csv"
CSV_ETD       = "assetsWithPDFs_just_ETDs_metadata.csv"
CSV_SANS_ETD  = "assetsWithPDFs_without_ETD_metadata.csv"

# Asset types treated as ETDs
ETD_TYPES = {"ETD-Doctoral", "ETD-Graduate"}

# Alma Analytics API endpoint (goes through the API gateway, not the raw OBI UI)
# Column order matches the SELECT: s_0 skipped, s_1=Year, s_2=Type, s_3=HasFiles,
# s_4=Title, s_5=AssetId, s_6=FileViews, s_7=RecordViews, s_8=FileExt
ANALYTICS_PATH = (
    "/shared/University of Idaho/Reports/normTesting/assetsWithPDFs"
)
ANALYTICS_BASE = "https://api-na.hosted.exlibrisgroup.com/almaws/v1/analytics/reports"

# Column index → readable name (Column0 is s_0 dummy, skipped)
COL_MAP = {
    "Column1": "Asset Published Year",
    "Column2": "Asset Type",
    "Column3": "Has Files",
    "Column4": "Title",
    "Column5": "Asset Id",
    "Column6": "Number of File Views / Downloads",
    "Column7": "Number of Record Views",
    "Column8": "File Extension",
}

# XML namespace used by Oracle BI rowset responses
ROWSET_NS = "urn:schemas-microsoft-com:xml-analysis:rowset"

errors = []

# ---------------------------------------------------------------------------
# LOGGING – file (all levels) + console (WARNING+)
# ---------------------------------------------------------------------------
os.makedirs(f"./C/{timestamp}/", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler(f"C/{timestamp}/logs.log")],
)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.WARNING)
console_handler.setFormatter(
    logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
)
logging.getLogger().addHandler(console_handler)
logger = logging.getLogger(__name__)


# ===========================================================================
# STEP 0 – Fetch the analytics report and rebuild the three source CSVs
# ===========================================================================

def _parse_rows_from_xml(xml_text: str) -> tuple[list[dict], str, bool]:
    """
    Parse one page of the Oracle BI Analytics XML response.

    Returns:
        (rows, resumption_token, is_finished)

    The response structure is:
        <report>
          <QueryResult>
            <ResumptionToken>…</ResumptionToken>
            <IsFinished>true|false</IsFinished>
            <ResultXml>
              <rowset:rowset xmlns:rowset="urn:schemas-microsoft-com:xml-analysis:rowset"
                             xmlns="urn:schemas-microsoft-com:xml-analysis:rowset">
                <Row>
                  <Column0>…</Column0>
                  <Column1>…</Column1>
                  …
                </Row>
              </rowset:rowset>
            </ResultXml>
          </QueryResult>
        </report>
    """
    root = ET.fromstring(xml_text)

    # Pagination controls
    token_el    = root.find(".//ResumptionToken")
    finished_el = root.find(".//IsFinished")
    resumption_token = token_el.text.strip() if token_el is not None and token_el.text else ""
    is_finished      = (finished_el.text or "").strip().lower() == "true"

    # Rows live inside the namespaced rowset
    row_elements = root.findall(f".//{{{ROWSET_NS}}}Row")

    rows = []
    for row_el in row_elements:
        row = {}
        for child in row_el:
            # Strip namespace prefix from tag name
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if tag in COL_MAP:
                row[COL_MAP[tag]] = (child.text or "").strip()
        if row:
            rows.append(row)

    return rows, resumption_token, is_finished


def fetch_and_rebuild_csvs() -> None:
    """
    Pull the assetsWithPDFs report from Alma Analytics via the API gateway,
    handling pagination via ResumptionToken.  Save it as assetsWithPDFs.csv,
    then split into the ETD and non-ETD CSVs (overwriting previous versions).
    """
    API_KEY = os.getenv("VERSO_API_KEY")
    if not API_KEY:
        raise EnvironmentError("VERSO_API_KEY not found in environment / .env file.")

    print("Fetching latest assetsWithPDFs report from Alma Analytics …")
    logger.info("Fetching analytics report: %s", ANALYTICS_PATH)

    all_rows = []
    resumption_token = None

    while True:
        params = {
            "apikey": API_KEY,
            "path":   ANALYTICS_PATH,
        }
        if resumption_token:
            params["token"] = resumption_token

        response = requests.get(
            ANALYTICS_BASE,
            params=params,
            headers={"Accept": "application/xml"},
            timeout=120,
        )
        response.raise_for_status()

        rows, resumption_token, is_finished = _parse_rows_from_xml(response.text)
        all_rows.extend(rows)
        print(f"  … fetched {len(all_rows):,} rows so far", end="\r")

        if is_finished:
            break
        if not resumption_token:
            # Safety: no token and not finished means something unexpected
            logger.warning("No ResumptionToken received but IsFinished was not true – stopping.")
            break

    print(f"  Fetched {len(all_rows):,} total rows from Analytics.          ")

    if not all_rows:
        raise ValueError(
            "No data rows found in the Analytics response. "
            "Check the API key, report path, and that the report has results."
        )

    df_all = pd.DataFrame(all_rows)
    if "Asset Id" in df_all.columns:
        df_all["Asset Id"] = pd.to_numeric(df_all["Asset Id"], errors="coerce")

    df_all.to_csv(CSV_ALL, index=False, encoding="utf-8")
    print(f"  Saved {len(df_all):,} rows → {CSV_ALL}")
    logger.info("Saved %d rows to %s", len(df_all), CSV_ALL)

    # Split on Asset Type
    mask_etd    = df_all["Asset Type"].isin(ETD_TYPES)
    df_etd      = df_all[mask_etd].reset_index(drop=True)
    df_sans_etd = df_all[~mask_etd].reset_index(drop=True)

    df_etd.to_csv(CSV_ETD, index=False, encoding="utf-8")
    print(f"  Saved {len(df_etd):,} ETD rows → {CSV_ETD}")
    logger.info("Saved %d ETD rows to %s", len(df_etd), CSV_ETD)

    df_sans_etd.to_csv(CSV_SANS_ETD, index=False, encoding="utf-8")
    print(f"  Saved {len(df_sans_etd):,} non-ETD rows → {CSV_SANS_ETD}\n")
    logger.info("Saved %d non-ETD rows to %s", len(df_sans_etd), CSV_SANS_ETD)


# ===========================================================================
# STEP 1 – Load the appropriate CSV for this run mode
# ===========================================================================

def load_data(mode: str) -> pd.DataFrame:
    """
    Load asset IDs from the CSV that corresponds to the run mode and
    attach the Esploro API URL to each row.

    mode values: 'full' | 'ETD' | 'sansETD'
    """
    csv_map = {
        "full":    CSV_ALL,
        "ETD":     CSV_ETD,
        "sansETD": CSV_SANS_ETD,
    }
    csv_file = csv_map[mode]

    if not os.path.exists(csv_file):
        raise FileNotFoundError(
            f"Source CSV '{csv_file}' not found. "
            "Run the script to regenerate it from Analytics."
        )

    df = pd.read_csv(csv_file)
    print(f"Loaded {len(df):,} records from '{csv_file}'.")
    logger.info("Loaded %d records from %s", len(df), csv_file)

    api_base = "https://api-na.hosted.exlibrisgroup.com/esploro/v1/assets/"
    df["api_url"] = df["Asset Id"].apply(
        lambda x: f"{api_base}{int(x)}" if pd.notna(x) else None
    )
    return df


# ===========================================================================
# STEP 2 – Fetch asset metadata via Esploro API
# ===========================================================================

def make_api_calls(df: pd.DataFrame) -> dict:
    """
    Request each asset's metadata as JSON from the Esploro API and
    compile into a single dict (also saved as JSON).
    """
    API_KEY = os.getenv("VERSO_API_KEY")
    all_records = []

    df_subset = df.head(DF_SUBSET_SIZE) if DEBUG_MODE else df

    print(f"\nStarting API extraction for {len(df_subset):,} records …")
    logger.info("Starting API extraction for %d records.", len(df_subset))

    for index, row in tqdm(
        df_subset.iterrows(), total=len(df_subset), desc="Fetching Records", unit="rec"
    ):
        target_url = row["api_url"]
        try:
            response = requests.get(
                target_url,
                params={"apikey": API_KEY},
                headers={"Accept": "application/json"},
            )
            if response.status_code == 200:
                try:
                    data = response.json()
                    if "records" in data and isinstance(data["records"], list):
                        all_records.extend(data["records"])
                except Exception as e:
                    tqdm.write(f"Error [Row {index}]: Response was not valid JSON. URL: {target_url}")
                    logger.error("Error for URL %s: %s", target_url, e)
                    errors.append({"url": target_url, "error": str(e)})
            else:
                error_msg = f"Failed: {response.status_code} - {response.text}"
                tqdm.write(f"Error [Row {index}]: {error_msg} URL: {target_url}")
                logger.error("Error for URL %s: %s", target_url, error_msg)
                errors.append({"url": target_url, "error": error_msg})
        except Exception as e:
            tqdm.write(f"Error [Row {index}]: {e} URL: {target_url}")
            logger.error("Exception for URL %s: %s", target_url, e)
            errors.append({"url": target_url, "error": str(e)})

        time.sleep(0.2)

    final_output = {"totalRecordCount": len(all_records), "records": all_records}

    output_file = f"C/{timestamp}/asset_metadata.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(final_output, f, indent=4)

    print(f"\nExtraction complete.\n")

    if len(all_records) == len(df_subset):
        logger.info("All %d records successfully retrieved.", len(all_records))
    else:
        logger.warning(
            "Discrepancy: retrieved %d out of %d records.",
            len(all_records), len(df_subset),
        )
    logger.info("Saved %d records to %s", len(all_records), output_file)

    if errors:
        print(f"Encountered {len(errors)} errors (check log).")

    return final_output


# ===========================================================================
# STEP 3 – Download PDF files
# ===========================================================================

def download_asset_files(final_output: dict) -> list:
    """
    Download PDFs listed in fileDownloadUrl into folder 'A'.
    """
    logger.info("Starting download_asset_files")

    assets_with_files = 0
    total_files = 0
    file_tasks = []

    output_dir = "A"
    os.makedirs(output_dir, exist_ok=True)

    for record in final_output["records"]:
        if "files" not in record:
            continue

        asset_id = record["originalRepository"]["assetId"]
        pdf_files = [
            f for f in record["files"]
            if f.get("file.extension", "").lower() == "pdf"
        ]

        if not pdf_files:
            continue

        assets_with_files += 1
        multi = len(record["files"]) > 1
        pdf_idx = 0

        for asset_file in pdf_files:
            file_tasks.append({
                "url":                asset_file["fileDownloadUrl"],
                "original_name":      asset_file["file.name"],
                "asset_id":           asset_id,
                "file_number":        pdf_idx if multi else None,
                "file_creation_date": asset_file.get("file.creationDate", ""),
                "file_size_bytes":    asset_file.get("file.size", ""),
                "file_order":         asset_file.get("file.order", ""),
            })
            if multi:
                pdf_idx += 1

    logger.info("Downloading %d PDFs into folder 'A'", len(file_tasks))

    for task in tqdm(file_tasks, desc="Downloading PDFs"):
        try:
            response = requests.get(task["url"])
            response.raise_for_status()

            _, file_extension = os.path.splitext(task["original_name"])
            filename = (
                f"{task['asset_id']}_{task['file_number']}{file_extension}"
                if task["file_number"] is not None
                else f"{task['asset_id']}{file_extension}"
            )

            with open(os.path.join(output_dir, filename), "wb") as f:
                f.write(response.content)

            total_files += 1
            time.sleep(0.2)

        except requests.exceptions.RequestException as e:
            error_msg = (
                f"Error downloading {task['original_name']} "
                f"from {task['asset_id']}: {e}"
            )
            print(f"\n{error_msg}")
            logger.error(error_msg)
            errors.append(error_msg)
            time.sleep(0.2)

    print(f"\nAssets with files: {assets_with_files}")
    print(f"Total PDFs saved to folder 'A': {total_files}")
    print(f"Errors encountered (if any): {errors}")
    logger.info(
        "File download complete: %d files downloaded to 'A', %d errors",
        total_files, len(errors),
    )
    return file_tasks


# ===========================================================================
# STEP 4 – Generate metadata CSV (and _new diff CSV)
# ===========================================================================

def _build_metadata_rows(file_tasks: list, final_output: dict) -> list:
    """
    Shared logic: build the list of metadata dicts from file_tasks + API records.
    """
    record_lookup = {
        rec["originalRepository"]["assetId"]: rec
        for rec in final_output["records"]
        if "originalRepository" in rec and "assetId" in rec["originalRepository"]
    }

    rows = []
    for task in file_tasks:
        asset_id = task["asset_id"]
        record   = record_lookup.get(asset_id, {})

        creators_list = [
            c["creatorname"]
            for c in record.get("creators", [])
            if isinstance(c, dict) and "creatorname" in c
        ]
        creators_str = "; ".join(creators_list)

        first_creator  = record.get("creators", [{}])[0] if record.get("creators") else {}
        additional_ids = first_creator.get("additionalIdentifiers", {})

        _, ext = os.path.splitext(task["original_name"])
        filename = (
            f"{task['asset_id']}_{task['file_number']}{ext}"
            if task["file_number"] is not None
            else f"{task['asset_id']}{ext}"
        )

        row = {
            "filename":            filename,
            "asset_id":            asset_id,
            "original_filename":   task["original_name"],
            "file_name_in_record": task["original_name"],
            "file_number":         task["file_number"] if task["file_number"] is not None else "",
            "file_order":          task.get("file_order", ""),
            "file_creation_date":  task.get("file_creation_date", ""),
            "file_size_bytes":     task.get("file_size_bytes", ""),
            "title":               record.get("title", ""),
            "description": (
                record.get("description.abstract", [{}])[0].get("value", "")
                if record.get("description.abstract") else ""
            ),
            "creators":            creators_str,
            "publisher":           record.get("publisher", ""),
            "publication_date":    record.get("date.published", ""),
            "displayed_date":      record.get("displayedDateByPriorityEsploroCP", ""),
            "language": (
                "; ".join(record.get("language", []))
                if isinstance(record.get("language"), list)
                else record.get("language", "")
            ),
            "external_id":         additional_ids.get("EXTERNAL", ""),
            "barcode":             additional_ids.get("BARCODE", ""),
            "pivot_id":            additional_ids.get("Pivot", ""),
            "inst_id":             additional_ids.get("INST_ID", ""),
            "other_id":            additional_ids.get("Other", ""),
            "alma_user_id":        first_creator.get("almaUserId", ""),
            "user_primary_id":     first_creator.get("user.primaryId", ""),
            "doi":                 record.get("identifier.doi", ""),
            "uri":                 record.get("identifier.uri", ""),
            "wos_id":              record.get("identifier.wos", ""),
            "download_url":        task["url"],
        }
        rows.append(row)

    return rows


def _load_previous_asset_ids(csv_path: str) -> set:
    """
    Read a previously generated metadata CSV and return the set of asset_id
    values it contained.  Returns empty set if the file doesn't exist.
    """
    if not os.path.exists(csv_path):
        return set()
    try:
        prev_df = pd.read_csv(csv_path, usecols=["asset_id"], dtype=str)
        return set(prev_df["asset_id"].dropna().unique())
    except Exception as e:
        logger.warning("Could not read previous CSV %s: %s", csv_path, e)
        return set()


def generate_metadata_csv(file_tasks: list, final_output: dict, mode: str) -> None:
    """
    Generate metadata CSVs in folder B:
      • pdf_metadata.csv      – full metadata for this run
      • pdf_metadata_new.csv  – only rows whose asset_id was NOT in the
                                 previous run's pdf_metadata.csv

    The '_new' file helps digital preservation staff identify items not yet
    archived from prior export initiatives.
    """
    logger.info("Generating metadata CSV in folder B (mode=%s)", mode)
    os.makedirs("B", exist_ok=True)

    metadata_path     = "B/pdf_metadata.csv"
    metadata_new_path = "B/pdf_metadata_new.csv"

    # Capture asset IDs from the PREVIOUS run before overwriting
    previous_asset_ids = _load_previous_asset_ids(metadata_path)
    logger.info(
        "Previous run had %d unique asset IDs in %s",
        len(previous_asset_ids), metadata_path,
    )

    rows = _build_metadata_rows(file_tasks, final_output)

    metadata_df = pd.DataFrame(rows)
    metadata_df.to_csv(metadata_path, index=False, encoding="utf-8")
    logger.info("Metadata CSV saved to %s (%d records)", metadata_path, len(rows))
    print(f"\nMetadata CSV generated:    {metadata_path}  ({len(rows):,} records)")

    # Identify rows new to this run
    if previous_asset_ids:
        new_df = metadata_df[
            ~metadata_df["asset_id"].astype(str).isin(previous_asset_ids)
        ]
    else:
        new_df = metadata_df.copy()

    new_df.to_csv(metadata_new_path, index=False, encoding="utf-8")
    logger.info("New-items CSV saved to %s (%d records)", metadata_new_path, len(new_df))
    print(
        f"New-items CSV generated:   {metadata_new_path}  "
        f"({len(new_df):,} records not present in previous run)"
    )


# ===========================================================================
# CLI entry-point
# ===========================================================================

VALID_MODES = {"full", "ETD", "sansETD"}


def print_usage() -> None:
    print(
        "\nUsage:\n"
        "  python script.py full      – download ALL assets (PDFs + metadata)\n"
        "  python script.py ETD       – download ETD assets only\n"
        "  python script.py sansETD   – download non-ETD assets only\n"
        "\nIn all modes the script first refreshes the three source CSVs\n"
        "by fetching the latest report from Alma Analytics.\n"
    )


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in VALID_MODES:
        print_usage()
        sys.exit(1)

    mode = sys.argv[1]
    print(f"\n{'='*60}")
    print(f"  verso_pdf_export  |  mode: {mode}  |  {timestamp}")
    print(f"{'='*60}\n")

    # 0. Refresh source CSVs from Analytics
    fetch_and_rebuild_csvs()

    # 1. Load the appropriate slice
    df = load_data(mode)

    # 2. Fetch asset metadata
    final_output = make_api_calls(df)

    # 3. Download PDFs
    file_tasks = download_asset_files(final_output)

    # 4. Write metadata CSVs (full + _new diff)
    generate_metadata_csv(file_tasks, final_output, mode)

    print(f"\nDone. Logs and asset_metadata.json → C/{timestamp}/\n")