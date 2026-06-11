# Implementation Plan: Abstract Harvesting for verso_pdf_export

## Context

**Why:** The verso_pdf_export tool exports PDFs and metadata from U of I's VERSO repository, but the metadata often lacks abstracts. The Universo project already has a working abstract harvester (OpenAlex + Semantic Scholar) that has been run against prod data. We want to: (1) import those already-harvested abstracts via a one-time BSON import, and (2) add ongoing enrichment so future exports can fetch abstracts on the fly.

**Source code to port from:** `universo/backend/app/services/` — specifically `openalex_service.py`, `semantic_scholar_service.py`, and `abstract_harvester_service.py`. These are async (httpx + asyncio); we're porting to sync (requests) to match verso_pdf_export's style.

**Outcome:** Three new capabilities in verso_pdf_export:
1. `import_abstracts.py` — one-time script to ingest pre-harvested abstracts from a Universo BSON export
2. `abstract_script.py` — standalone script to enrich VERSO metadata with abstracts from external APIs
3. `ENRICH_ABSTRACTS` flag in `script.py` / `md_script.py` — inline enrichment during regular exports

---

## Architecture

```
providers/
  openalex.py ───────┐
  s2.py ─────────────┤
  harvester.py ──────┤   (shared library — all sync, plain functions)
                     │
                     ├──> abstract_script.py   (Deliverable 2)
                     ├──> import_abstracts.py   (Deliverable 1 — uses only harvester.py for fuzzy matching)
                     └──> script.py / md_script.py  (Deliverable 3)
```

### Design decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Sync vs async | Sync (requests) | Matches existing codebase; simpler for the team; batch sizes <4k don't need concurrency |
| File layout | `providers/` package | User preference; keeps provider code namespaced |
| Rate limiting | `time.sleep(interval)` between calls | Matches existing pattern (script.py:103); no threading.Lock needed for single-threaded code |
| Classes vs functions | Plain functions + module-level constants | Matches existing codebase (zero classes in script.py/md_script.py) |
| Circuit breaker | Yes, for OpenAlex 429s | Prevents burning ~48s/record when throttled; only ~15 lines |
| ETD handling | Skip by default | ETDs unlikely indexed in OpenAlex/S2; saves ~2,000 wasted API calls |
| `reconstruct_abstract()` | Inside `openalex.py` | Only used for OpenAlex responses; doesn't warrant its own file |
| `title_matches()` | Inside `harvester.py` | Only used in the cascade orchestrator |

---

## File tree at completion

```
verso_pdf_export/
  script.py                  (modified: +ENRICH_ABSTRACTS flag, +import)
  md_script.py               (modified: same)
  abstract_script.py         (new: standalone enrichment)
  import_abstracts.py        (new: one-time BSON import)
  requirements.txt           (modified: +rapidfuzz, +pymongo, +pytest, +responses, +pytest-cov)
  setup.md                   (modified: document new .env vars)
  providers/
    __init__.py
    openalex.py              (OA client + reconstruct_abstract)
    s2.py                    (S2 client)
    harvester.py             (cascade orchestrator + title_matches)
    enrich.py                (shared enrichment helpers)
  tests/
    __init__.py
    conftest.py              (shared fixtures)
    test_openalex.py
    test_s2.py
    test_harvester.py
    test_abstract_script.py
    test_import_abstracts.py
    test_enrich.py
    test_integration.py
```

---

## Phase 0: Foundation

### Step 0.1 — Test infrastructure and dependencies

**Modify:** `requirements.txt`

Add:
```
rapidfuzz>=3.0.0
# pymongo provides bson.decode_file_iter for mongodump files; do NOT install standalone 'bson' package
pymongo>=4.0.0
pytest>=7.0.0
responses>=0.23.0
```

**Create:** `providers/__init__.py` (empty), `tests/__init__.py` (empty), `tests/conftest.py` (minimal, will hold shared fixtures)

**Verify:** `pip install -r requirements.txt && pytest --collect-only` — installs cleanly, finds 0 tests.

---

## Phase 1: Provider Modules (TDD)

### Step 1.1 — OpenAlex client (`providers/openalex.py`)

**Port from:** `universo/backend/app/services/openalex_service.py`

**Functions to implement:**
- `reconstruct_abstract(inverted_index: dict | None) -> str` — converts OpenAlex inverted-index format to plain text. Pure function, no I/O.
- `lookup_by_doi(session: requests.Session, doi: str, rate_interval: float) -> dict | None` — `GET https://api.openalex.org/works/doi:{doi}`. Returns `{"abstract", "matched_title", "external_id", "source": "openalex"}` or `None`.
- `search_by_title(session: requests.Session, title: str, rate_interval: float) -> dict | None` — `GET https://api.openalex.org/works?search={title}&per_page=1`. Same return shape.

**Config** (module-level constants, loaded from env via `os.environ.get`):
- `OPENALEX_API_KEY` — required, sent as `?api_key=` param (free keys at openalex.org; the `mailto=` polite pool was deprecated Feb 2026)
- `OPENALEX_RATE_INTERVAL` — default `0.1` (credit-based system: singleton lookups = 1 credit, search = ~100 credits, daily free allowance = 100,000 credits, hard cap 100 req/s)

**Error handling:**
- Returns `None` on 404
- Retries up to 3 times on 429/5xx with exponential backoff (`time.sleep(3), time.sleep(15), time.sleep(30)`)
- Also retries on 403 (per-second rate limit) — distinguish from 429 (daily credits exhausted) by checking `X-RateLimit-Remaining` header; if 0, do not retry
- Circuit breaker: after 3 consecutive 429-skips, suspend OA calls for 300s (module-level globals, matching universo pattern)
- Logs warnings on retries and errors via `logging` module

**Test file:** `tests/test_openalex.py` (uses `responses` library to mock HTTP)

**Test matrix:**

| Given | When | Then |
|-------|------|------|
| Valid inverted index `{"the": [0], "quick": [1]}` | `reconstruct_abstract(index)` | Returns `"the quick"` |
| Repeated-position index | `reconstruct_abstract(index)` | Correct word order |
| `None` or `{}` input | `reconstruct_abstract(None)` | Returns `""` |
| Sparse index with gaps | `reconstruct_abstract(index)` | Gap positions skipped |
| API returns 200 with abstract | `lookup_by_doi(s, "10.1/abc", 0.1)` | Returns shaped dict |
| API returns 200 but `abstract_inverted_index` is null | `lookup_by_doi(...)` | Returns `None` |
| API returns 404 | `lookup_by_doi(...)` | Returns `None`, no retry |
| API returns 429 then 200 | `lookup_by_doi(...)` | Returns result after retry |
| API returns 429 three times | `lookup_by_doi(...)` | Returns `None`, logs warning |
| Empty DOI `""` | `lookup_by_doi(s, "", 0.1)` | Returns `None` immediately, no HTTP call |
| `search_by_title` returns results | `search_by_title(s, "My Paper", 0.1)` | Returns shaped dict |
| `search_by_title` empty results | `search_by_title(...)` | Returns `None` |
| API key configured | Any request | URL contains `api_key=...` param |
| 403 (per-second rate limit) then 200 | `lookup_by_doi(...)` | Retries, returns result |
| 429 with `X-RateLimit-Remaining: 0` | `lookup_by_doi(...)` | Does NOT retry (daily credits exhausted), logs warning |

**Verify:** `pytest tests/test_openalex.py -v` — all green, no real HTTP calls.

---

### Step 1.2 — Semantic Scholar client (`providers/s2.py`)

**Port from:** `universo/backend/app/services/semantic_scholar_service.py`

**Functions to implement:**
- `lookup_by_doi(session: requests.Session, doi: str, rate_interval: float) -> dict | None` — `GET https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}?fields=title,abstract,externalIds`
- `match_by_title(session: requests.Session, title: str, rate_interval: float) -> dict | None` — `GET https://api.semanticscholar.org/graph/v1/paper/search/match?query={title}&fields=title,abstract,externalIds`

Return shape: `{"abstract", "matched_title", "external_id", "source": "semantic_scholar"}` or `None`.

**Config:**
- `S2_API_KEY` — optional, sent as `x-api-key` header. Note: unauthenticated users share a 1,000 req/s pool; authenticated users get a guaranteed 1 req/s baseline per key (higher limits available on request). The key gives a stable individual allocation rather than competing in the shared pool.
- `S2_RATE_INTERVAL` — default `1.0` (conservative; safe for both authenticated and unauthenticated use)

**Error handling:** Same retry pattern as OpenAlex (exponential backoff on 429/5xx). Honors `Retry-After` header if present (not guaranteed by S2 docs — use fallback backoff when absent). No circuit breaker (S2 doesn't have the same throttling pattern).

**Future optimization:** S2 offers a batch endpoint (`POST /graph/v1/paper/batch`) that accepts up to 500 DOIs per request. For ~2,000 lookups this would be significantly more efficient. Consider for a later phase.

**Test file:** `tests/test_s2.py`

**Test matrix:**

| Given | When | Then |
|-------|------|------|
| 200 with abstract | `lookup_by_doi(...)` | Returns shaped dict |
| 200 but abstract is null | `lookup_by_doi(...)` | Returns `None` |
| 404 | `lookup_by_doi(...)` | Returns `None` |
| 429 with Retry-After header, then 200 | `lookup_by_doi(...)` | Sleeps for Retry-After seconds, returns result |
| 429 without Retry-After, then 200 | `lookup_by_doi(...)` | Uses fallback schedule |
| `match_by_title` returns match | `match_by_title(...)` | Returns shaped dict (S2 provides `matchScore` in response; can be used alongside fuzzy title matching) |
| API key present | Any request | `x-api-key` header included |
| API key absent | Any request | No `x-api-key` header |
| Empty DOI or title | Either function | Returns `None` immediately |

**Verify:** `pytest tests/test_s2.py -v` — all green.

---

### Step 1.3 — Harvester orchestrator (`providers/harvester.py`)

**Port from:** `universo/backend/app/services/abstract_harvester_service.py` (the `_try_providers` cascade)

**Functions to implement:**
- `title_matches(local: str, candidate: str, threshold: int = 90) -> bool` — fuzzy match via `rapidfuzz.fuzz.token_set_ratio`. Returns `False` if either string is empty.
- `try_providers(session, doi, title, oa_rate, s2_rate, fuzzy_threshold=90) -> tuple[dict | None, str, list[str]]` — cascade: OA DOI → OA title → S2 DOI → S2 title. Returns `(result, reason, trace)` where reason is `"ok"` / `"no_match"` / `"low_confidence"`.

**Test file:** `tests/test_harvester.py` — mocks `providers.openalex.lookup_by_doi` etc. at the function level, not HTTP level.

**Test matrix:**

| Given | When | Then |
|-------|------|------|
| Identical titles | `title_matches("Hello World", "Hello World", 90)` | `True` |
| Case difference | `title_matches("HELLO", "hello", 90)` | `True` |
| Unrelated titles | `title_matches("Quantum Physics", "Cooking Tips", 90)` | `False` |
| Empty local or candidate | `title_matches("", "anything", 90)` | `False` |
| Score exactly at threshold | `title_matches(a, b, threshold)` | `True` (>= comparison) |
| OA DOI hits | `try_providers(...)` | Returns OA result, reason="ok", trace=["oa_doi=hit"] |
| OA DOI miss, S2 DOI hits | `try_providers(...)` | Returns S2 result |
| Both DOI miss, OA title above threshold | `try_providers(...)` | Returns OA title result |
| OA title below threshold, S2 title above | `try_providers(...)` | Returns S2 title result |
| All four miss | `try_providers(...)` | Returns `(None, "no_match", [...])` |
| No DOI, title only | `try_providers(s, "", "Title", ...)` | Skips DOI lookups |
| No DOI, no title | `try_providers(s, "", "", ...)` | Returns `(None, "no_match", [])` immediately |
| OA DOI raises exception | `try_providers(...)` | Logs warning, falls through to S2 |
| All providers raise exceptions | `try_providers(...)` | Returns `(None, "no_match", [...])` |

**Verify:** `pytest tests/test_harvester.py -v` — all green.

---

## Phase 2: Standalone Enrichment Script (Deliverable 2)

### Step 2.1 — `abstract_script.py`

Reads a prior run's `asset_metadata.json`, enriches records with abstracts, outputs results.

**Configuration block** (top of file, matching existing script pattern):
```python
METADATA_JSON_PATH = "C/YYYY-MM-DD_HH-MM-SS/asset_metadata.json"  # user edits this
DEBUG_MODE = False
DF_SUBSET_SIZE = 5
FUZZY_THRESHOLD = 90
ASSET_TYPES_TO_SKIP = ["ETD-Doctoral", "ETD-Masters"]
```

**Functions:**
- `load_metadata(path: str) -> list[dict]` — loads and validates asset_metadata.json. Exits with clear error if file not found.
- `extract_identifiers(record: dict) -> tuple[str, str, str, str]` — returns `(asset_id, doi, title, asset_type)` from a single Esploro API record.
- `should_skip(record: dict) -> bool` — returns True if record already has `description.abstract` or asset type is in skip list.
- `enrich_records(records, session, oa_rate, s2_rate, threshold) -> list[dict]` — main loop with tqdm progress bar. Calls `try_providers()` for each non-skipped record.
- `write_results_csv(results: list[dict], path: str)` — outputs CSV to `B/abstract_metadata.csv`.
- `main()` — orchestrator: load_dotenv, load metadata, create session, enrich, write, print summary.

**Output CSV columns:** `asset_id, doi, title, abstract, abstract_source, abstract_external_id, harvest_status, trace`

**Logging:** Creates `C/{timestamp}/` directory, uses same dual-handler logging pattern as existing scripts (file=INFO, console=WARNING). Uses tqdm for progress.

**Test file:** `tests/test_abstract_script.py`

**Test matrix:**

| Given | When | Then |
|-------|------|------|
| Valid metadata JSON | `load_metadata(path)` | Returns list of record dicts |
| Missing file | `load_metadata("nonexistent.json")` | `sys.exit` with clear error message |
| Record with DOI + title + asset_type | `extract_identifiers(record)` | Returns all four values |
| Record missing DOI | `extract_identifiers(record)` | Returns `("id", "", "title", "type")` |
| Record with existing abstract | `should_skip(record)` | `True` |
| ETD record | `should_skip(record)` | `True` (in skip list) |
| 3 records, providers return abstracts for 2 | `enrich_records(...)` | 2 enriched, 1 marked no_match |
| Record with no DOI and no title | `enrich_records(...)` | Skipped, harvest_status="no_identifiers" |
| Running twice on same metadata | `enrich_records(...)` | Idempotent — same results |
| DEBUG_MODE=True | `main()` | Only processes first 5 records |

**Verify:** `pytest tests/test_abstract_script.py -v` — all green. Then manual smoke test: run `python abstract_script.py` with DEBUG_MODE=True on a real `asset_metadata.json` and check 5 records get processed.

---

## Phase 3: One-Time BSON Import (Deliverable 1)

### Step 3.1 — `import_abstracts.py`

Reads Universo export BSON, matches pre-harvested abstracts to VERSO assets by DOI + fuzzy title.

**Configuration block:**
```python
BSON_FILE_PATH = "unique_documents.bson"       # from Universo export ZIP (flat, no nested dirs)
METADATA_JSON_PATH = "C/YYYY-MM-DD_HH-MM-SS/asset_metadata.json"  # user edits this
FUZZY_THRESHOLD = 90
```

**Functions:**
- `parse_bson_abstracts(filepath: str) -> list[dict]` — reads `bson.decode_file_iter()`, filters to docs with non-empty `abstract` + `abstract_source`. Extracts: `abstract, abstract_source, abstract_external_id, identifier_doi, title`. Exits with clear error if file not found.
- `build_doi_index(docs: list[dict]) -> dict[str, dict]` — DOI-keyed lookup (normalized lowercase, stripped whitespace).
- `load_verso_records(path: str) -> list[dict]` — loads asset_metadata.json, extracts asset_id + DOI + title per record. Exits with clear error if file not found.
- `match_records(bson_docs, verso_records, threshold) -> list[dict]` — DOI match first, then fuzzy title fallback for unmatched. Returns list with `match_method` ("doi" / "title") and `match_score`.
- `write_import_csv(matches: list[dict], path: str)` — outputs `B/imported_abstracts.csv`.
- `main()` — orchestrator with tqdm + logging + summary stats.

**Output CSV columns:** `asset_id, verso_doi, verso_title, abstract, abstract_source, abstract_external_id, match_method, match_score`

**Note:** This script makes NO HTTP calls. It only reads files and does local matching.

**Test file:** `tests/test_import_abstracts.py`

**Test matrix:**

| Given | When | Then |
|-------|------|------|
| BSON doc with abstract + DOI | `parse_bson_abstracts(path)` | Doc included in results |
| BSON doc with empty abstract | `parse_bson_abstracts(path)` | Doc excluded |
| BSON doc missing abstract field entirely | `parse_bson_abstracts(path)` | Doc excluded |
| DOI "10.1/ABC" in index | `build_doi_index` then lookup "10.1/abc" | Match found (case-insensitive) |
| DOI with leading/trailing whitespace | `build_doi_index` | Normalized, matches cleanly |
| DOI not in index | `match_records(...)` | Falls through to title matching |
| Title fuzzy match above threshold | `match_records(...)` | Matched with method="title" |
| Title below threshold | `match_records(...)` | Not matched, reported in summary |
| Empty BSON file (0 documents) | `parse_bson_abstracts(path)` | Returns empty list, logs warning |
| VERSO record with no DOI and no title | `match_records(...)` | Skipped, reported in summary |
| Multiple BSON docs could match same title | `match_records(...)` | Best score wins |
| Missing BSON file | `main()` | `sys.exit` with clear error |
| Missing metadata JSON | `main()` | `sys.exit` with clear error |

**Verify:** `pytest tests/test_import_abstracts.py -v` — all green. For BSON parsing tests, create fixture data using `bson.encode()` in test setup (write to temp file).

---

## Phase 4: Integration into Existing Scripts (Deliverable 3)

### Step 4.1 — Modify `script.py` and `md_script.py`

**Add to configuration block** (top of each script):
```python
ENRICH_ABSTRACTS = False   # Set True to look up abstracts from OpenAlex/Semantic Scholar
ASSET_TYPES_TO_SKIP = ["ETD-Doctoral", "ETD-Masters"]
FUZZY_THRESHOLD = 90
```

**Integration point:** After `make_api_calls()` returns `final_output` and before `generate_metadata_csv()` runs. If `ENRICH_ABSTRACTS = True`:
1. Iterate records in `final_output` that lack `description.abstract`
2. Skip records whose asset type is in `ASSET_TYPES_TO_SKIP`
3. Call `try_providers()` for each via a new helper function
4. Patch the record dict in-memory with abstract fields

**Modify `generate_metadata_csv()`:** Add 3 new columns to the CSV output: `abstract`, `abstract_source`, `abstract_external_id`. When `ENRICH_ABSTRACTS = False`, these columns are present but empty (maintains consistent CSV schema).

**Test file:** `tests/test_integration.py`

**Test matrix:**

| Given | When | Then |
|-------|------|------|
| `ENRICH_ABSTRACTS = False` | Run metadata generation | Output CSV has 26 columns, abstract columns empty |
| `ENRICH_ABSTRACTS = True`, providers return abstracts | Run with mock providers | Abstract columns populated |
| `ENRICH_ABSTRACTS = True`, provider returns None | Run with mock | Those rows have empty abstract columns |
| Existing `description.abstract` in Esploro response | `ENRICH_ABSTRACTS = True` | Keeps Esploro abstract, does not call providers |

**Verify:** `pytest tests/test_integration.py -v`. Also: run `script.py` with `ENRICH_ABSTRACTS = False` and diff output CSV columns against a prior run to confirm no regression.

---

## Phase 5: CLI Consolidation & Documentation

### Step 5.0 — Standardize `abstract_script.py` CLI

Replaced positional `metadata_path` argument with `--metadata` flag. Added `--subset-size` and `--fuzzy-threshold` optional flags with defaults matching other scripts.

### Step 5.1 — Standardize `import_abstracts.py` CLI

Replaced positional arguments with `--bson` and `--metadata` flags. Consistent with the flag-based pattern used across the project.

### Step 5.2 — Consolidate `abstract_script.py`

Removed `enrich_records()` and `_make_result()`. `main()` now calls `enrich_final_output()` from `providers/enrich.py`. Added `merge_enrichment_results()` helper.

### Step 5.3 — Rewrite `README.md`

Rewrote `README.md` with full project documentation and CLI reference.

### Step 5.4 — Update `setup.md`

Added env var documentation (`OPENALEX_API_KEY`, `S2_API_KEY`) and run instructions for `abstract_script.py`, `import_abstracts.py`, and the `--enrich-abstracts` flag.

### Step 5.5 — Update `requirements.txt` comment

Added pymongo/bson namespace conflict warning above `pymongo>=4.0.0` in `requirements.txt`.

---

## New .env variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `OPENALEX_API_KEY` | Recommended | `""` | API key for OpenAlex (free at openalex.org). Unauthenticated requests work but share a 10k-credit/day pool; a key guarantees your own allocation. |
| `S2_API_KEY` | No | `""` | S2 API key (gives guaranteed 1 req/s individual allocation vs shared unauthenticated pool) |

Existing `VERSO_API_KEY` unchanged. All loaded via `python-dotenv` (`load_dotenv()` at script startup).

---

## Verification plan

1. **Unit tests:** `pytest -v` — all tests pass, no real HTTP calls
2. **Smoke test (abstract_script.py):** Run with `DEBUG_MODE=True` on a real `asset_metadata.json` — processes 5 records, outputs CSV
3. **Smoke test (import_abstracts.py):** Run on a real Universo BSON export — matches some records, outputs CSV
4. **Regression test:** Run `script.py` and `md_script.py` with `ENRICH_ABSTRACTS=False` — output CSV matches prior runs (same column count, same data)
5. **Integration test:** Run `md_script.py` with `ENRICH_ABSTRACTS=True` and `DEBUG_MODE=True` on the non-ETD CSV — check that abstract columns appear in output

---

## Exit checklist

- [ ] `pytest` passes with zero failures
- [ ] `pytest --co` finds tests in all 6 test files
- [ ] `python -c "from providers.harvester import try_providers"` succeeds
- [ ] `abstract_script.py` runs in DEBUG_MODE without error on real metadata
- [ ] `import_abstracts.py` runs without error on real BSON export
- [ ] `script.py` with `ENRICH_ABSTRACTS=False` produces same output as before (regression)
- [ ] `md_script.py` with `ENRICH_ABSTRACTS=False` produces same output as before
- [ ] No `import asyncio` or `import httpx` in any new file
- [ ] Every provider function has tests for: success, 404, 429-retry, empty input
- [ ] `.env` variables documented in `setup.md`
- [ ] `pymongo`/`bson` conflict noted in `requirements.txt`
