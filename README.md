# verso_pdf_export

Export PDF files and metadata from the University of Idaho's VERSO institutional repository (Esploro) for web archiving purposes.

## What This Tool Does

This project fetches metadata records from the VERSO/Esploro API based on titles listed in a CSV input file. Depending on which script you run, it either downloads the associated PDFs alongside the metadata or generates metadata only.

The tool can also enrich records with abstracts sourced from external APIs (OpenAlex and Semantic Scholar). Abstract enrichment can run inline during a metadata fetch, or as a standalone post-processing step against previously exported metadata.

Records with asset types `ETD-Doctoral` and `ETD-Masters` are skipped by default during enrichment, since those records typically already have abstracts.

## Setup

### Prerequisites

- Python 3 (no specific version pinned)
- `uv` or `venv` for environment isolation

### Install

```bash
git clone <repo-url>
cd verso_pdf_export
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Dependencies: `pandas>=1.5.0`, `requests>=2.28.0`, `python-dotenv>=1.0.0`, `tqdm>=4.65.0`, `openpyxl>=3.0.0`, `rapidfuzz>=3.0.0`, `pymongo>=4.0.0`

### Environment Variables

Create a `.env` file in the project root. The `.env` file is obtained from SharePoint (see `setup.md` for details).

| Variable | Required | Default | Description |
|---|---|---|---|
| `VERSO_API_KEY` | Yes | -- | Authenticates requests to the Esploro API. Used by `script.py` and `md_script.py`. |
| `OPENALEX_API_KEY` | Recommended | `""` | Dedicated rate-limit allocation for OpenAlex API. Free keys available at [openalex.org](https://openalex.org). Unauthenticated requests work but share a rate-limit pool. |
| `S2_API_KEY` | No | `""` | Guaranteed 1 req/s individual allocation for Semantic Scholar, vs shared unauthenticated pool. |
| `OPENALEX_RATE_INTERVAL` | No | `0.1` | Minimum interval (seconds) between OpenAlex API requests. |
| `S2_RATE_INTERVAL` | No | `1.0` | Minimum interval (seconds) between Semantic Scholar API requests. |

### Create Output Directories

The output directories are gitignored and must be created manually:

```bash
mkdir A B C
```

## Usage

### `script.py` -- Fetch Metadata and Download PDFs

Fetches metadata and downloads PDFs from VERSO/Esploro.

```bash
./.venv/bin/python script.py
```

| Flag | Type | Default | Description |
|---|---|---|---|
| `--csv` | string | `assetsWithPDFs_just_ETDs.csv` | Path to input CSV file |
| `--debug` | flag | off | Enable debug mode (process subset of records) |
| `--subset-size` | int | `5` | Number of records to process in debug mode |
| `--enrich-abstracts` | flag | off | Enrich records with abstracts from OpenAlex/Semantic Scholar |
| `--fuzzy-threshold` | int | `90` | Minimum fuzzy-match score for title matching |

**Example:**

```bash
./.venv/bin/python script.py --csv my_assets.csv --debug --subset-size 10
```

**Output:** `A/` (PDFs), `B/pdf_metadata.csv`, `C/{timestamp}/asset_metadata.json`, `C/{timestamp}/logs.log`

---

### `md_script.py` -- Fetch Metadata Only (No PDFs)

Fetches metadata and generates CSV from VERSO/Esploro without downloading PDFs.

```bash
./.venv/bin/python md_script.py
```

| Flag | Type | Default | Description |
|---|---|---|---|
| `--csv` | string | `assetsWithPDFs_without_ETD.csv` | Path to input CSV file |
| `--debug` | flag | off | Enable debug mode (process subset of records) |
| `--subset-size` | int | `5` | Number of records to process in debug mode |
| `--enrich-abstracts` | flag | off | Enrich records with abstracts from OpenAlex/Semantic Scholar |
| `--fuzzy-threshold` | int | `90` | Minimum fuzzy-match score for title matching |

**Example:**

```bash
./.venv/bin/python md_script.py --enrich-abstracts --fuzzy-threshold 85
```

**Output:** `B/pdf_metadata.csv`, `C/{timestamp}/asset_metadata.json`, `C/{timestamp}/logs.log` (does NOT write to `A/`)

---

### `abstract_script.py` -- Enrich Existing Metadata with Abstracts

Enriches previously exported VERSO metadata records with abstracts from external APIs. Runs as a standalone post-processing step.

```bash
./.venv/bin/python abstract_script.py --metadata C/2026-01-15_12-00-00/asset_metadata.json
```

| Flag | Type | Default | Description |
|---|---|---|---|
| `--metadata` | string | **required** | Path to `asset_metadata.json` file |
| `--debug` | flag | off | Limit processing to first N records |
| `--subset-size` | int | `5` | Number of records to process in debug mode |
| `--fuzzy-threshold` | int | `90` | Minimum fuzzy-match score for title matching |

**Example:**

```bash
./.venv/bin/python abstract_script.py --metadata C/2026-01-15_12-00-00/asset_metadata.json --debug
```

**Output:** `C/{timestamp}/abstract_metadata.csv` (in a new timestamped subdirectory)

---

### `import_abstracts.py` -- Match Abstracts from BSON Export

Matches pre-harvested abstracts from a Universo BSON export to VERSO metadata records using fuzzy title matching.

```bash
./.venv/bin/python import_abstracts.py --bson export.bson --metadata C/2026-01-15_12-00-00/asset_metadata.json
```

| Flag | Type | Default | Description |
|---|---|---|---|
| `--bson` | string | **required** | Path to multi-document BSON export file |
| `--metadata` | string | **required** | Path to `asset_metadata.json` file |
| `--threshold` | int | `90` | Minimum fuzzy title match score |

**Example:**

```bash
./.venv/bin/python import_abstracts.py --bson universo_dump.bson --metadata C/2026-01-15_12-00-00/asset_metadata.json --threshold 85
```

**Output:** `C/{timestamp}/imported_abstracts.csv`

**TODO:** The Universo BSON export contains duplicate DOIs (likely multiple records sharing the same DOI, e.g. preprint and published version, or records merged from different source collections). The current behavior is "last one wins" — when duplicates exist, the last BSON document with that DOI overwrites earlier ones in the index. Investigate whether this causes incorrect abstract matches and whether deduplication should prefer a specific record (e.g. the one with the longest abstract, or the most recent).

## Abstract Harvesting

The `feature/abstract-harvesting` branch adds the ability to enrich VERSO metadata records with abstracts from OpenAlex and Semantic Scholar. There are three ways to use it:

1. **Inline during fetch** -- Pass `--enrich-abstracts` to `script.py` or `md_script.py`. Abstracts are fetched as part of the main metadata export run.
2. **Standalone enrichment** -- Run `abstract_script.py` against a previously exported `asset_metadata.json`. Useful when you want to enrich metadata that was already fetched without the `--enrich-abstracts` flag.
3. **BSON import** -- Run `import_abstracts.py` to match abstracts from a Universo BSON export to VERSO records. Useful when abstracts have already been harvested into a separate database.

### Provider Cascade

When enriching via API (options 1 and 2 above), `try_providers()` queries sources in this order and returns on the first successful match:

1. OpenAlex -- DOI lookup
2. OpenAlex -- title search
3. Semantic Scholar -- DOI lookup
4. Semantic Scholar -- title match

Each step uses fuzzy title matching (`rapidfuzz` `token_set_ratio`, default threshold 90) to verify that the returned paper matches the query. If all four steps fail or return low-confidence matches, the record is left without an abstract and marked `no_match` in the output.

## Directory Structure

| Directory | Contents | Written By |
|---|---|---|
| `A/` | Downloaded PDF files, named `{assetId}.pdf` or `{assetId}_{n}.pdf` | `script.py` only |
| `B/` | `pdf_metadata.csv` -- human-readable metadata | `script.py`, `md_script.py` |
| `C/` | Timestamped subdirectories containing `asset_metadata.json`, `logs.log`, and enrichment CSV outputs (`abstract_metadata.csv`, `imported_abstracts.csv`) | All scripts |

All three directories are gitignored.

## Provider Modules

The `providers/` package contains the enrichment logic. Key modules:

- **`providers/openalex.py`** -- OpenAlex API client. Functions: `reconstruct_abstract()`, `lookup_by_doi()`, `search_by_title()`. Includes a circuit breaker for 429 (rate-limit) responses.
- **`providers/s2.py`** -- Semantic Scholar API client. Functions: `lookup_by_doi()`, `match_by_title()`.
- **`providers/harvester.py`** -- Cascade orchestrator and fuzzy title matching. Functions: `title_match_score()`, `title_matches()`, `try_providers()`.
- **`providers/enrich.py`** -- Shared enrichment helpers. Functions: `extract_identifiers()`, `should_skip()`, `enrich_final_output()`.
