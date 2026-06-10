"""Shared helper functions for record enrichment across harvesting scripts."""

import logging

import requests
from tqdm import tqdm

from providers.harvester import try_providers

logger = logging.getLogger(__name__)


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


def enrich_final_output(
    records: list[dict],
    session: requests.Session,
    oa_rate: float,
    s2_rate: float,
    threshold: int = 90,
    skip_types: list[str] | None = None,
) -> dict[str, dict]:
    """Run the provider cascade over records with per-record skip logic and error handling.

    Bridge between try_providers (Phase 1-3) and the export scripts — centralises
    skip/error/logging so scripts don't have to inline it.  Returns a dict keyed
    by asset_id for O(1) lookup during CSV generation.
    """
    if skip_types is None:
        skip_types = []

    results: dict[str, dict] = {}
    enriched = 0
    skipped = 0
    no_match = 0
    errors = 0

    for record in tqdm(records, desc="Enriching", unit="rec"):
        asset_id = ""
        try:
            asset_id, doi, title, asset_type = extract_identifiers(record)

            if not doi and not title:
                results[asset_id] = {
                    "abstract": "",
                    "abstract_source": "",
                    "abstract_external_id": "",
                    "harvest_status": "no_identifiers",
                    "trace": [],
                }
                skipped += 1
                continue

            skip_reason = should_skip(record, skip_types)
            if skip_reason is not None:
                results[asset_id] = {
                    "abstract": "",
                    "abstract_source": "",
                    "abstract_external_id": "",
                    "harvest_status": skip_reason,
                    "trace": [],
                }
                skipped += 1
                continue

            result, reason, trace = try_providers(
                session, doi, title, oa_rate, s2_rate, threshold
            )

            if result is not None:
                results[asset_id] = {
                    "abstract": result.get("abstract", ""),
                    "abstract_source": result.get("source", ""),
                    "abstract_external_id": result.get("external_id", ""),
                    "harvest_status": reason,
                    "trace": trace,
                }
                if reason == "ok" or reason == "low_confidence":
                    enriched += 1
                else:
                    no_match += 1
            else:
                results[asset_id] = {
                    "abstract": "",
                    "abstract_source": "",
                    "abstract_external_id": "",
                    "harvest_status": reason,
                    "trace": trace,
                }
                no_match += 1

        except Exception:
            # Intentionally broad: a single bad record should not crash the entire
            # enrichment run.  We log with exc_info so the traceback is available
            # for diagnosis.
            logger.warning(
                "Unexpected error enriching asset_id=%s", asset_id, exc_info=True
            )
            results[asset_id] = {
                "abstract": "",
                "abstract_source": "",
                "abstract_external_id": "",
                "harvest_status": "error",
                "trace": [],
            }
            errors += 1

    if enriched + no_match + errors == 0 and len(records) > 0:
        logger.warning(
            "All %d records were skipped — check skip_types and existing abstracts",
            len(records),
        )

    logger.info(
        "Enrichment complete: %d enriched, %d skipped, %d no_match, %d error out of %d total",
        enriched,
        skipped,
        no_match,
        errors,
        len(records),
    )

    return results
