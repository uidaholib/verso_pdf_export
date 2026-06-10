"""Enrich VERSO metadata records with abstracts from external APIs."""

import argparse
import json
import logging
import os
import sys
from datetime import datetime

import pandas as pd
import requests
from dotenv import load_dotenv

from providers.enrich import enrich_final_output, extract_identifiers

logger = logging.getLogger(__name__)

FUZZY_THRESHOLD = 90
ASSET_TYPES_TO_SKIP = ["ETD-Doctoral", "ETD-Masters"]
DEBUG_SUBSET_SIZE = 5


def load_metadata(path: str) -> list[dict]:
    """Read and validate an asset_metadata.json file, returning the records list.

    The file must contain a JSON object with a "records" key whose value is a
    list.  If "totalRecordCount" is present and doesn't match len(records), a
    warning is logged but the records are still returned.

    Raises ValueError on any I/O or validation failure so callers get a clear
    message instead of a cryptic traceback.
    """
    try:
        with open(path) as f:
            raw = f.read()
    except FileNotFoundError:
        raise ValueError(f"metadata file not found: {path}")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}")

    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object in {path}, got {type(data).__name__}")

    if "records" not in data:
        raise ValueError(f"missing 'records' key in {path}")

    records = data["records"]

    total = data.get("totalRecordCount")
    if total is not None and total != len(records):
        logger.warning(
            "totalRecordCount=%d but found %d records in %s",
            total,
            len(records),
            path,
        )

    return records


def merge_enrichment_results(
    enrichment_results: dict[str, dict],
    records: list[dict],
) -> list[dict]:
    """Convert enrich_final_output's dict-keyed-by-asset_id into the flat list
    that write_results_csv expects, preserving the original record order."""
    merged: list[dict] = []
    for record in records:
        asset_id, doi, title, _asset_type = extract_identifiers(record)
        enrichment = enrichment_results.get(str(asset_id), {})
        merged.append(
            {
                "asset_id": asset_id,
                "doi": doi,
                "title": title,
                "abstract": enrichment.get("abstract", ""),
                "abstract_source": enrichment.get("abstract_source", ""),
                "abstract_external_id": enrichment.get("abstract_external_id", ""),
                "harvest_status": enrichment.get("harvest_status", ""),
                "trace": enrichment.get("trace", []),
            }
        )
    return merged


def write_results_csv(results: list[dict], path: str) -> None:
    """Serialize enrichment results to CSV for review or downstream import.

    Trace lists are joined with semicolons so each row stays on one line,
    and None values become empty strings so the CSV never contains literal
    'None' text.
    """
    rows = []
    for r in results:
        row = dict(r)
        trace = row.get("trace")
        row["trace"] = ";".join(trace) if isinstance(trace, list) else (trace or "")
        for key, value in row.items():
            if value is None:
                row[key] = ""
        rows.append(row)

    df = pd.DataFrame(
        rows,
        columns=[
            "asset_id",
            "doi",
            "title",
            "abstract",
            "abstract_source",
            "abstract_external_id",
            "harvest_status",
            "trace",
        ],
    )
    df.to_csv(path, index=False, encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for the abstract harvesting script."""
    parser = argparse.ArgumentParser(
        description="Enrich VERSO metadata records with abstracts from external APIs."
    )
    parser.add_argument(
        "--metadata",
        required=True,
        help="Path to asset_metadata.json file",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help=f"Limit processing to first {DEBUG_SUBSET_SIZE} records",
    )
    parser.add_argument(
        "--subset-size",
        type=int,
        default=DEBUG_SUBSET_SIZE,
        help=f"Number of records to process in debug mode (default: {DEBUG_SUBSET_SIZE})",
    )
    parser.add_argument(
        "--fuzzy-threshold",
        type=int,
        default=FUZZY_THRESHOLD,
        help=f"Minimum fuzzy-match score for title matching (default: {FUZZY_THRESHOLD})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Orchestrate the full abstract enrichment pipeline."""
    args = parse_args(argv)
    load_dotenv()

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    os.makedirs(f"C/{timestamp}/", exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(f"C/{timestamp}/logs.log"),
        ],
    )

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    logging.getLogger().addHandler(console_handler)

    try:
        records = load_metadata(args.metadata)
    except ValueError as exc:
        sys.exit(str(exc))

    if args.debug:
        records = records[: args.subset_size]
        logger.info("DEBUG mode: processing first %d records", len(records))
    else:
        logger.info("Processing %d records", len(records))

    session = requests.Session()

    oa_rate = float(os.environ.get("OPENALEX_RATE_INTERVAL", "0.1"))
    s2_rate = float(os.environ.get("S2_RATE_INTERVAL", "1.0"))

    enrichment_results = enrich_final_output(
        records, session, oa_rate, s2_rate, args.fuzzy_threshold, ASSET_TYPES_TO_SKIP
    )
    results = merge_enrichment_results(enrichment_results, records)

    write_results_csv(results, f"C/{timestamp}/abstract_metadata.csv")

    print(f"Results written to C/{timestamp}/abstract_metadata.csv")


if __name__ == "__main__":
    main()
