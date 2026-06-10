"""Import pre-harvested abstracts from a Universo MongoDB BSON export."""

import argparse
import json
import logging
import os
import sys
from datetime import datetime

import bson
import pandas as pd
from bson.errors import InvalidBSON
from tqdm import tqdm

from providers.harvester import title_match_score

logger = logging.getLogger(__name__)

FUZZY_THRESHOLD = 90


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


def write_import_csv(matches: list[dict], path: str) -> None:
    """Write match results to CSV so they can be reviewed or fed to VERSO import.

    None values are replaced with empty strings to avoid literal 'None' text
    in the output.  Column order is fixed for downstream tooling consistency.
    """
    rows = []
    for m in matches:
        row = dict(m)
        for key, value in row.items():
            if value is None:
                row[key] = ""
        rows.append(row)

    df = pd.DataFrame(
        rows,
        columns=[
            "asset_id",
            "verso_doi",
            "verso_title",
            "abstract",
            "abstract_source",
            "abstract_external_id",
            "match_method",
            "match_score",
        ],
    )
    df.to_csv(path, index=False, encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for the abstract import script."""
    parser = argparse.ArgumentParser(
        description="Match pre-harvested abstracts from a Universo BSON export to VERSO metadata records."
    )
    parser.add_argument(
        "--bson",
        required=True,
        help="Path to multi-document BSON export file",
    )
    parser.add_argument(
        "--metadata",
        required=True,
        help="Path to asset_metadata.json file",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=FUZZY_THRESHOLD,
        help=f"Minimum fuzzy title match score (default: {FUZZY_THRESHOLD})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Orchestrate the full abstract import pipeline."""
    args = parse_args(argv)

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
        bson_docs = parse_bson_abstracts(args.bson)
    except ValueError as exc:
        sys.exit(str(exc))

    logger.info("Parsed %d BSON docs with abstracts", len(bson_docs))

    try:
        verso_records = load_verso_records(args.metadata)
    except ValueError as exc:
        sys.exit(str(exc))

    logger.info("Loaded %d VERSO records", len(verso_records))

    matches = match_records(bson_docs, verso_records, args.threshold)

    write_import_csv(matches, f"C/{timestamp}/imported_abstracts.csv")

    doi_matched = sum(1 for m in matches if m["match_method"] == "doi")
    title_matched = sum(1 for m in matches if m["match_method"] == "title")
    unmatched = len(verso_records) - len(matches)

    print(f"Total BSON docs with abstracts: {len(bson_docs)}")
    print(f"Total VERSO records: {len(verso_records)}")
    print(f"Matched: {len(matches)} (DOI: {doi_matched}, title: {title_matched})")
    print(f"Unmatched: {unmatched}")


if __name__ == "__main__":
    main()
