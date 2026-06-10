# Phase 5 Implementation Plan: CLI Consolidation & Documentation

**Scope:** Three areas:
1. Retrofit CLI overrides onto `abstract_script.py` and `import_abstracts.py` to
   match the config-block-plus-argparse pattern in `script.py`/`md_script.py`
2. Consolidate `abstract_script.py` to use `enrich_final_output()` from
   `providers/enrich.py` instead of its own `enrich_records()`
3. Documentation updates: `setup.md`, `requirements.txt`, `_SPEC.md`

**Spec reference:** `_SPEC.md` — Phase 5 (Steps 5.1, 5.2). Steps 0–2 below
expand beyond the spec's documentation-only scope; Step 5 updates the spec to
reflect the actual work.

**Branch:** `feature/abstract-harvesting` (continuing from Phase 4)

**No new dependencies required.**

---

## Design decisions made during planning

| Decision | Choice | Why |
|----------|--------|-----|
| `abstract_script.py` consolidation | Full refactor: remove `enrich_records()`, call `enrich_final_output()` directly in `main()` | Single source of enrichment logic in `providers/enrich.py`; `enrich_records` was a duplication |
| `write_results_csv` signature | Keep unchanged (flat `list[dict]`); add `merge_enrichment_results()` helper | Separation of concerns: join logic is independently testable; `write_results_csv` stays as pure I/O; existing tests need zero changes |
| `import_abstracts.py` CLI style | Switch positional args to `--flags` | Full consistency with `script.py`/`md_script.py` pattern |
| `abstract_script.py` flag scope | Add `--subset-size` and `--fuzzy-threshold` | Full consistency with `script.py`/`md_script.py` |
| `_make_result` helper | Remove along with `enrich_records` | Only used by `enrich_records`; no other callers |
| Test migration | Remove `TestEnrichRecords` from `test_abstract_script.py`; add malformed-record test to `test_enrich.py` first | Enrichment logic is now tested in `test_enrich.py`; must verify coverage gap (malformed record) is filled before removing tests |

---

## Step 0 — Add CLI flags to `abstract_script.py` parse_args()

**Depends on:** nothing

**Modify:** `abstract_script.py`

Change `metadata_path` from positional to `--metadata` flag (`required=True`).
Add flags:
- `--subset-size` (default `DEBUG_SUBSET_SIZE`, type `int`)
- `--fuzzy-threshold` (default `FUZZY_THRESHOLD`, type `int`)

Update `main()`:
- Use `args.metadata` instead of `args.metadata_path`
- Use `args.fuzzy_threshold` instead of module-level `FUZZY_THRESHOLD`
- Use `args.subset_size` instead of module-level `DEBUG_SUBSET_SIZE`

**Modify:** `tests/test_abstract_script.py`

Update `TestParseArgs` tests for new flag-based interface. Update `TestMain`
tests that pass positional args to use `--metadata` flag.

**Test first** (update `TestParseArgs`):

| # | Given | When | Then |
|---|-------|------|------|
| 1 | No args | `parse_args([])` | `SystemExit` (`--metadata` is required) |
| 2 | `--metadata path.json` | `parse_args(["--metadata", "path.json"])` | `metadata="path.json"`, `debug=False`, `subset_size=5`, `fuzzy_threshold=90` |
| 3 | `--metadata p.json --debug` | `parse_args(...)` | `debug=True` |
| 4 | `--metadata p.json --subset-size 3` | `parse_args(...)` | `subset_size=3` |
| 5 | `--metadata p.json --fuzzy-threshold 85` | `parse_args(...)` | `fuzzy_threshold=85` |
| 6 | All flags | `parse_args(["--metadata", "p.json", "--debug", "--subset-size", "3", "--fuzzy-threshold", "85"])` | All set correctly |

**Verify:**
```bash
pytest tests/test_abstract_script.py -v    # all green
python3 abstract_script.py --help          # shows --metadata, --debug, --subset-size, --fuzzy-threshold
```

---

## Step 1 — Switch `import_abstracts.py` positional args to --flags

**Depends on:** nothing (independent of Step 0)

**Modify:** `import_abstracts.py`

Change `bson_path` from positional to `--bson` flag (`required=True`).
Change `metadata_path` from positional to `--metadata` flag (`required=True`).
Keep `--threshold` as-is (already a flag).

Update `main()`:
- Use `args.bson` instead of `args.bson_path`
- Use `args.metadata` instead of `args.metadata_path`

**Modify:** `tests/test_import_abstracts.py`

Update `TestParseArgs` tests and `TestMain` tests that pass positional args.

**Test first** (update `TestParseArgs`):

| # | Given | When | Then |
|---|-------|------|------|
| 1 | No args | `parse_args([])` | `SystemExit` |
| 2 | `--bson f.bson --metadata m.json` | `parse_args(...)` | `bson="f.bson"`, `metadata="m.json"`, `threshold=90` |
| 3 | `--bson f.bson --metadata m.json --threshold 85` | `parse_args(...)` | `threshold=85` |
| 4 | Missing `--bson` only | `parse_args(["--metadata", "m.json"])` | `SystemExit` |
| 5 | Missing `--metadata` only | `parse_args(["--bson", "f.bson"])` | `SystemExit` |

**Verify:**
```bash
pytest tests/test_import_abstracts.py -v    # all green
python3 import_abstracts.py --help          # shows --bson, --metadata, --threshold
```

---

## Step 2 — Consolidate abstract_script.py: remove enrich_records, use enrich_final_output

**Depends on:** Step 0 (parse_args updated)

This step has two sub-parts: first add the merge helper and its tests, then
remove `enrich_records` and update `main()`.

### Step 2a — Add `merge_enrichment_results()` to `abstract_script.py`

**Modify:** `abstract_script.py`

Add:
```python
from providers.enrich import enrich_final_output, extract_identifiers, should_skip

def merge_enrichment_results(
    enrichment_results: dict[str, dict],
    records: list[dict],
) -> list[dict]:
```

Iterates `records`, calls `extract_identifiers()` to get `(asset_id, doi, title,
asset_type)`, looks up `enrichment_results.get(str(asset_id), {})`, and builds
the flat result dict that `write_results_csv` expects:

```python
{
    "asset_id": asset_id,
    "doi": doi,
    "title": title,
    "abstract": enrichment.get("abstract", ""),
    "abstract_source": enrichment.get("abstract_source", ""),
    "abstract_external_id": enrichment.get("abstract_external_id", ""),
    "harvest_status": enrichment.get("harvest_status", ""),
    "trace": enrichment.get("trace", []),
}
```

**Modify:** `tests/test_abstract_script.py`

Add `TestMergeEnrichmentResults` class.

**Test first:**

| # | Given | When | Then |
|---|-------|------|------|
| 1 | 3 records, enrichment results for 2 | `merge_enrichment_results(results, records)` | Returns 3-item list; 2 with abstracts, 1 with empty fields |
| 2 | Empty enrichment results, 2 records | `merge_enrichment_results({}, records)` | 2-item list, all abstract fields empty, harvest_status empty |
| 3 | Empty records list | `merge_enrichment_results({...}, [])` | Empty list |
| 4 | `asset_id` type mismatch: int in record, str in results key | `merge_enrichment_results(...)` | Lookup succeeds (str conversion) |
| 5 | Enrichment result has trace list | `merge_enrichment_results(...)` | Trace list preserved (not yet serialized — that's `write_results_csv`'s job) |
| 6 | Record missing `originalRepository` key | `merge_enrichment_results(...)` | Uses empty-string asset_id; still produces a row |

**Verify:**
```bash
pytest tests/test_abstract_script.py::TestMergeEnrichmentResults -v
```

### Step 2b — Remove `enrich_records()` and wire `main()` to `enrich_final_output`

**Depends on:** Step 2a

**Modify:** `abstract_script.py`

- Remove `enrich_records()` and `_make_result()`
- Remove `from providers.harvester import try_providers` (no longer needed)
- Modify `main()`:
  - Replace `enrich_records(...)` with `enrich_final_output(...)`
  - Add `merge_enrichment_results(enrichment_results, records)` call
  - Pass flat results to `write_results_csv()`
  - Remove manual summary stats (`enriched`, `skipped`, etc. counting and
    `print` calls) — `enrich_final_output` logs its own summary via
    `logging.info`. Keep a single `print` confirming the output path.

**Modify:** `tests/test_abstract_script.py`

- Remove `TestEnrichRecords` class
- Remove `enrich_records` from the import line (line 12)
- Add `merge_enrichment_results` to the import line
- Update `TestMain` tests:
  - Mock `abstract_script.enrich_final_output` instead of `abstract_script.enrich_records`
  - Mock return value is now `dict[str, dict]` instead of `list[dict]`
  - Carry forward: `test_debug_limits_records` (verify subset slicing),
    `test_happy_path_calls_pipeline_in_order` (verify call sequence),
    `test_creates_timestamped_directory`, `test_creates_log_file`,
    `test_bad_metadata_path_exits`, `test_default_rate_intervals`,
    `test_custom_rate_intervals_from_env`

**Modify:** `tests/test_enrich.py`

Add malformed-record test to `TestEnrichFinalOutput` (coverage gap — currently
only in `test_abstract_script.py`):

| # | Given | When | Then |
|---|-------|------|------|
| 1 | Record is a string instead of dict | `enrich_final_output(["not a dict"], ...)` | `harvest_status="error"`, logged with warning, loop continues |

**Test first for main() updates:**

| # | Given | When | Then |
|---|-------|------|------|
| 1 | Happy path | `main(["--metadata", "f.json"])` | Calls `load_metadata` → `enrich_final_output` → `merge_enrichment_results` → `write_results_csv` |
| 2 | `--debug` | `main(["--metadata", "f.json", "--debug"])` | Only first N records passed to `enrich_final_output` |
| 3 | `--fuzzy-threshold 85` | `main(["--metadata", "f.json", "--fuzzy-threshold", "85"])` | `threshold=85` passed to `enrich_final_output` |
| 4 | `--subset-size 3 --debug` | `main(["--metadata", "f.json", "--debug", "--subset-size", "3"])` | Only first 3 records passed |
| 5 | Default rate intervals (no env vars) | `main(...)` | `oa_rate=0.1`, `s2_rate=1.0` passed to `enrich_final_output` |
| 6 | Custom rate intervals from env | `main(...)` with env vars set | Custom rates passed through |

**Verify:**
```bash
pytest tests/test_enrich.py -v              # malformed-record test green
pytest tests/test_abstract_script.py -v     # all updated tests green
pytest -v                                   # full suite, no regressions
```

---

## Step 3 — Rewrite README.md

**Depends on:** Steps 0–1 (needs final CLI flag names)

**Modify:** `README.md`

Replace the current single-paragraph README with a full project document
containing three sections:

### Section 1: Project Overview

What this tool does and how it works:
- Exports PDFs and metadata from University of Idaho's VERSO institutional
  repository (Esploro-based) for web archiving
- Uses the Esploro API to fetch records matching titles in input CSV files
- Directory structure: `A/` (PDFs), `B/` (metadata CSV), `C/` (full JSON +
  logs per run, in timestamped subdirectories)
- Abstract harvesting feature: fetches missing abstracts from OpenAlex and
  Semantic Scholar via a cascade lookup (DOI → title search, with fuzzy
  matching)
- Provider modules in `providers/`: `openalex.py`, `s2.py`, `harvester.py`
  (cascade orchestrator), `enrich.py` (shared helpers)

### Section 2: Abstract Harvesting (feature/abstract-harvesting branch)

What this branch adds to the project:
- `abstract_script.py` — standalone script to enrich previously-exported
  metadata with abstracts from external APIs
- `import_abstracts.py` — one-time script to import pre-harvested abstracts
  from a Universo BSON export
- `--enrich-abstracts` flag on `script.py` and `md_script.py` — inline
  enrichment during regular exports
- Provider cascade: OpenAlex DOI → OpenAlex title → Semantic Scholar DOI →
  Semantic Scholar title, with fuzzy title matching (rapidfuzz), retry logic,
  and circuit breaker

### Section 3: User Guide

Step-by-step CLI reference for all entry points. For each script, document:
- Purpose (one sentence)
- Basic usage command
- All flags with defaults and descriptions
- Example invocations for common workflows
- Output location and format

Scripts to document:

**`script.py`** — fetch metadata + download PDFs
- `--csv` (default: `assetsWithPDFs_just_ETDs.csv`)
- `--debug` / `--subset-size` (default: 5)
- `--enrich-abstracts` / `--fuzzy-threshold` (default: 90)

**`md_script.py`** — fetch metadata only (no PDF download)
- Same flags, `--csv` default: `assetsWithPDFs_without_ETD.csv`

**`abstract_script.py`** — enrich existing metadata with abstracts
- `--metadata` (required)
- `--debug` / `--subset-size` (default: 5)
- `--fuzzy-threshold` (default: 90)

**`import_abstracts.py`** — import pre-harvested abstracts from BSON
- `--bson` (required), `--metadata` (required)
- `--threshold` (default: 90)

Also document:
- Setup instructions (venv, requirements, `.env` file, `mkdir A B C`)
- `.env` variables: `VERSO_API_KEY` (required), `OPENALEX_API_KEY`
  (recommended), `SEMANTIC_SCHOLAR_API_KEY` (optional)
- Directory structure explanation

**No tests needed** — documentation only.

**Verify:** Visual review of `README.md`.

---

## Step 4 — Update setup.md

**Depends on:** Step 3 (README now covers setup in detail; `setup.md` should
be consistent but can be briefer, pointing to README for full reference)

**Modify:** `setup.md`

Add `.env` variable documentation:
```
# For abstract harvesting (abstract_script.py and --enrich-abstracts mode)
OPENALEX_API_KEY=your-key-here          # free at openalex.org
SEMANTIC_SCHOLAR_API_KEY=               # optional
```

Add run instructions for the new entry points:
```
**to enrich existing metadata with abstracts**
python abstract_script.py --metadata C/YYYY-MM-DD_HH-MM-SS/asset_metadata.json

**to import pre-harvested abstracts from Universo BSON export**
python import_abstracts.py --bson unique_documents.bson --metadata C/YYYY-MM-DD_HH-MM-SS/asset_metadata.json

**to generate metadata with abstract enrichment**
python md_script.py --enrich-abstracts

**to generate PDFs + metadata with abstract enrichment**
python script.py --enrich-abstracts
```

**No tests needed** — documentation only.

**Verify:** Visual review of `setup.md`.

---

## Step 5 — Update requirements.txt comment

**Depends on:** nothing (independent)

**Modify:** `requirements.txt`

Add comment above `pymongo` line:
```
# pymongo provides bson.decode_file_iter for mongodump files.
# Do NOT install the standalone 'bson' package — it conflicts with pymongo's bson namespace.
pymongo>=4.0.0
```

**No tests needed.**

**Verify:** `./.venv/bin/pip install -r requirements.txt` succeeds.

---

## Step 6 — Update _SPEC.md Phase 5 section

**Depends on:** Steps 0–5 complete

**Modify:** `_SPEC.md`

Update the Phase 5 section to reflect the actual implementation:
- Rename to "Phase 5: CLI Consolidation & Documentation"
- Note the CLI flag standardization across all scripts (config block + argparse)
- Note the `enrich_records` → `enrich_final_output` consolidation
- Keep the documentation items (setup.md, requirements.txt)
- Update file tree if needed (no new files in Phase 5)

**No tests needed.**

**Verify:** Visual review of `_SPEC.md`.

---

## Exit checklist

- [ ] `pytest -v` passes with zero failures
- [ ] `pytest --collect-only` finds tests in all 7 test files
- [ ] `abstract_script.py --help` shows `--metadata`, `--debug`, `--subset-size`, `--fuzzy-threshold`
- [ ] `import_abstracts.py --help` shows `--bson`, `--metadata`, `--threshold`
- [ ] `abstract_script.py` no longer contains `enrich_records()` or `_make_result()`
- [ ] `abstract_script.py` imports `enrich_final_output` from `providers.enrich`
- [ ] `write_results_csv` signature unchanged (still accepts flat `list[dict]`)
- [ ] `merge_enrichment_results()` exists and is tested
- [ ] `test_enrich.py` has malformed-record test for `enrich_final_output`
- [ ] `README.md` has project overview, abstract-harvesting branch description, and CLI user guide for all 4 scripts
- [ ] `setup.md` documents `.env` variables and run instructions for all 4 scripts
- [ ] `requirements.txt` has pymongo/bson conflict comment
- [ ] `_SPEC.md` Phase 5 section reflects actual work
- [ ] No `import asyncio` or `import httpx` in any file
