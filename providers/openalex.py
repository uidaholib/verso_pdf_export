"""OpenAlex API provider for abstract harvesting.

Handles communication with the OpenAlex API (https://openalex.org)
to retrieve paper abstracts by DOI or title.
"""

import logging
import os
import time
from urllib.parse import quote

import requests
from dotenv import load_dotenv

load_dotenv()

# CONFIGURATION
# API key for OpenAlex — free keys available at openalex.org.
# The mailto= polite pool was deprecated Feb 2026; an API key is now required.
OPENALEX_API_KEY = os.getenv("OPENALEX_API_KEY", "")

# Minimum interval (seconds) between API requests.
# OpenAlex uses a credit-based system: singleton lookups = 1 credit,
# search = ~100 credits, 100k daily free credits, hard cap 100 req/s.
OPENALEX_RATE_INTERVAL = float(os.getenv("OPENALEX_RATE_INTERVAL", "0.1"))

logger = logging.getLogger(__name__)

# Retry and circuit breaker configuration
_RETRY_429_SCHEDULE = (3.0, 15.0, 30.0)
_MAX_RETRIES = 3
_CIRCUIT_THRESHOLD = 3
_CIRCUIT_COOLDOWN = 300.0

# Circuit breaker state — module-level globals
_consecutive_429s = 0
_suspended_until = 0.0


def reconstruct_abstract(inverted_index: dict | None) -> str:
    """Convert an OpenAlex inverted-index abstract to plain text.

    OpenAlex stores abstracts as {"word": [pos0, pos1, ...], ...} where each
    word is mapped to the positions it occupies in the original text. This
    function reverses that mapping to recover the original word order.
    """
    if not inverted_index:
        return ""

    position_to_word: dict[int, str] = {}
    for word, positions in inverted_index.items():
        for pos in positions:
            position_to_word[pos] = word

    sorted_positions = sorted(position_to_word)
    return " ".join(position_to_word[pos] for pos in sorted_positions)


def _trip_circuit() -> None:
    """Increment the circuit breaker counter; suspend if threshold reached."""
    global _consecutive_429s, _suspended_until
    _consecutive_429s += 1
    if _consecutive_429s >= _CIRCUIT_THRESHOLD:
        _suspended_until = time.monotonic() + _CIRCUIT_COOLDOWN
        logger.warning(
            "OpenAlex circuit breaker tripped after %d consecutive 429s — "
            "suspending requests for %.0fs",
            _consecutive_429s,
            _CIRCUIT_COOLDOWN,
        )


def _reset_circuit() -> None:
    """Reset circuit breaker state after a successful request."""
    global _consecutive_429s, _suspended_until
    if _consecutive_429s or _suspended_until:
        _consecutive_429s = 0
        _suspended_until = 0.0


def _shape(work: dict) -> dict | None:
    """Extract abstract from an OpenAlex work dict into a standard shape."""
    abstract = reconstruct_abstract(work.get("abstract_inverted_index"))
    if not abstract:
        return None
    title = (work.get("title") or work.get("display_name") or "").strip()
    return {
        "abstract": abstract,
        "matched_title": title,
        "external_id": work.get("id", ""),
        "source": "openalex",
    }


def lookup_by_doi(
    session: requests.Session, doi: str, rate_interval: float
) -> dict | None:
    """Look up a paper by DOI via the OpenAlex API.

    Returns a shaped dict with abstract, matched_title, external_id, and source,
    or None if the paper is not found, has no abstract, or an error occurs.
    Retries on transient errors (429, 403, 5xx) with backoff.
    """
    if not doi:
        return None

    # Circuit breaker check
    if _suspended_until and time.monotonic() < _suspended_until:
        return None

    # Rate limiting
    time.sleep(rate_interval)

    encoded_doi = quote(doi, safe="")
    url = f"https://api.openalex.org/works/doi:{encoded_doi}"
    params = {"api_key": OPENALEX_API_KEY}

    retries = 0
    while True:
        try:
            resp = session.get(
                url, params=params, headers={"Accept": "application/json"}
            )
        except requests.exceptions.ConnectionError:
            logger.warning("OpenAlex connection error for DOI=%s", doi)
            return None
        except requests.exceptions.Timeout:
            logger.warning("OpenAlex timeout for DOI=%s", doi)
            return None

        status = resp.status_code

        if status == 200:
            _reset_circuit()
            return _shape(resp.json())

        if status == 404:
            return None

        if status == 429:
            remaining = resp.headers.get("X-RateLimit-Remaining")
            if remaining is not None and remaining == "0":
                logger.warning("OpenAlex daily credits exhausted for DOI=%s", doi)
                return None

        if status in (429, 403, 500, 502, 503, 504):
            retries += 1
            if retries > _MAX_RETRIES:
                logger.warning(
                    "OpenAlex %d retries exhausted (%d) for DOI=%s",
                    status,
                    retries,
                    doi,
                )
                if status == 429:
                    _trip_circuit()
                return None
            logger.info(
                "OpenAlex %d, retry %d/%d for DOI=%s",
                status,
                retries,
                _MAX_RETRIES,
                doi,
            )
            time.sleep(_RETRY_429_SCHEDULE[retries - 1])
            continue

        # Unexpected status
        logger.debug("OpenAlex unexpected status %d for DOI=%s", status, doi)
        return None


def search_by_title(
    session: requests.Session, title: str, rate_interval: float
) -> dict | None:
    """Search for a paper by title via the OpenAlex API.

    Returns a shaped dict for the top result, or None if no match is found,
    the result has no abstract, or an error occurs.
    Retries on transient errors (429, 403, 5xx) with backoff.
    """
    if not title:
        return None

    # Circuit breaker check
    if _suspended_until and time.monotonic() < _suspended_until:
        return None

    # Rate limiting
    time.sleep(rate_interval)

    url = "https://api.openalex.org/works"
    params = {"api_key": OPENALEX_API_KEY, "search": title, "per_page": 1}

    retries = 0
    while True:
        try:
            resp = session.get(
                url, params=params, headers={"Accept": "application/json"}
            )
        except requests.exceptions.ConnectionError:
            logger.warning("OpenAlex connection error for title=%s", title)
            return None
        except requests.exceptions.Timeout:
            logger.warning("OpenAlex timeout for title=%s", title)
            return None

        status = resp.status_code

        if status == 200:
            _reset_circuit()
            results = resp.json().get("results", [])
            if not results:
                return None
            return _shape(results[0])

        if status == 404:
            return None

        if status == 429:
            remaining = resp.headers.get("X-RateLimit-Remaining")
            if remaining is not None and remaining == "0":
                logger.warning("OpenAlex daily credits exhausted for title=%s", title)
                return None

        if status in (429, 403, 500, 502, 503, 504):
            retries += 1
            if retries > _MAX_RETRIES:
                logger.warning(
                    "OpenAlex %d retries exhausted (%d) for title=%s",
                    status,
                    retries,
                    title,
                )
                if status == 429:
                    _trip_circuit()
                return None
            logger.info(
                "OpenAlex %d, retry %d/%d for title=%s",
                status,
                retries,
                _MAX_RETRIES,
                title,
            )
            time.sleep(_RETRY_429_SCHEDULE[retries - 1])
            continue

        # Unexpected status
        logger.debug("OpenAlex unexpected status %d for title=%s", status, title)
        return None
