# Phase 0–1 Implementation Plan: Foundation + Provider Modules

**Scope:** Test infrastructure, dependencies, and the three provider modules
(`providers/openalex.py`, `providers/s2.py`, `providers/harvester.py`) with
full TDD test suites.

**Spec reference:** `_SPEC.md` — Phase 0 (Step 0.1) and Phase 1 (Steps 1.1–1.3)

---

## Design decisions made during planning

| Decision | Choice | Why |
|----------|--------|-----|
| `low_confidence` reason | Returned when a title-based match scores >= threshold but < 95 | Spec lists it as a valid `try_providers` return value; defining a concrete boundary now avoids ambiguity later |
| `pytest-cov` | Included as test dependency | User preference for coverage tracking from the start, even though spec doesn't mention it |
| Step granularity | One function per step for I/O functions | Keeps TDD cycles small and reviewable, despite shared retry infrastructure |
| Provider logging | Modules only call `logging.getLogger(__name__)` — never configure handlers | Handler config belongs in the calling scripts; avoids duplicate handlers |
| `conftest.py` session fixture | Real `requests.Session()` — the `responses` library intercepts at the adapter level | Keeps fixtures simple; no need to mock the session itself |
| OpenAlex auth | `api_key=` query param (not `mailto=`) | Polite pool with `mailto=` deprecated Feb 2026; free API keys at openalex.org |
| OpenAlex rate limits | Credit-based (1 credit/singleton, ~100/search, 100k daily free, 100 req/s cap) | Replaced flat "10 req/s polite pool" assumption per current API docs |
| OpenAlex 403 vs 429 | 403 = per-second cap (retry), 429 = daily credits exhausted (check `X-RateLimit-Remaining`) | Both can indicate rate limiting but require different handling |
| S2 batch endpoint | Deferred to later phase | Exists (`POST /paper/batch`, 500 DOIs/req) but adds complexity; individual calls fine for Phase 1 |
| S2 `Retry-After` header | Honor if present, fallback backoff if absent | S2 docs don't confirm the header is always sent on 429 |

---

## Step 0 — Test infrastructure and dependencies

**Modify:** `requirements.txt`

Add:
```
rapidfuzz>=3.0.0
pymongo>=4.0.0
pytest>=7.0.0
responses>=0.23.0
pytest-cov>=4.0.0
```

**Create (3 files — all trivial boilerplate):**
- `providers/__init__.py` — empty
- `tests/__init__.py` — empty
- `tests/conftest.py` — shared fixtures:
  - `session` — returns a real `requests.Session()` (the `responses` library
    intercepts at the adapter level, so a real session works correctly in tests)
  - `sample_doi`, `sample_title` — string constants for reuse
  - `sample_esploro_record` — a realistic Esploro API record dict (used in
    later test files for `extract_identifiers`, `should_skip`, etc.)

**Verify:**
```bash
pip install -r requirements.txt && pytest --collect-only
```
Installs cleanly, finds 0 tests.

---

## Step 1 — `reconstruct_abstract()` in `providers/openalex.py`

**Test first** in `tests/test_openalex.py`:

| # | Given | When | Then |
|---|-------|------|------|
| 1 | Valid inverted index `{"the": [0], "quick": [1]}` | `reconstruct_abstract(index)` | Returns `"the quick"` |
| 2 | One word at multiple positions `{"the": [0, 5], "cat": [1]}` | `reconstruct_abstract(index)` | Correct word order: `"the cat ... the"` (word placed at each position) |
| 3 | Two words mapped to the same position `{"a": [0], "b": [0]}` | `reconstruct_abstract(index)` | Does not crash; returns a string (last-write-wins or similar) |
| 4 | `None` input | `reconstruct_abstract(None)` | Returns `""` |
| 5 | `{}` input | `reconstruct_abstract({})` | Returns `""` |
| 6 | Sparse index with gaps (positions 0, 2, 5) | `reconstruct_abstract(index)` | Gap positions produce no extra whitespace; words joined cleanly |
| 7 | Large realistic index (~50 words) | `reconstruct_abstract(index)` | Produces coherent sentence; regression guard |

**Implement:** Create `providers/openalex.py` with:
- Module-level constants: `OPENALEX_API_KEY` (from env, required — free keys at
  openalex.org; the `mailto=` polite pool was deprecated Feb 2026),
  `OPENALEX_RATE_INTERVAL` (from env, default `0.1` — credit-based system:
  singleton lookups = 1 credit, search = ~100 credits, 100k daily free credits,
  hard cap 100 req/s)
- `reconstruct_abstract(inverted_index: dict | None) -> str` — pure function, no I/O

**Verify:** `pytest tests/test_openalex.py -v` — all green.

---

## Step 2 — `lookup_by_doi()` in `providers/openalex.py`

**Test first** (add to `tests/test_openalex.py`, uses `responses` library to mock HTTP):

| # | Given | When | Then |
|---|-------|------|------|
| 1 | API returns 200 with `abstract_inverted_index` | `lookup_by_doi(s, "10.1/abc", 0)` | Returns `{"abstract": "...", "matched_title": "...", "external_id": "...", "source": "openalex"}` |
| 2 | API returns 200 but `abstract_inverted_index` is `null` | `lookup_by_doi(...)` | Returns `None` |
| 3 | API returns 200 but `abstract_inverted_index` key missing entirely | `lookup_by_doi(...)` | Returns `None` |
| 4 | API returns 404 | `lookup_by_doi(...)` | Returns `None`, no retry |
| 5 | API returns 429 then 200 | `lookup_by_doi(...)` | Returns result after retry |
| 6 | API returns 500 then 200 | `lookup_by_doi(...)` | Returns result after retry (5xx triggers same retry as 429) |
| 7 | API returns 429 three times | `lookup_by_doi(...)` | Returns `None`, logs warning |
| 8 | Empty DOI `""` | `lookup_by_doi(s, "", 0)` | Returns `None` immediately, no HTTP call |
| 9 | API key configured (env var set) | `lookup_by_doi(...)` | URL contains `api_key=...` param |
| 13 | API returns 403 (per-second rate limit) then 200 | `lookup_by_doi(...)` | Retries, returns result |
| 14 | API returns 429 with `X-RateLimit-Remaining: 0` | `lookup_by_doi(...)` | Does NOT retry (daily credits exhausted), logs warning |
| 10 | `rate_interval` parameter | `lookup_by_doi(s, doi, 0.5)` | `time.sleep(0.5)` is called (mock `time.sleep`) |
| 11 | `session.get()` raises `ConnectionError` | `lookup_by_doi(...)` | Returns `None`, logs warning |
| 12 | `session.get()` raises `Timeout` | `lookup_by_doi(...)` | Returns `None`, logs warning |

**Implement:** Add `lookup_by_doi(session, doi, rate_interval) -> dict | None` to
`providers/openalex.py`. Includes:
- `GET https://api.openalex.org/works/doi:{doi}`
- Retry up to 3 times on 429/403/5xx with exponential backoff (`time.sleep(3), time.sleep(15), time.sleep(30)`)
- On 429: check `X-RateLimit-Remaining` header — if 0, daily credits are exhausted,
  do NOT retry (return `None` immediately with a warning log)
- On 403: per-second rate limit exceeded, retry normally
- Returns `None` on 404 (no retry)
- Returns `None` on network errors (`ConnectionError`, `Timeout`) after logging
- Calls `time.sleep(rate_interval)` before each request
- Sends `api_key=` query param on all requests (required since Feb 2026)
- Circuit breaker globals (module-level): `_consecutive_429s`, `_suspended_until`.
  After 3 consecutive 429-skips, suspend OA calls for 300s.

**Verify:** `pytest tests/test_openalex.py -v` — all green, no real HTTP calls.

---

## Step 3 — Circuit breaker tests for `providers/openalex.py`

**Test first** (add to `tests/test_openalex.py`):

| # | Given | When | Then |
|---|-------|------|------|
| 1 | 3 consecutive calls each get 429 three times | Next call to `lookup_by_doi` | Returns `None` immediately, no HTTP request made (circuit open) |
| 2 | Circuit is open, 300s have passed | `lookup_by_doi(...)` | Makes HTTP request normally (circuit closed) |
| 3 | Circuit is open | `search_by_title(...)` | Also returns `None` immediately (circuit is module-wide) |
| 4 | A successful call after failures | Next call | `_consecutive_429s` resets to 0 |

**Implement:** Wire circuit breaker checks into `lookup_by_doi` (already partially
done in Step 2) and ensure `search_by_title` (Step 4) will also check it.

**Note:** Tests will need to reset module-level circuit breaker globals between test
cases. Add a `reset_openalex_circuit_breaker` fixture to `conftest.py` or use
`autouse` fixture in `test_openalex.py`.

**Verify:** `pytest tests/test_openalex.py -v` — all green.

---

## Step 4 — `search_by_title()` in `providers/openalex.py`

**Test first** (add to `tests/test_openalex.py`):

| # | Given | When | Then |
|---|-------|------|------|
| 1 | Search returns results with `abstract_inverted_index` | `search_by_title(s, "My Paper", 0)` | Returns shaped dict |
| 2 | Search returns empty results list | `search_by_title(...)` | Returns `None` |
| 3 | Search returns 429 then 200 | `search_by_title(...)` | Retries, returns result |
| 4 | Search returns 500 | `search_by_title(...)` | Retries with same pattern as `lookup_by_doi` |
| 5 | Empty title `""` | `search_by_title(s, "", 0)` | Returns `None` immediately |
| 6 | Circuit breaker is open | `search_by_title(...)` | Returns `None` immediately (shared circuit) |

**Implement:** Add `search_by_title(session, title, rate_interval) -> dict | None`
to `providers/openalex.py`.
- `GET https://api.openalex.org/works?search={title}&per_page=1`
- Same retry/circuit-breaker logic as `lookup_by_doi`

**Verify:** `pytest tests/test_openalex.py -v` — all green.

---

## Step 5 — `lookup_by_doi()` in `providers/s2.py`

**Test first** in `tests/test_s2.py` (uses `responses` library):

| # | Given | When | Then |
|---|-------|------|------|
| 1 | 200 with abstract | `lookup_by_doi(s, "10.1/abc", 0)` | Returns `{"abstract": "...", "matched_title": "...", "external_id": "...", "source": "semantic_scholar"}` |
| 2 | 200 but abstract is `null` | `lookup_by_doi(...)` | Returns `None` |
| 3 | 200 but abstract key missing entirely | `lookup_by_doi(...)` | Returns `None` |
| 4 | 404 | `lookup_by_doi(...)` | Returns `None`, no retry |
| 5 | 429 with `Retry-After` header, then 200 | `lookup_by_doi(...)` | Sleeps for `Retry-After` seconds, returns result |
| 6 | 429 without `Retry-After`, then 200 | `lookup_by_doi(...)` | Uses fallback backoff schedule |
| 7 | 500 then 200 | `lookup_by_doi(...)` | Retries, returns result |
| 8 | API key present (env var set) | Any request | `x-api-key` header included |
| 9 | API key absent | Any request | No `x-api-key` header |
| 10 | Empty DOI `""` | `lookup_by_doi(s, "", 0)` | Returns `None` immediately |
| 11 | `rate_interval` parameter | `lookup_by_doi(s, doi, 1.0)` | `time.sleep(1.0)` called |
| 12 | `session.get()` raises `ConnectionError` | `lookup_by_doi(...)` | Returns `None`, logs warning |

**Implement:** Create `providers/s2.py` with:
- Module-level constants: `S2_API_KEY` (from env, default `""` — optional; gives
  guaranteed 1 req/s individual allocation vs shared unauthenticated pool),
  `S2_RATE_INTERVAL` (from env, default `1.0`)
- `lookup_by_doi(session, doi, rate_interval) -> dict | None`
- `GET https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}?fields=title,abstract,externalIds`
- Retry up to 3 times on 429/5xx; honors `Retry-After` header if present
  (not guaranteed by S2 docs — use fallback backoff when absent)
- No circuit breaker (S2 doesn't have the same throttling pattern)

**Note:** S2 offers a batch endpoint (`POST /graph/v1/paper/batch`, up to 500 DOIs)
that would be more efficient for ~2,000 lookups. Deferred to a later optimization phase.

**Verify:** `pytest tests/test_s2.py -v` — all green.

---

## Step 6 — `match_by_title()` in `providers/s2.py`

**Test first** (add to `tests/test_s2.py`):

| # | Given | When | Then |
|---|-------|------|------|
| 1 | Match endpoint returns result with abstract | `match_by_title(s, "My Paper", 0)` | Returns shaped dict (S2 response includes `matchScore`; can be logged for diagnostics) |
| 2 | Match endpoint returns 404 (no match) | `match_by_title(...)` | Returns `None` (S2 returns 404 when no match found, not empty results) |
| 3 | Empty title `""` | `match_by_title(s, "", 0)` | Returns `None` immediately |
| 4 | 429 with `Retry-After`, then 200 | `match_by_title(...)` | Honors `Retry-After`, retries, returns result |
| 5 | 500 then 200 | `match_by_title(...)` | Retries with same pattern |
| 6 | `session.get()` raises `ConnectionError` | `match_by_title(...)` | Returns `None`, logs warning |

**Implement:** Add `match_by_title(session, title, rate_interval) -> dict | None`
to `providers/s2.py`.
- `GET https://api.semanticscholar.org/graph/v1/paper/search/match?query={title}&fields=title,abstract,externalIds`
- Same retry pattern as `lookup_by_doi`

**Verify:** `pytest tests/test_s2.py -v` — all green.

---

## Step 7 — `title_matches()` in `providers/harvester.py`

**Test first** in `tests/test_harvester.py`:

| # | Given | When | Then |
|---|-------|------|------|
| 1 | Identical titles `"Hello World"` / `"Hello World"` | `title_matches(a, b, 90)` | `True` |
| 2 | Case difference `"HELLO"` / `"hello"` | `title_matches(a, b, 90)` | `True` |
| 3 | Unrelated titles `"Quantum Physics"` / `"Cooking Tips"` | `title_matches(a, b, 90)` | `False` |
| 4 | Empty local `""` | `title_matches("", "anything", 90)` | `False` |
| 5 | Empty candidate `""` | `title_matches("anything", "", 90)` | `False` |
| 6 | Score exactly at threshold (craft input to hit boundary) | `title_matches(a, b, threshold)` | `True` (uses `>=` comparison) |
| 7 | Score just below threshold | `title_matches(a, b, threshold)` | `False` |

**Implement:** Create `providers/harvester.py` with:
- `title_matches(local: str, candidate: str, threshold: int = 90) -> bool`
- Uses `rapidfuzz.fuzz.token_set_ratio`
- Returns `False` if either string is empty

**Verify:** `pytest tests/test_harvester.py -v` — all green.

---

## Step 8 — `try_providers()` in `providers/harvester.py`

**Test first** (add to `tests/test_harvester.py`, mocks at function level via
`monkeypatch` on `providers.openalex.lookup_by_doi` etc., NOT at HTTP level):

| # | Given | When | Then |
|---|-------|------|------|
| 1 | OA DOI hits with high-confidence title match (score >= 95) | `try_providers(...)` | Returns `(result, "ok", ["oa_doi=hit"])` |
| 2 | OA DOI miss, S2 DOI hits | `try_providers(...)` | Returns S2 result, trace shows OA miss + S2 hit |
| 3 | Both DOI miss, OA title match score >= 95 | `try_providers(...)` | Returns `(result, "ok", [...])` |
| 4 | Both DOI miss, OA title match score >= 90 but < 95 | `try_providers(...)` | Returns `(result, "low_confidence", [...])` |
| 5 | OA title below threshold, S2 title match >= 95 | `try_providers(...)` | Returns `(result, "ok", [...])` |
| 6 | OA title below threshold, S2 title match >= 90 but < 95 | `try_providers(...)` | Returns `(result, "low_confidence", [...])` |
| 7 | All four providers miss | `try_providers(...)` | Returns `(None, "no_match", [...])` |
| 8 | No DOI provided, title only | `try_providers(s, "", "Title", ...)` | Skips DOI lookups, goes straight to title search |
| 9 | No DOI and no title | `try_providers(s, "", "", ...)` | Returns `(None, "no_match", [])` immediately |
| 10 | OA DOI raises exception | `try_providers(...)` | Logs warning, falls through to next provider |
| 11 | All providers raise exceptions | `try_providers(...)` | Returns `(None, "no_match", [...])` |
| 12 | DOI-based hit (no title matching needed) | `try_providers(...)` | reason is always `"ok"` (DOI match = high confidence) |

**`low_confidence` definition:** When a match comes from a title-based lookup
(not DOI), and `title_matches()` scores >= `threshold` (default 90) but < 95,
reason is `"low_confidence"`. Score >= 95 = `"ok"`. DOI-based matches are
always `"ok"` (DOI is a strong identifier). This boundary (95) is a constant
`HIGH_CONFIDENCE_THRESHOLD` in `harvester.py`.

**Implement:** Add to `providers/harvester.py`:
- `HIGH_CONFIDENCE_THRESHOLD = 95` (module-level constant)
- `try_providers(session, doi, title, oa_rate, s2_rate, fuzzy_threshold=90) -> tuple[dict | None, str, list[str]]`
- Cascade order: OA DOI → OA title → S2 DOI → S2 title
- Each step wrapped in try/except to allow fallthrough on errors
- `try_providers` does NOT make HTTP calls itself — it delegates to provider functions

**Verify:**
```bash
pytest tests/test_harvester.py -v          # all green
python -c "from providers.harvester import try_providers"  # import succeeds
```

---

## Exit checklist

- [ ] `pytest -v` passes with zero failures
- [ ] `pytest --collect-only` finds tests in all 3 test files (`test_openalex.py`, `test_s2.py`, `test_harvester.py`)
- [ ] `pytest --cov=providers --cov-report=term-missing` shows coverage for all provider modules
- [ ] `python -c "from providers.harvester import try_providers"` succeeds
- [ ] `python -c "from providers.openalex import lookup_by_doi, search_by_title, reconstruct_abstract"` succeeds
- [ ] `python -c "from providers.s2 import lookup_by_doi, match_by_title"` succeeds
- [ ] No `import asyncio` or `import httpx` in any new file
- [ ] Provider modules only use `logging.getLogger(__name__)` — no handler configuration
- [ ] Every provider function has tests for: success, 404, 429-retry, 5xx-retry, empty input, network error
- [ ] Circuit breaker tested: trips after 3 consecutive 429s, resets after 300s, applies module-wide
- [ ] `low_confidence` reason tested: title match >= threshold but < 95
- [ ] `rate_interval` sleep behavior tested (mocked `time.sleep`)
