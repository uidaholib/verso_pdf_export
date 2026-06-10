"""Enrich VERSO metadata records with abstracts from external APIs."""

import json
import logging

import pandas as pd
import requests
from tqdm import tqdm

from providers.harvester import try_providers

logger = logging.getLogger(__name__)


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


def extract_identifiers(record: dict) -> tuple[str, str, str, str]:
    """Pull the four key identifiers used by downstream enrichment providers.

    Returns (asset_id, doi, title, asset_type).  assetId lives inside the
    nested 'originalRepository' dict and may be an int, so we convert to str.
    """
    asset_id = str(record.get("originalRepository", {}).get("assetId", ""))
    doi = record.get("identifier.doi", "")
    title = record.get("title", "")
    asset_type = record.get("resourceType", "")
    return (asset_id, doi, title, asset_type)


def should_skip(record: dict, skip_types: list[str]) -> str | None:
    """Decide whether a record should be skipped during abstract enrichment.

    Returns a reason string if the record should be skipped, or None if it
    should be enriched.  The reason distinguishes "already has an abstract"
    from "asset type is in the skip list" so callers can report accurately.
    """
    abstracts = record.get("description.abstract", [])
    if abstracts and abstracts[0].get("value", ""):
        return "skipped_existing_abstract"

    if record.get("resourceType", "") in skip_types:
        return "skipped_etd"

    return None


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
