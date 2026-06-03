"""Semantic Scholar API provider for abstract harvesting.

Handles communication with the Semantic Scholar API
(https://api.semanticscholar.org) to retrieve paper abstracts by DOI.
"""

import logging
import os
import time
from urllib.parse import quote

import requests
from dotenv import load_dotenv

load_dotenv()

# CONFIGURATION
# Optional API key for Semantic Scholar — provides a guaranteed 1 req/s
# individual allocation vs the shared unauthenticated pool.
# When empty, requests are sent without authentication.
S2_API_KEY = os.getenv("S2_API_KEY", "")

# Minimum interval (seconds) between API requests.
S2_RATE_INTERVAL = float(os.getenv("S2_RATE_INTERVAL", "1.0"))

logger = logging.getLogger(__name__)

# Retry configuration — no circuit breaker for S2 (different throttling pattern)
_RETRY_BACKOFF_SCHEDULE = (3.0, 15.0, 30.0)
_MAX_RETRIES = 3


def _shape(data: dict) -> dict | None:
    """Extract abstract from an S2 paper dict into a standard shape."""
    abstract = data.get("abstract")
    if not abstract:
        return None
    title = (data.get("title") or "").strip()
    return {
        "abstract": abstract,
        "matched_title": title,
        "external_id": data.get("paperId", ""),
        "source": "semantic_scholar",
    }


def lookup_by_doi(
    session: requests.Session, doi: str, rate_interval: float
) -> dict | None:
    """Look up a paper by DOI via the Semantic Scholar API.

    Returns a shaped dict with abstract, matched_title, external_id, and source,
    or None if the paper is not found, has no abstract, or an error occurs.
    Retries on transient errors (429, 5xx) with backoff; honors Retry-After
    header on 429 responses when present.
    """
    if not doi:
        return None

    # Rate limiting
    time.sleep(rate_interval)

    encoded_doi = quote(doi, safe="")
    url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{encoded_doi}"
    params = {"fields": "title,abstract,externalIds"}

    headers = {"Accept": "application/json"}
    if S2_API_KEY:
        headers["x-api-key"] = S2_API_KEY

    retries = 0
    while True:
        try:
            resp = session.get(url, params=params, headers=headers)
        except requests.exceptions.ConnectionError:
            logger.warning("S2 connection error for DOI=%s", doi)
            return None

        status = resp.status_code

        if status == 200:
            return _shape(resp.json())

        if status == 404:
            return None

        if status in (429, 500, 502, 503, 504):
            retries += 1
            if retries > _MAX_RETRIES:
                logger.warning(
                    "S2 %d retries exhausted (%d) for DOI=%s",
                    status,
                    retries,
                    doi,
                )
                return None
            logger.info(
                "S2 %d, retry %d/%d for DOI=%s",
                status,
                retries,
                _MAX_RETRIES,
                doi,
            )
            # Honor Retry-After header if present on 429; otherwise use
            # fallback backoff schedule for both 429 and 5xx.
            retry_after = resp.headers.get("Retry-After") if status == 429 else None
            if retry_after is not None:
                try:
                    time.sleep(float(retry_after))
                except ValueError:
                    time.sleep(_RETRY_BACKOFF_SCHEDULE[retries - 1])
            else:
                time.sleep(_RETRY_BACKOFF_SCHEDULE[retries - 1])
            continue

        # Unexpected status
        logger.debug("S2 unexpected status %d for DOI=%s", status, doi)
        return None
