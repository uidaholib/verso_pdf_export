"""Import pre-harvested abstracts from a Universo MongoDB BSON export."""

import json
import logging
import os

import bson
from bson.errors import InvalidBSON

logger = logging.getLogger(__name__)


def parse_bson_abstracts(filepath: str) -> list[dict]:
    """Read a multi-document BSON file and return docs that have provenance.

    Only documents with both a non-empty ``abstract`` and non-empty
    ``abstract_source`` are included — this ensures every imported abstract
    is traceable to the service that provided it.
    """
    if not os.path.isfile(filepath):
        raise ValueError(f"BSON file not found: {filepath}")

    results: list[dict] = []
    doc_count = 0
    with open(filepath, "rb") as f:
        try:
            for doc in bson.decode_file_iter(f):
                doc_count += 1
                abstract = doc.get("abstract") or ""
                abstract_source = doc.get("abstract_source") or ""

                if not abstract or not abstract_source:
                    continue

                results.append(
                    {
                        "abstract": abstract,
                        "abstract_source": abstract_source,
                        "abstract_external_id": doc.get("abstract_external_id") or "",
                        "identifier_doi": doc.get("identifier_doi") or "",
                        "title": doc.get("title") or "",
                    }
                )
        except InvalidBSON as exc:
            raise ValueError(f"Failed to decode BSON file {filepath}: {exc}") from exc

    if doc_count == 0:
        logger.warning("BSON file contains 0 documents: %s", filepath)

    return results


def load_verso_records(path: str) -> list[dict]:
    """Read a VERSO asset_metadata.json and return flat record dicts.

    Each record is reduced to three fields (asset_id, doi, title) because
    downstream matching only needs these — the full Esploro record shape
    used by abstract_script.load_metadata is not needed here.
    """
    try:
        with open(path) as f:
            raw = f.read()
    except FileNotFoundError:
        raise ValueError(f"metadata file not found: {path}")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object in {path}, got {type(data).__name__}")
    if "records" not in data:
        raise ValueError(f"missing 'records' key in {path}")

    results: list[dict] = []
    for record in data["records"]:
        asset_id = str(record.get("originalRepository", {}).get("assetId", ""))
        doi = (record.get("identifier.doi", "") or "").strip().lower()
        title = record.get("title", "") or ""
        results.append({"asset_id": asset_id, "doi": doi, "title": title})

    return results


def build_doi_index(docs: list[dict]) -> dict[str, dict]:
    """Build a DOI-keyed lookup dict from parsed abstract documents.

    Keys are normalized (lowercased, stripped) so that case/whitespace
    differences don't prevent matches against VERSO records.
    """
    index: dict[str, dict] = {}
    for doc in docs:
        raw_doi = doc.get("identifier_doi", "")
        normalized = raw_doi.strip().lower()
        if not normalized:
            continue
        if normalized in index:
            logger.warning(
                "Duplicate DOI after normalization: %r (overwrites previous entry)",
                normalized,
            )
        index[normalized] = doc
    return index
