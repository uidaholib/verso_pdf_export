# Phase 3 Implementation Plan: One-Time BSON Import (`import_abstracts.py`)

**Scope:** `import_abstracts.py` and `tests/test_import_abstracts.py` — reads a
Universo BSON export (`unique_documents.bson`), matches pre-harvested abstracts
to VERSO asset metadata records by DOI + fuzzy title, outputs a CSV for review.

**Spec reference:** `_SPEC.md` — Phase 3 (Step 3.1)

**Branch:** `feature/abstract-harvesting` (continuing from Phase 2)

**No new dependencies required** — `pymongo` (provides `bson`), `pandas`,
`tqdm`, `rapidfuzz`, and `argparse` (stdlib) are already in `requirements.txt`.

**Important:** The `bson` module comes from the `pymongo` package. Do NOT install
the standalone `bson` PyPI package — they conflict. This is already noted in the
spec's Phase 5 exit checklist.

---

## Design decisions made during planning

| Decision | Choice | Why |
|----------|--------|-----|
| Error handling | `ValueError` (caller catches → `sys.exit`) | Consistent with Phase 2's `load_metadata` — better separation of concerns |
| BSON filter | Require both non-empty `abstract` AND non-empty `abstract_source` | Strictest option; ensures provenance tracking for every imported abstract |
| CLI interface | `argparse` with two positional args | Consistent with Phase 2 (spec deviation); no source editing between runs |
| Output location | `C/{timestamp}/` (not `B/`) | Consistent with Phase 2; keeps runs isolated with CSV + log together |
| Ambiguous title matches | Best score wins, log warning if 2nd-best within 2 points | Pragmatic: doesn't block matches but flags potential issues for review |
| `load_verso_records` vs reusing `load_metadata` | Separate function | Different return shape (3 flat fields vs raw Esploro record); justifies independent code |
| Title match performance | Naive O(n×m) with tqdm progress | rapidfuzz is C-backed; 26k × 4k ≈ 100M comparisons is feasible. Optimize later if needed |
| Fuzzy matching import | Import `title_match_score` from `providers.harvester` | Single source of truth; the side-effect of loading HTTP provider modules is harmless |
| BSON `None` values | Coerce `None` to `""` for `title`, `identifier_doi`, `abstract_external_id` | `dict.get("key", "")` only defaults when key is absent; explicit `None` must also be handled |

---

## Step 0 — Add `write_bson_file` helper to `tests/conftest.py`

**Modify:** `tests/conftest.py`

Add a shared fixture that writes a list of dicts as a BSON file to `tmp_path`.
Multiple Step 1 tests need to create BSON fixture files, and duplicating the
`bson.encode()` + concatenate + write pattern in every test would be noisy.

```python
@pytest.fixture
def write_bson_file(tmp_path):
    """Write a list of dicts as a multi-document BSON file."""
    def _write(docs, filename="test.bson"):
        import bson
        path = tmp_path / filename
        with open(path, "wb") as f:
            for doc in docs:
                f.write(bson.encode(doc))
        return str(path)
    return _write
```

**Verify:** `pytest --collect-only` — fixture is available, no regressions.

---

## Step 1 — `parse_bson_abstracts()`

**Test first** in `tests/test_import_abstracts.py` (uses `write_bson_file` and
`tmp_path` fixtures):

| # | Given | When | Then |
|---|-------|------|------|
| 1 | BSON with 3 docs: 2 have abstract+source, 1 missing abstract | `parse_bson_abstracts(path)` | Returns 2 dicts |
| 2 | BSON doc with empty abstract `""` | `parse_bson_abstracts(path)` | Doc excluded |
| 3 | BSON doc with abstract but missing `abstract_source` key entirely | `parse_bson_abstracts(path)` | Doc excluded (require both) |
| 4 | BSON doc with abstract but empty `abstract_source` `""` | `parse_bson_abstracts(path)` | Doc excluded |
| 5 | File does not exist | `parse_bson_abstracts("nonexistent.bson")` | Raises `ValueError` with path in message |
| 6 | Empty BSON file (0 bytes) | `parse_bson_abstracts(path)` | Returns empty list, logs warning |
| 7 | BSON doc missing `identifier_doi` key entirely | `parse_bson_abstracts(path)` | Included, DOI defaults to `""` |
| 8 | BSON doc with `title: None` (explicit null) | `parse_bson_abstracts(path)` | Included, title coerced to `""` |
| 9 | BSON doc with `abstract` key absent (not just empty) | `parse_bson_abstracts(path)` | Doc excluded |
| 10 | Returned dict shape | Check any result dict | Has exactly: `abstract`, `abstract_source`, `abstract_external_id`, `identifier_doi`, `title` |
| 11 | Truncated/corrupt BSON file | `parse_bson_abstracts(path)` | Raises `ValueError` with descriptive message |

**Implement** in `import_abstracts.py`:
- `parse_bson_abstracts(filepath: str) -> list[dict]`
- Opens file in binary mode, iterates via `bson.decode_file_iter()`
- Filters: non-empty `abstract` AND non-empty `abstract_source`
- Extracts per doc: `abstract`, `abstract_source`, `abstract_external_id`
  (default `""`), `identifier_doi` (default `""`), `title` (default `""`)
- Coerces `None` values to `""` for optional string fields (BSON `null` ≠ key
  absence — `dict.get("title", "")` won't catch explicit `None`)
- Raises `ValueError` if file not found or if BSON decoding fails
- Logs warning if file contains zero documents

**Verify:** `pytest tests/test_import_abstracts.py -v` — all green.

---

## Step 2 — `build_doi_index()`

**Test first** (add to `tests/test_import_abstracts.py`):

| # | Given | When | Then |
|---|-------|------|------|
| 1 | 3 docs with distinct DOIs | `build_doi_index(docs)` | Dict with 3 entries, keys lowercase |
| 2 | DOI `"10.1/ABC"` in index | Lookup `"10.1/abc"` | Match found (case-insensitive) |
| 3 | DOI with leading/trailing whitespace `" 10.1/x "` | `build_doi_index(docs)` | Stripped, stored as `"10.1/x"` |
| 4 | Doc with empty DOI `""` | `build_doi_index(docs)` | Not included in index |
| 5 | Two docs with same DOI (different case) | `build_doi_index(docs)` | Last one wins (dict overwrite), logs warning |
| 6 | Empty list | `build_doi_index([])` | Returns empty dict |

**Implement** in `import_abstracts.py`:
- `build_doi_index(docs: list[dict]) -> dict[str, dict]`
- Keys: `doc["identifier_doi"].strip().lower()`
- Skips empty DOIs
- Logs warning on duplicate DOIs (collision after normalization)

**Verify:** `pytest tests/test_import_abstracts.py -v` — all green.

---

## Step 3 — `load_verso_records()`

**Test first** (add to `tests/test_import_abstracts.py`, uses `tmp_path`):

| # | Given | When | Then |
|---|-------|------|------|
| 1 | Valid `asset_metadata.json` with 3 records | `load_verso_records(path)` | Returns 3 dicts, each with `asset_id`, `doi`, `title` |
| 2 | File does not exist | `load_verso_records("nonexistent.json")` | Raises `ValueError` |
| 3 | Invalid JSON | `load_verso_records(path)` | Raises `ValueError` |
| 4 | Missing `"records"` key | `load_verso_records(path)` | Raises `ValueError` |
| 5 | Record with no DOI (`identifier.doi` absent) | `load_verso_records(path)` | Returns record with `doi=""` |
| 6 | Record with int `assetId` | `load_verso_records(path)` | `asset_id` converted to string |
| 7 | DOI normalized (lowercase, stripped) | `load_verso_records(path)` | `doi` is lowercase and trimmed |
| 8 | Record missing `originalRepository` key entirely | `load_verso_records(path)` | `asset_id=""` |
| 9 | Record missing `title` key | `load_verso_records(path)` | `title=""` |

**Implement** in `import_abstracts.py`:
- `load_verso_records(path: str) -> list[dict]`
- Reads JSON, validates `records` key exists (same pattern as `abstract_script.py`'s `load_metadata`)
- Extracts per record: `asset_id` (str), `doi` (lowercase, stripped), `title`
- Raises `ValueError` on file/parse/validation errors
- Does NOT reuse `abstract_script.load_metadata` — different return shape
  (3 flat fields vs full Esploro record dict)

**Verify:** `pytest tests/test_import_abstracts.py -v` — all green.

---

## Step 4 — `match_records()`

**Test first** (add to `tests/test_import_abstracts.py`):

| # | Given | When | Then |
|---|-------|------|------|
| 1 | VERSO record DOI matches BSON index | `match_records(...)` | Matched with `match_method="doi"`, `match_score=100.0` |
| 2 | VERSO DOI not in index, title fuzzy match ≥ threshold | `match_records(...)` | Matched with `match_method="title"`, `match_score=<actual>` |
| 3 | VERSO DOI not in index, title below threshold | `match_records(...)` | Not in matched list |
| 4 | VERSO record with no DOI and no title | `match_records(...)` | Skipped (not in results) |
| 5 | Multiple BSON docs match same VERSO title, scores differ by >2 | `match_records(...)` | Best score wins, no warning |
| 6 | Multiple BSON docs match same VERSO title, scores within 2 points | `match_records(...)` | Best score wins, warning logged |
| 7 | Empty BSON docs list | `match_records([], verso, 90)` | Returns empty list |
| 8 | Empty VERSO records list | `match_records(bson, [], 90)` | Returns empty list |
| 9 | VERSO record already DOI-matched | `match_records(...)` | Appears once (not duplicated by title pass) |
| 10 | Returned dict shape | Check any match dict | Has exactly: `asset_id`, `verso_doi`, `verso_title`, `abstract`, `abstract_source`, `abstract_external_id`, `match_method`, `match_score` |

**Implement** in `import_abstracts.py`:
- `match_records(bson_docs: list[dict], verso_records: list[dict], threshold: int) -> list[dict]`
- Builds DOI index via `build_doi_index(bson_docs)`
- **Phase 1 — DOI matching:** For each VERSO record with a DOI, check index.
  If hit, emit match with `match_method="doi"`, `match_score=100.0`. Track
  matched VERSO indices in a set.
- **Phase 2 — Title matching:** For unmatched VERSO records that have a title,
  scan all BSON docs using `title_match_score()` from `providers.harvester`.
  Track best and second-best scores. If best ≥ threshold, emit match with
  `match_method="title"`, `match_score=<score>`. If second-best is within
  2 points of best, log warning with both titles and scores.
- Uses `tqdm` for progress over the title-matching phase (the slow part)
- Returns list of match dicts with the 8 columns from the spec

**Note on performance:** Title matching is O(unmatched_verso × bson_docs).
With ~26k BSON docs and potentially a few thousand unmatched VERSO records,
this is feasible because `rapidfuzz` is C-backed. If it's slow in practice,
`rapidfuzz.process.extractOne` is a drop-in optimization for a later phase.

**Verify:** `pytest tests/test_import_abstracts.py -v` — all green.

---

## Step 5 — `write_import_csv()`

**Test first** (add to `tests/test_import_abstracts.py`, uses `tmp_path`):

| # | Given | When | Then |
|---|-------|------|------|
| 1 | List of match dicts | `write_import_csv(matches, path)` | Creates CSV at path |
| 2 | CSV headers | Read generated CSV | Has exactly 8 columns: `asset_id, verso_doi, verso_title, abstract, abstract_source, abstract_external_id, match_method, match_score` |
| 3 | Empty matches list | `write_import_csv([], path)` | Creates CSV with header row only |
| 4 | Abstract with commas and newlines | `write_import_csv(...)` | Properly escaped (pandas handles this) |
| 5 | `None` values in match dict | `write_import_csv(...)` | Written as empty string, not `"None"` |

**Implement** in `import_abstracts.py`:
- `write_import_csv(matches: list[dict], path: str) -> None`
- Replaces `None` with empty string
- Uses `pandas.DataFrame` with explicit column order matching spec
- Writes via `df.to_csv(path, index=False, encoding="utf-8")`

**Verify:** `pytest tests/test_import_abstracts.py -v` — all green.

---

## Step 6 — `parse_args()` and `main()`

**Test first** (add to `tests/test_import_abstracts.py`):

| # | Given | When | Then |
|---|-------|------|------|
| 1 | `parse_args(["data.bson", "meta.json"])` | Parse | Returns args with `bson_path` and `metadata_path` |
| 2 | `parse_args(["data.bson"])` | Parse | Raises `SystemExit` (missing required arg) |
| 3 | `parse_args([])` | Parse | Raises `SystemExit` |
| 4 | `parse_args(["a.bson", "b.json", "--threshold", "85"])` | Parse | `threshold=85` |
| 5 | `main()` happy path | Mock all I/O functions | Calls parse_bson → load_verso → match → write in order |
| 6 | `main()` with bad BSON path | `parse_bson_abstracts` raises ValueError | Catches, calls `sys.exit()` |
| 7 | `main()` with bad metadata path | `load_verso_records` raises ValueError | Catches, calls `sys.exit()` |
| 8 | `main()` creates timestamped `C/` directory | Check after mocked run | Directory exists with format `C/YYYY-MM-DD_HH-MM-SS/` |
| 9 | `main()` sets up log file | Check after mocked run | `logs.log` created in `C/{timestamp}/` |
| 10 | `main()` summary stats | Mock match returning 3 DOI + 2 title matches | Prints total, DOI-matched, title-matched, unmatched counts |

**Implement** in `import_abstracts.py`:
- `parse_args(argv: list[str] | None = None) -> argparse.Namespace`
  - Two positional args: `bson_path`, `metadata_path`
  - Optional `--threshold` (default `90`, type `int`)
- `main(argv: list[str] | None = None) -> None`
  1. `parse_args(argv)`
  2. Create `C/{timestamp}/` directory
  3. Setup dual logging (file handler → `C/{timestamp}/logs.log` at INFO,
     console handler at WARNING) — same pattern as `abstract_script.py`
  4. Try `parse_bson_abstracts(args.bson_path)` — catch `ValueError`, `sys.exit()`
  5. Log count: `"Parsed N BSON docs with abstracts"`
  6. Try `load_verso_records(args.metadata_path)` — catch `ValueError`, `sys.exit()`
  7. Log count: `"Loaded N VERSO records"`
  8. `match_records(bson_docs, verso_records, args.threshold)`
  9. `write_import_csv(matches, f"C/{timestamp}/imported_abstracts.csv")`
  10. Print summary: total BSON docs with abstracts, total VERSO records,
      matched (DOI count + title count breakdown), unmatched count
- `if __name__ == "__main__": main()`

**Module-level constants:**
```python
FUZZY_THRESHOLD = 90  # default, overridable via --threshold CLI arg
```

**Note:** No `load_dotenv()` call needed — this script makes no API calls and
reads no `.env` variables.

**Verify:** `pytest tests/test_import_abstracts.py -v` — all green. Then manual
smoke test: `python import_abstracts.py 2026_06_10_universo_export/unique_documents.bson C/{timestamp}/asset_metadata.json` — processes real data, outputs CSV + log.

---

## Exit checklist

- [ ] `pytest tests/test_import_abstracts.py -v` passes with zero failures
- [ ] `pytest --collect-only` finds tests in `test_import_abstracts.py`
- [ ] `python import_abstracts.py --help` shows usage with two positional args and `--threshold`
- [ ] `python import_abstracts.py <bson_path> <metadata_path>` runs on real data without error
- [ ] Output CSV at `C/{timestamp}/imported_abstracts.csv` has correct 8 columns
- [ ] Log file created at `C/{timestamp}/logs.log`
- [ ] No `import asyncio` or `import httpx` in `import_abstracts.py`
- [ ] `import_abstracts.py` makes NO HTTP calls
- [ ] `import_abstracts.py` uses `logging.getLogger(__name__)` — no handler config outside `main()`
- [ ] DOI matching is case-insensitive and strips whitespace
- [ ] BSON docs missing `abstract_source` are excluded (require both abstract + source)
- [ ] BSON docs with explicit `None` for `title`/`identifier_doi` handled (coerced to `""`)
- [ ] Ambiguous title matches (2nd-best within 2 points) logged as warnings
- [ ] Records with no DOI and no title are skipped
- [ ] `write_bson_file` fixture added to `tests/conftest.py`
- [ ] Corrupt/truncated BSON files raise `ValueError`
