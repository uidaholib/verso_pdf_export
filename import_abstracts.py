"""Import pre-harvested abstracts from a Universo MongoDB BSON export."""

import json
import logging
import os

import bson
from bson.errors import InvalidBSON
from tqdm import tqdm

from providers.harvester import title_match_score

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


def match_records(
    bson_docs: list[dict], verso_records: list[dict], threshold: int
) -> list[dict]:
    """Match BSON abstracts to VERSO records by DOI then fuzzy title fallback.

    DOI matches are exact (score 100.0). Title matches use rapidfuzz
    token_set_ratio and require score >= threshold. Ambiguous title matches
    (2nd-best within 2 points of best) are logged as warnings.
    """
    if not bson_docs or not verso_records:
        return []

    doi_index = build_doi_index(bson_docs)
    matches: list[dict] = []
    doi_matched_indices: set[int] = set()

    for i, rec in enumerate(verso_records):
        if rec["doi"] and rec["doi"] in doi_index:
            bson_doc = doi_index[rec["doi"]]
            matches.append(
                {
                    "asset_id": rec["asset_id"],
                    "verso_doi": rec["doi"],
                    "verso_title": rec["title"],
                    "abstract": bson_doc["abstract"],
                    "abstract_source": bson_doc["abstract_source"],
                    "abstract_external_id": bson_doc["abstract_external_id"],
                    "match_method": "doi",
                    "match_score": 100.0,
                }
            )
            doi_matched_indices.add(i)

    unmatched = [
        (i, rec)
        for i, rec in enumerate(verso_records)
        if i not in doi_matched_indices and rec["title"]
    ]

    for _, rec in tqdm(unmatched, desc="Title matching", unit="rec"):
        best_score = 0.0
        second_best_score = 0.0
        best_doc = None

        for bson_doc in bson_docs:
            score = title_match_score(rec["title"], bson_doc["title"])
            if score > best_score:
                second_best_score = best_score
                best_score = score
                best_doc = bson_doc
            elif score > second_best_score:
                second_best_score = score

        if best_score >= threshold and best_doc is not None:
            if best_score - second_best_score <= 2:
                logger.warning(
                    "Ambiguous title match for %r (best candidate: %r): "
                    "best=%.1f, 2nd-best=%.1f",
                    rec["title"],
                    best_doc["title"],
                    best_score,
                    second_best_score,
                )
            matches.append(
                {
                    "asset_id": rec["asset_id"],
                    "verso_doi": rec["doi"],
                    "verso_title": rec["title"],
                    "abstract": best_doc["abstract"],
                    "abstract_source": best_doc["abstract_source"],
                    "abstract_external_id": best_doc["abstract_external_id"],
                    "match_method": "title",
                    "match_score": best_score,
                }
            )

    return matches
