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
from tqdm import tqdm

from providers.enrich import extract_identifiers, should_skip
from providers.harvester import try_providers

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


def _make_result(
    asset_id="",
    doi="",
    title="",
    harvest_status="",
    abstract="",
    abstract_source="",
    abstract_external_id="",
    trace=None,
) -> dict:
    return {
        "asset_id": asset_id,
        "doi": doi,
        "title": title,
        "abstract": abstract,
        "abstract_source": abstract_source,
        "abstract_external_id": abstract_external_id,
        "harvest_status": harvest_status,
        "trace": trace if trace is not None else [],
    }


def enrich_records(
    records: list[dict],
    session: requests.Session,
    oa_rate: float,
    s2_rate: float,
    threshold: int,
    skip_types: list[str],
) -> list[dict]:
    """Iterate records, skip ineligible ones, and call providers for the rest.

    Each record produces a result dict with harvest_status indicating
    what happened: ok, low_confidence, no_match, skipped_existing_abstract,
    skipped_etd, no_identifiers, or error.
    """
    results: list[dict] = []

    for record in tqdm(records, desc="Enriching", unit="rec"):
        try:
            asset_id, doi, title, asset_type = extract_identifiers(record)

            if not doi and not title:
                results.append(_make_result(asset_id, doi, title, "no_identifiers"))
                continue

            skip_reason = should_skip(record, skip_types)
            if skip_reason is not None:
                results.append(_make_result(asset_id, doi, title, skip_reason))
                continue

            result, reason, trace = try_providers(
                session, doi, title, oa_rate, s2_rate, threshold
            )

            if result is not None:
                results.append(
                    _make_result(
                        asset_id,
                        doi,
                        title,
                        reason,
                        abstract=result["abstract"],
                        abstract_source=result["source"],
                        abstract_external_id=result["external_id"],
                        trace=trace,
                    )
                )
            else:
                results.append(_make_result(asset_id, doi, title, reason, trace=trace))

        except Exception:
            logger.warning(
                "Unexpected error processing record: %s",
                record,
                exc_info=True,
            )
            results.append(_make_result(harvest_status="error"))

    return results


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
        "metadata_path",
        help="Path to asset_metadata.json file",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help=f"Limit processing to first {DEBUG_SUBSET_SIZE} records",
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
        records = load_metadata(args.metadata_path)
    except ValueError as exc:
        sys.exit(str(exc))

    if args.debug:
        records = records[:DEBUG_SUBSET_SIZE]
        logger.info("DEBUG mode: processing first %d records", len(records))
    else:
        logger.info("Processing %d records", len(records))

    session = requests.Session()

    oa_rate = float(os.environ.get("OPENALEX_RATE_INTERVAL", "0.1"))
    s2_rate = float(os.environ.get("S2_RATE_INTERVAL", "1.0"))

    results = enrich_records(
        records, session, oa_rate, s2_rate, FUZZY_THRESHOLD, ASSET_TYPES_TO_SKIP
    )

    write_results_csv(results, f"C/{timestamp}/abstract_metadata.csv")

    enriched = sum(
        1 for r in results if r["harvest_status"] in ("ok", "low_confidence")
    )
    skipped = sum(1 for r in results if r["harvest_status"].startswith("skipped"))
    no_match = sum(1 for r in results if r["harvest_status"] == "no_match")
    errors = sum(1 for r in results if r["harvest_status"] == "error")

    print(f"Total processed: {len(results)}")
    print(f"Enriched: {enriched}")
    print(f"Skipped: {skipped}")
    print(f"No match: {no_match}")
    print(f"Errors: {errors}")


if __name__ == "__main__":
    main()
