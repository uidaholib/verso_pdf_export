# Phase 4 Implementation Plan: Integration into Existing Scripts (Deliverable 3)

**Scope:** Modify `script.py` and `md_script.py` to support optional abstract
enrichment during regular exports. Move shared enrichment helpers into
`providers/enrich.py`. Create `tests/test_enrich.py` and
`tests/test_integration.py`.

**Spec reference:** `_SPEC.md` — Phase 4 (Step 4.1)

**Branch:** `feature/abstract-harvesting` (continuing from Phase 3)

**No new dependencies required** — all imports (`requests`, `providers.harvester`,
`tqdm`, `argparse`) are already available.

---

## Design decisions made during planning

| Decision | Choice | Why |
|----------|--------|-----|
| Testability | Add `main()` guard + `parse_args()` to both scripts | Module-level execution prevents import without side effects; `main()` enables testing. Matches pattern in `abstract_script.py` / `import_abstracts.py` |
| CSV columns (spec deviation) | New columns only — don't patch record dict | Avoids ambiguity about data provenance; existing `description` column continues to reflect only Esploro-native data. Spec says "patch the record dict in-memory" — we deviate because separate columns make provenance explicit |
| Column count (spec deviation) | Always 29 columns, even when `ENRICH_ABSTRACTS=False` | Consistent CSV schema is easier for downstream tools. Spec says "26 columns" when off — we deviate to keep schema stable. The 3 new columns are simply empty when enrichment is disabled |
| Code sharing | `extract_identifiers()` and `should_skip()` moved to `providers/enrich.py`; new `enrich_final_output()` also lives there | Single source of truth; `abstract_script.py` imports from `providers.enrich`. Keeps `harvester.py` focused on the provider cascade |
| Config style | Config block defaults at module level + CLI flag overrides via `parse_args()` | Readable defaults + runtime flexibility without editing source |
| `timestamp` global | Move into `main()`; pass as parameter to `make_api_calls()` | Module-level `timestamp` causes side effects on import — set at import time regardless of whether the script actually runs |
| `errors` global | Keep module-level; `errors.clear()` at top of `main()` | Minimal refactor — fully cleaning up error accumulation is orthogonal to enrichment. Known limitation: not ideal for test isolation |
| ETD no-op | Log warning when all records are skipped | `script.py` processes ETDs and `ASSET_TYPES_TO_SKIP` includes ETD types, so `--enrich-abstracts` would skip every record. The behavior is correct; the warning provides visibility |
| `generate_metadata_csv` output path | Add `output_dir` parameter (default `"B"`) | Enables testing with `tmp_path` without writing to project directory |

---

## Step 0 — Move `extract_identifiers()` and `should_skip()` to `providers/enrich.py`

**Depends on:** Phase 2 complete (functions exist in `abstract_script.py`)

**Create:** `providers/enrich.py`

Move `extract_identifiers()` and `should_skip()` from `abstract_script.py` into
`providers/enrich.py`. These functions are unchanged — identical signatures and
behavior.

```python
# providers/enrich.py

def extract_identifiers(record: dict) -> tuple[str, str, str, str]: ...
def should_skip(record: dict, skip_types: list[str]) -> str | None: ...
```

**Modify:** `abstract_script.py`

Replace the local function definitions with imports:
```python
from providers.enrich import extract_identifiers, should_skip
```

**Verification strategy:** Existing tests in `tests/test_abstract_script.py`
continue to pass unchanged — they import through `abstract_script`, which
re-exports from `providers.enrich`.

**Test first** (add `tests/test_enrich.py` — verify the functions are importable
from their new home):

| # | Given | When | Then |
|---|-------|------|------|
| 1 | Valid record | `from providers.enrich import extract_identifiers; extract_identifiers(record)` | Returns `(asset_id, doi, title, asset_type)` — same behavior as before move |
| 2 | Valid record | `from providers.enrich import should_skip; should_skip(record, [])` | Returns `None` or skip reason — same behavior as before move |

**Note:** These are smoke tests to verify the move didn't break anything. The
exhaustive test cases remain in `tests/test_abstract_script.py`.

**Verify:**
```bash
pytest tests/test_enrich.py tests/test_abstract_script.py -v  # all green
python3 -c "from providers.enrich import extract_identifiers, should_skip"
```

---

## Step 1 — Refactor `script.py`: `main()` guard + `parse_args()`

**Depends on:** nothing (independent of Step 0)

**Modify:** `script.py`

Move module-level side effects into `main(argv=None)`:
- `timestamp = datetime.now().strftime(...)` — created inside `main()`, passed
  as parameter to `make_api_calls()`
- `os.makedirs(f'./C/{timestamp}/', ...)` — inside `main()`
- Logging setup (`logging.basicConfig`, console handler) — inside `main()`
- Bottom execution block (`load_data()` → ... → `generate_metadata_csv()`) —
  inside `main()`
- `errors.clear()` at the top of `main()` — reset module-level accumulator

Keep at module level (no side effects):
- Static config constants: `CSV_FILENAME`, `DEBUG_MODE`, `DF_SUBSET_SIZE`
- `errors = []` (module-level accumulator — reset in `main()`)
- Function definitions and imports

Add `parse_args(argv=None) -> argparse.Namespace`:
- `--csv` (default: `CSV_FILENAME`) — path to input CSV
- `--debug` flag (default: `False`)
- `--subset-size` (default: `DF_SUBSET_SIZE`, type `int`)

Parameterize existing functions:
- `load_data(csv_filename)` — instead of reading `CSV_FILENAME` global
- `make_api_calls(df, timestamp, debug_mode=False, subset_size=5)` — instead
  of reading globals. `timestamp` passed explicitly for the output path

Add `if __name__ == "__main__": main()` at bottom.

**Test first** in `tests/test_integration.py`:

| # | Given | When | Then |
|---|-------|------|------|
| 1 | Module import | `import script` | No side effects: no files created, no dirs created, no logging configured |
| 2 | Default args | `script.parse_args([])` | Returns `csv="assetsWithPDFs_just_ETDs.csv"`, `debug=False`, `subset_size=5` |
| 3 | All flags | `script.parse_args(["--csv", "x.csv", "--debug", "--subset-size", "3"])` | Returns correct overrides |
| 4 | `--debug` only | `script.parse_args(["--debug"])` | `debug=True`, others at defaults |

**Verify:**
```bash
pytest tests/test_integration.py -v          # all green
python3 script.py --help                     # shows usage
pytest tests/test_abstract_script.py -v      # no regressions
```

---

## Step 2 — Refactor `md_script.py`: `main()` guard + `parse_args()`

**Depends on:** nothing (independent of Steps 0–1, but follows same pattern)

**Modify:** `md_script.py`

Same refactor as Step 1, adapted for `md_script.py`'s flow:
- `main()` calls `load_data()` → `make_api_calls()` → `generate_file_tasks()` →
  `generate_metadata_csv()` (no `download_asset_files`)
- Same `parse_args` flags, with `--csv` default `"assetsWithPDFs_without_ETD.csv"`
- Same parameter changes to `load_data(csv_filename)` and
  `make_api_calls(df, timestamp, debug_mode, subset_size)`
- Same `errors.clear()` at top of `main()`

**Test first** (add to `tests/test_integration.py`):

| # | Given | When | Then |
|---|-------|------|------|
| 1 | Module import | `import md_script` | No side effects |
| 2 | Default args | `md_script.parse_args([])` | Returns `csv="assetsWithPDFs_without_ETD.csv"`, `debug=False`, `subset_size=5` |
| 3 | All flags | `md_script.parse_args(["--csv", "y.csv", "--debug"])` | Correct overrides |

**Verify:**
```bash
pytest tests/test_integration.py -v    # all green
python3 md_script.py --help            # shows usage
```

---

## Step 3 — Add `enrich_final_output()` to `providers/enrich.py`

**Depends on:** Step 0 (`extract_identifiers` and `should_skip` in `providers/enrich.py`)

**Modify:** `providers/enrich.py`

Add:
```python
def enrich_final_output(
    records: list[dict],
    session: requests.Session,
    oa_rate: float,
    s2_rate: float,
    threshold: int = 90,
    skip_types: list[str] | None = None,
) -> dict[str, dict]:
```

Returns a dict keyed by `asset_id` (string). Each value:
```python
{
    "abstract": str,
    "abstract_source": str,
    "abstract_external_id": str,
    "harvest_status": str,
    "trace": list[str],
}
```

**Internal logic:**
1. Default `skip_types` to `[]` if `None`
2. For each record (with `tqdm` progress bar):
   a. `extract_identifiers(record)` → `(asset_id, doi, title, asset_type)`
   b. If no DOI and no title → `harvest_status="no_identifiers"`
   c. `should_skip(record, skip_types)` → skip reason or `None`
   d. Call `try_providers(session, doi, title, oa_rate, s2_rate, threshold)` for
      eligible records
   e. Wrap each record in try/except for robustness (`harvest_status="error"`)
3. After loop: if all records were skipped, log warning explaining why (ETD no-op
   visibility)
4. Log summary: enriched count, skipped count, no-match count, error count

**Why a separate function from `abstract_script.enrich_records`:** Different return
shape. `abstract_script.enrich_records` returns a flat list of result dicts
(for standalone CSV output). `enrich_final_output` returns a dict keyed by
`asset_id` (for lookup during CSV generation). `abstract_script.enrich_records`
will be updated to call `enrich_final_output` in Phase 5 consolidation.

**Test first** (add to `tests/test_enrich.py`, mocks `providers.harvester.try_providers`
via `monkeypatch`):

| # | Given | When | Then |
|---|-------|------|------|
| 1 | 3 records, provider returns abstracts for 2 | `enrich_final_output(records, ...)` | Returns dict with 3 entries; 2 have `harvest_status="ok"`, 1 has `"no_match"` |
| 2 | Record with existing abstract `description.abstract: [{"value": "text"}]` | `enrich_final_output(...)` | Entry has `harvest_status="skipped_existing_abstract"`, `try_providers` NOT called |
| 3 | Record with empty abstract value `[{"value": ""}]` | `enrich_final_output(...)` | NOT skipped — empty string is not a real abstract |
| 4 | ETD record (`resourceType: "ETD-Doctoral"`) | `enrich_final_output(...)` | Entry has `harvest_status="skipped_etd"` |
| 5 | Record with no DOI and no title | `enrich_final_output(...)` | Entry has `harvest_status="no_identifiers"` |
| 6 | Provider returns `low_confidence` result | `enrich_final_output(...)` | Entry has `harvest_status="low_confidence"`, abstract still populated |
| 7 | Provider raises unexpected exception | `enrich_final_output(...)` | Entry has `harvest_status="error"`, continues to next record |
| 8 | Empty records list | `enrich_final_output([])` | Returns empty dict |
| 9 | Record missing `originalRepository` key | `enrich_final_output(...)` | `harvest_status="error"`, doesn't crash |
| 10 | `skip_types=None` (default) | `enrich_final_output(...)` | No type-based skipping occurs |
| 11 | Result keyed by string asset_id | Check return dict keys | All keys are strings (even if `assetId` was int in record) |
| 12 | All records skipped (ETD scenario) | `enrich_final_output(...)` with all ETD records | Warning logged about all records being skipped |

**Verify:**
```bash
pytest tests/test_enrich.py -v    # all green, no real HTTP calls
python3 -c "from providers.enrich import enrich_final_output"
```

---

## Step 4 — Modify `generate_metadata_csv()` in `script.py`

**Depends on:** Step 1 (`script.py` importable without side effects)

**Modify:** `script.py`

Change `generate_metadata_csv` signature:
```python
def generate_metadata_csv(file_tasks, final_output, enrichment_results=None, output_dir="B"):
```

Changes:
- Add `enrichment_results` parameter (default `None`, treated as empty dict)
- Add `output_dir` parameter (default `"B"`) — for testability with `tmp_path`
- Use `output_dir` instead of hardcoded `"B"` for `os.makedirs` and CSV path
- Add 3 new columns after `download_url`:
  - `abstract` — from `enrichment_results`
  - `abstract_source` — from `enrichment_results`
  - `abstract_external_id` — from `enrichment_results`
- **Type-safe lookup:** `enrichment_results.get(str(asset_id), {})` — asset_id in
  `file_tasks` may be an int, but enrichment result keys are always strings

When `enrichment_results` is `None` or empty, all 3 new columns are empty strings.

**Add fixtures to `tests/conftest.py`:**
- `sample_file_task` — minimal file task dict matching the shape produced by
  `download_asset_files` (fields: `url`, `original_name`, `asset_id`,
  `file_number`, `file_creation_date`, `file_size_bytes`, `file_order`)
- `sample_final_output(sample_esploro_record)` — wraps a record list in
  `{"totalRecordCount": N, "records": [...]}`

**Note on `sample_esploro_record` fixture:** The existing fixture in `conftest.py`
is missing some fields that `generate_metadata_csv` reads:
`displayedDateByPriorityEsploroCP`, `additionalIdentifiers` (nested in
`creators[0]`), `user.primaryId` (nested in `creators[0]`). Update the fixture
to include these fields so CSV generation tests produce realistic output.

**Test first** (add to `tests/test_integration.py`, uses `tmp_path`):

| # | Given | When | Then |
|---|-------|------|------|
| 1 | `enrichment_results=None` | `script.generate_metadata_csv(tasks, output, output_dir=tmp)` | CSV has 29 columns; last 3 are empty |
| 2 | `enrichment_results={}` (empty dict) | Same call | Same result — 29 columns, last 3 empty |
| 3 | `enrichment_results` has entry for `asset_id` | Same call with results | 3 new columns populated for that row |
| 4 | `enrichment_results` has no entry for a given `asset_id` | Same call | That row's 3 new columns are empty |
| 5 | Existing `description` column | Call with enrichment results | `description` column unchanged (still from Esploro data only) |
| 6 | Column order | Read CSV headers | Last 3 are `abstract, abstract_source, abstract_external_id` |
| 7 | `asset_id` type mismatch: int in task, str in enrichment | Call with int asset_id in task, str key in results | Lookup succeeds (str conversion) |

**Verify:**
```bash
pytest tests/test_integration.py -v    # all green
```

---

## Step 5 — Modify `generate_metadata_csv()` in `md_script.py`

**Depends on:** Step 2 (`md_script.py` importable without side effects)

**Modify:** `md_script.py`

Same changes as Step 4:
- Add `enrichment_results` and `output_dir` parameters
- Add 3 new columns with `str(asset_id)` type-safe lookup
- Use `output_dir` instead of hardcoded `"B"`

**Test first** (add to `tests/test_integration.py`):

| # | Given | When | Then |
|---|-------|------|------|
| 1 | `enrichment_results=None` | `md_script.generate_metadata_csv(tasks, output, output_dir=tmp)` | CSV has 29 columns; last 3 empty |
| 2 | `enrichment_results` with matching entry | Same call with results | 3 new columns populated |
| 3 | `asset_id` type mismatch | Same as Step 4, test #7 | Lookup succeeds |

**Note:** Fewer tests than Step 4 — the logic is identical, so we verify basic
correctness + the type mismatch edge case without re-testing every permutation.

**Verify:**
```bash
pytest tests/test_integration.py -v    # all green
```

---

## Step 6 — Wire enrichment into `script.py` `main()`

**Depends on:** Steps 1, 3, 4 (main guard, enrich_final_output, CSV columns)

**Modify:** `script.py`

Add to module-level config block:
```python
ENRICH_ABSTRACTS = False
ASSET_TYPES_TO_SKIP = ["ETD-Doctoral", "ETD-Masters"]
FUZZY_THRESHOLD = 90
```

Add to `parse_args()`:
- `--enrich-abstracts` flag (default: `False`)
- `--fuzzy-threshold` (default: `FUZZY_THRESHOLD`, type `int`)

Add to imports:
```python
from providers.enrich import enrich_final_output
```

In `main()`, between `make_api_calls()` and `download_asset_files()`:
```python
enrichment_results = {}
if args.enrich_abstracts:
    session = requests.Session()
    oa_rate = float(os.getenv("OPENALEX_RATE_INTERVAL", "0.1"))
    s2_rate = float(os.getenv("S2_RATE_INTERVAL", "1.0"))
    enrichment_results = enrich_final_output(
        final_output["records"], session, oa_rate, s2_rate,
        args.fuzzy_threshold, ASSET_TYPES_TO_SKIP
    )
```

Pass `enrichment_results` to `generate_metadata_csv()`.

**Test first** (add to `tests/test_integration.py`, mocks
`providers.enrich.enrich_final_output` and `script.make_api_calls` etc.):

| # | Given | When | Then |
|---|-------|------|------|
| 1 | Default args (no `--enrich-abstracts`) | `script.parse_args([])` | `enrich_abstracts=False`, `fuzzy_threshold=90` |
| 2 | `--enrich-abstracts` flag | `script.parse_args(["--enrich-abstracts"])` | `enrich_abstracts=True` |
| 3 | `--enrich-abstracts --fuzzy-threshold 85` | `script.parse_args(...)` | `fuzzy_threshold=85` |
| 4 | `ENRICH_ABSTRACTS=False` | Mock `main()` run | `enrich_final_output` NOT called |
| 5 | `--enrich-abstracts` | Mock `main()` run | `enrich_final_output` IS called; results passed to `generate_metadata_csv` |
| 6 | All ETD records + `--enrich-abstracts` | Mock `main()` run | Warning logged that all records skipped (ETD no-op) |

**Verify:**
```bash
pytest tests/test_integration.py -v    # all green
python3 script.py --help               # shows --enrich-abstracts and --fuzzy-threshold
```

---

## Step 7 — Wire enrichment into `md_script.py` `main()`

**Depends on:** Steps 2, 3, 5 (main guard, enrich_final_output, CSV columns)

**Modify:** `md_script.py`

Same changes as Step 6:
- Add config block (`ENRICH_ABSTRACTS`, `ASSET_TYPES_TO_SKIP`, `FUZZY_THRESHOLD`)
- Add `--enrich-abstracts` and `--fuzzy-threshold` to `parse_args()`
- Add `from providers.enrich import enrich_final_output`
- In `main()`, between `make_api_calls()` and `generate_file_tasks()`:
  conditionally call `enrich_final_output`, pass results to `generate_metadata_csv`

**Test first** (add to `tests/test_integration.py`):

| # | Given | When | Then |
|---|-------|------|------|
| 1 | Default args | `md_script.parse_args([])` | `enrich_abstracts=False` |
| 2 | `--enrich-abstracts` | `md_script.parse_args(["--enrich-abstracts"])` | `enrich_abstracts=True` |
| 3 | `--enrich-abstracts` | Mock `main()` run | `enrich_final_output` IS called; results passed to `generate_metadata_csv` |
| 4 | Default (no flag) | Mock `main()` run | `enrich_final_output` NOT called; CSV has empty abstract columns |

**Verify:**
```bash
pytest tests/test_integration.py -v    # all green
python3 md_script.py --help            # shows --enrich-abstracts and --fuzzy-threshold
pytest -v                              # full suite — no regressions
```

---

## Regression verification

After all steps are complete, verify that the refactored scripts produce the same
output as before (minus the 3 new empty columns):

1. **Column check:** Run `script.py` and `md_script.py` without `--enrich-abstracts`.
   Verify CSV has 29 columns. First 26 columns have the same names and order as before.
   Last 3 (`abstract`, `abstract_source`, `abstract_external_id`) are empty.

2. **Data check:** If a prior CSV exists from a previous run, diff the first 26
   columns to confirm no data changes.

This is a manual verification step, not an automated test, because the scripts
make live API calls to the Esploro API.

---

## Exit checklist

- [ ] `pytest -v` passes with zero failures (all existing + new tests)
- [ ] `pytest --collect-only` finds tests in `test_enrich.py` and `test_integration.py`
- [ ] `import script` and `import md_script` produce no side effects
- [ ] `python3 script.py --help` shows `--csv`, `--debug`, `--subset-size`, `--enrich-abstracts`, `--fuzzy-threshold`
- [ ] `python3 md_script.py --help` shows same flags (with different `--csv` default)
- [ ] `python3 -c "from providers.enrich import enrich_final_output, extract_identifiers, should_skip"` succeeds
- [ ] Running without `--enrich-abstracts` produces CSV with 29 columns, last 3 empty
- [ ] Running with `--enrich-abstracts` calls `enrich_final_output` and populates abstract columns
- [ ] Existing `description` column is NOT modified by enrichment
- [ ] No `import asyncio` or `import httpx` in any modified file
- [ ] `ENRICH_ABSTRACTS`, `FUZZY_THRESHOLD`, `ASSET_TYPES_TO_SKIP` defined as module-level defaults in both scripts
- [ ] All ETD records skipped when `--enrich-abstracts` used with `script.py` — warning logged
- [ ] `providers/enrich.py` uses `logging.getLogger(__name__)` — no handler configuration
- [ ] `abstract_script.py` imports `extract_identifiers` and `should_skip` from `providers.enrich` — existing tests still pass
- [ ] `asset_id` type mismatch handled: `str()` conversion in `generate_metadata_csv` lookup
- [ ] `sample_esploro_record` fixture updated with missing fields (`displayedDateByPriorityEsploroCP`, `additionalIdentifiers`, `user.primaryId`)
