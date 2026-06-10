"""Shared helper functions for record enrichment across harvesting scripts."""


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
