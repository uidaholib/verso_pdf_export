# Phase 2 Implementation Plan: Standalone Enrichment Script (`abstract_script.py`)

**Scope:** `abstract_script.py` and `tests/test_abstract_script.py` — reads a prior
run's `asset_metadata.json`, enriches records with abstracts via the provider cascade,
outputs CSV + log to a timestamped `C/` directory.

**Spec reference:** `_SPEC.md` — Phase 2 (Step 2.1)

**Branch:** `feature/abstract-harvesting` (continuing from Phase 0-1)

**No new dependencies required** — `pandas`, `tqdm`, `requests`, and `argparse` (stdlib)
are already available.

---

## Design decisions made during planning

| Decision | Choice | Why |
|----------|--------|-----|
| Input path | CLI positional argument via `argparse` | Avoids editing source between runs (deviation from spec's hardcoded `METADATA_JSON_PATH`) |
| Debug mode | `--debug` CLI flag (limits to 5 records) | Cleaner than hardcoded `DEBUG_MODE` config var (spec deviation) |
| Output location | `C/{timestamp}/` only (CSV + log together) | Keeps runs isolated, avoids overwriting (spec had `B/abstract_metadata.csv`) |
| `main(argv)` signature | Accepts optional `argv` parameter | Enables testing without monkeypatching `sys.argv` (spec had `main()` with no args) |
| `should_skip(record, skip_types)` | Takes `skip_types` parameter | More testable than reading module-level constant (spec had `should_skip(record)`) |
| `enrich_records` signature | Adds `skip_types` parameter | Passes through to `should_skip` for consistency |
| Error handling in `load_metadata` | Raises `ValueError` (caller catches and exits) | Better separation of concerns than direct `sys.exit()` — departs from existing scripts |
| `load_metadata` validation | Unwraps `{"records": [...]}` wrapper, warns if `totalRecordCount` mismatches | `asset_metadata.json` is NOT a bare list — it has `totalRecordCount` + `records` keys |
| `should_skip` abstract check | Only skips if abstract value string is non-empty | `[{"value": ""}]` or `[{}]` treated as "no abstract" — enrich these records |

**Known limitation:** No partial-progress recovery. If the script crashes mid-enrichment,
all progress is lost. Checkpointing is deferred as YAGNI for this phase.

---

## Step 1 — `load_metadata()`

**Test first** in `tests/test_abstract_script.py` (uses `tmp_path` fixture):

| # | Given | When | Then |
|---|-------|------|------|
| 1 | Valid JSON `{"totalRecordCount": 2, "records": [{...}, {...}]}` | `load_metadata(path)` | Returns list of 2 dicts |
| 2 | File does not exist | `load_metadata("nonexistent.json")` | Raises `ValueError` with clear message |
| 3 | File contains invalid JSON | `load_metadata(path)` | Raises `ValueError` |
| 4 | File is empty | `load_metadata(path)` | Raises `ValueError` |
| 5 | File contains a bare list (not wrapped) | `load_metadata(path)` | Raises `ValueError` — expects `{"records": [...]}` |
| 6 | `totalRecordCount` doesn't match `len(records)` | `load_metadata(path)` | Returns records but logs a warning |
| 7 | JSON object missing `records` key | `load_metadata(path)` | Raises `ValueError` |

**Implement** in `abstract_script.py`:
- `load_metadata(path: str) -> list[dict]` — opens file, parses JSON, validates it's a
  dict with a `records` key containing a list, warns on count mismatch, returns
  `data["records"]`. Raises `ValueError` on any failure.

**Verify:** `pytest tests/test_abstract_script.py -v` — all green.

---

## Step 2 — `extract_identifiers()`

**Test first** (add to `tests/test_abstract_script.py`, uses `sample_esploro_record`
fixture from `conftest.py`):

| # | Given | When | Then |
|---|-------|------|------|
| 1 | Record with DOI, title, assetId (int), resourceType | `extract_identifiers(record)` | Returns `("12345678", "10.1234/example.2023", "A Sample...", "journal_article")` — assetId converted to string |
| 2 | Record missing `identifier.doi` key | `extract_identifiers(record)` | Returns `(id, "", title, type)` |
| 3 | Record missing `title` key | `extract_identifiers(record)` | Returns `(id, doi, "", type)` |
| 4 | Record missing `resourceType` key | `extract_identifiers(record)` | Returns `(id, doi, title, "")` |
| 5 | Record missing `originalRepository` key entirely | `extract_identifiers(record)` | Returns `("", doi, title, type)` |
| 6 | `assetId` is already a string | `extract_identifiers(record)` | Returns it as-is (no double conversion) |

**Implement** in `abstract_script.py`:
- `extract_identifiers(record: dict) -> tuple[str, str, str, str]` — returns
  `(asset_id, doi, title, asset_type)`. Converts `assetId` to string. Uses `.get()`
  with empty-string defaults for all optional fields. Handles missing
  `originalRepository` gracefully.

**Verify:** `pytest tests/test_abstract_script.py -v` — all green.

---

## Step 3 — `should_skip()`

**Test first** (add to `tests/test_abstract_script.py`):

| # | Given | When | Then |
|---|-------|------|------|
| 1 | Record with `description.abstract: [{"value": "Some text"}]` | `should_skip(record, skip_types)` | `True` |
| 2 | Record with `description.abstract: []` (empty list) | `should_skip(...)` | `False` |
| 3 | Record with `description.abstract: [{"value": ""}]` (empty value) | `should_skip(...)` | `False` — empty string is not a real abstract |
| 4 | Record with `description.abstract: [{}]` (missing value key) | `should_skip(...)` | `False` — no usable abstract |
| 5 | Record with no `description.abstract` key | `should_skip(...)` | `False` |
| 6 | Record with `resourceType: "ETD-Doctoral"` | `should_skip(record, ["ETD-Doctoral", "ETD-Masters"])` | `True` |
| 7 | Record with `resourceType: "ETD-Masters"` | `should_skip(...)` | `True` |
| 8 | Record with `resourceType: "journal_article"`, no abstract | `should_skip(...)` | `False` |

**Implement** in `abstract_script.py`:
- `should_skip(record: dict, skip_types: list[str]) -> bool` — returns `True` if:
  - `description.abstract` is a non-empty list AND the first element has a non-empty
    `value` string, OR
  - `resourceType` is in `skip_types`

**Verify:** `pytest tests/test_abstract_script.py -v` — all green.

---

## Step 4 — `enrich_records()`

**Test first** (add to `tests/test_abstract_script.py`, mocks
`providers.harvester.try_providers` via `monkeypatch`):

| # | Given | When | Then |
|---|-------|------|------|
| 1 | 3 records, provider returns abstracts for 2 | `enrich_records(records, ...)` | Returns 3 result dicts; 2 have abstract + harvest_status="ok", 1 has harvest_status="no_match" |
| 2 | Record with existing abstract (should_skip=True) | `enrich_records(...)` | harvest_status="skipped_existing_abstract", `try_providers` NOT called |
| 3 | Record with ETD type (should_skip=True) | `enrich_records(...)` | harvest_status="skipped_etd", `try_providers` NOT called |
| 4 | Record with no DOI and no title | `enrich_records(...)` | harvest_status="no_identifiers", `try_providers` NOT called |
| 5 | Provider returns low_confidence result | `enrich_records(...)` | harvest_status="low_confidence", abstract still included in result |
| 6 | Provider raises unexpected exception | `enrich_records(...)` | harvest_status="error", logs warning, continues to next record |
| 7 | Empty records list | `enrich_records([])` | Returns empty list |
| 8 | Malformed record where extract_identifiers raises | `enrich_records(...)` | harvest_status="error", continues to next record |

**Implement** in `abstract_script.py`:
- `enrich_records(records: list[dict], session, oa_rate: float, s2_rate: float, threshold: int, skip_types: list[str]) -> list[dict]`
- Iterates records with `tqdm` progress bar
- For each record: `extract_identifiers()` → check for no-identifiers →
  `should_skip()` → `try_providers()` if not skipped
- Wraps each record's processing in try/except to continue on unexpected errors
- Returns list of result dicts with keys: `asset_id, doi, title, abstract,
  abstract_source, abstract_external_id, harvest_status, trace`
- Distinguishes skip reasons: `"skipped_existing_abstract"` vs `"skipped_etd"`
  (checks which condition triggered `should_skip`)
- harvest_status values: `"ok"`, `"low_confidence"`, `"no_match"`,
  `"skipped_existing_abstract"`, `"skipped_etd"`, `"no_identifiers"`, `"error"`

**Note:** tqdm progress display is not unit-tested (UI concern). Tested indirectly via
the function returning correct results.

**Verify:** `pytest tests/test_abstract_script.py -v` — all green. No real HTTP calls.

---

## Step 5 — `write_results_csv()`

**Test first** (add to `tests/test_abstract_script.py`, uses `tmp_path` fixture):

| # | Given | When | Then |
|---|-------|------|------|
| 1 | List of result dicts | `write_results_csv(results, path)` | Creates CSV at path |
| 2 | Read generated CSV headers | `pd.read_csv(path)` | Has exactly: `asset_id, doi, title, abstract, abstract_source, abstract_external_id, harvest_status, trace` |
| 3 | Result with `None` abstract | `write_results_csv(...)` | Empty string in abstract column (not `"None"`) |
| 4 | Trace is a list `["oa_doi=miss", "s2_doi=hit"]` | `write_results_csv(...)` | Serialized as `"oa_doi=miss;s2_doi=hit"` |
| 5 | Empty results list | `write_results_csv([])` | Creates CSV with header row only |
| 6 | Abstract containing commas and newlines | `write_results_csv(...)` | Properly escaped in CSV (pandas handles this) |

**Implement** in `abstract_script.py`:
- `write_results_csv(results: list[dict], path: str) -> None` — converts `trace` lists
  to semicolon-joined strings, replaces `None` values with empty string, writes via
  `pandas.DataFrame.to_csv()`.

**Verify:** `pytest tests/test_abstract_script.py -v` — all green.

---

## Step 6 — `parse_args()` and `main()`

**Test first** (add to `tests/test_abstract_script.py`):

| # | Given | When | Then |
|---|-------|------|------|
| 1 | `parse_args(["path/to/metadata.json"])` | Parse | Returns args with `metadata_path="path/to/metadata.json"`, `debug=False` |
| 2 | `parse_args(["path.json", "--debug"])` | Parse | Returns args with `debug=True` |
| 3 | `parse_args([])` | Parse | Raises `SystemExit` (required positional arg) |
| 4 | main() with --debug and 10 records | Mock `load_metadata` returning 10 records | Only first 5 passed to `enrich_records()` |
| 5 | main() happy path | Mock all I/O functions | Calls load_metadata → enrich_records → write_results_csv in order |
| 6 | main() creates timestamped C/ directory | Check after mocked run | Directory exists with format `C/YYYY-MM-DD_HH-MM-SS/` |
| 7 | main() sets up log file | Check after mocked run | `logs.log` created in C/{timestamp}/ |
| 8 | main() with bad metadata path | `main(["nonexistent.json"])` | Catches `ValueError`, calls `sys.exit()` |
| 9 | main() with no env vars for rates | Unset `OPENALEX_RATE_INTERVAL` and `S2_RATE_INTERVAL` | Uses defaults (0.1 and 1.0) |
| 10 | main() with custom env var rates | Set `OPENALEX_RATE_INTERVAL=0.5` | Passes 0.5 to `enrich_records()` |

**Implement** in `abstract_script.py`:
- `parse_args(argv: list[str] | None = None) -> argparse.Namespace` — positional
  `metadata_path`, optional `--debug` flag
- `main(argv: list[str] | None = None)` — full orchestrator:
  1. `parse_args(argv)`
  2. `load_dotenv()`
  3. Create `C/{timestamp}/` directory
  4. Setup dual logging (file handler at INFO → `C/{timestamp}/logs.log`, console
     handler at WARNING)
  5. Try `load_metadata(args.metadata_path)` — catch `ValueError` and `sys.exit()`
     with the error message
  6. If `--debug`, slice to first `DEBUG_SUBSET_SIZE` (5) records, log which mode
     is active
  7. Create `requests.Session()`
  8. Read rate intervals from env: `OPENALEX_RATE_INTERVAL` (default `0.1`),
     `S2_RATE_INTERVAL` (default `1.0`)
  9. `enrich_records(records, session, oa_rate, s2_rate, FUZZY_THRESHOLD,
     ASSET_TYPES_TO_SKIP)`
  10. `write_results_csv(results, f"C/{timestamp}/abstract_metadata.csv")`
  11. Print summary: total processed, enriched (ok + low_confidence), skipped,
      no_match, errors
- `if __name__ == "__main__": main()`

**Verify:** `pytest tests/test_abstract_script.py -v` — all green. Then manual smoke
test: `python abstract_script.py C/{some_timestamp}/asset_metadata.json --debug` —
processes 5 records, creates CSV + log in `C/{new_timestamp}/`.

---

## Module-level constants (in `abstract_script.py`)

```python
FUZZY_THRESHOLD = 90
ASSET_TYPES_TO_SKIP = ["ETD-Doctoral", "ETD-Masters"]
DEBUG_SUBSET_SIZE = 5
```

---

## Exit checklist

- [ ] `pytest tests/test_abstract_script.py -v` passes with zero failures
- [ ] `pytest --collect-only` finds tests in `test_abstract_script.py`
- [ ] `python abstract_script.py --help` shows usage with positional arg and --debug flag
- [ ] `python abstract_script.py C/{timestamp}/asset_metadata.json --debug` runs without error on real metadata
- [ ] Output CSV at `C/{new_timestamp}/abstract_metadata.csv` has correct 8 columns
- [ ] Log file created at `C/{new_timestamp}/logs.log`
- [ ] No `import asyncio` or `import httpx` in `abstract_script.py`
- [ ] `abstract_script.py` uses `logging.getLogger(__name__)` — no handler configuration outside `main()`
- [ ] Skipped records (existing abstract, ETDs) do not call `try_providers()`
- [ ] Records with no DOI and no title get harvest_status="no_identifiers"
- [ ] Records with empty abstract values (`[{"value": ""}]`, `[{}]`) are enriched, not skipped
- [ ] `--debug` limits processing to 5 records
- [ ] `load_metadata()` raises `ValueError` (not `sys.exit()`) — `main()` catches and exits
- [ ] `totalRecordCount` mismatch produces a warning, not an error
