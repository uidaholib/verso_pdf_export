"""Enrich VERSO metadata records with abstracts from external APIs."""

import json
import logging

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


def should_skip(record: dict, skip_types: list[str]) -> bool:
    """Decide whether a record should be skipped during abstract enrichment.

    Skips when the record already has a usable abstract (non-empty string in the
    first element's "value" key) or when its resourceType is in skip_types
    (e.g., ETDs that external APIs won't index).
    """
    abstracts = record.get("description.abstract", [])
    if abstracts and abstracts[0].get("value", ""):
        return True

    if record.get("resourceType", "") in skip_types:
        return True

    return False
