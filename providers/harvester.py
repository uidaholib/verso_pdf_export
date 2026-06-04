"""Fuzzy title comparison and cascade orchestrator for abstract harvesting.

When external providers (OpenAlex, Semantic Scholar) return a paper, we need
to verify that the returned title actually matches the title we searched for.
token_set_ratio handles word reordering and minor differences well, making it
a good fit for academic titles that may vary in punctuation or subtitle format.

try_providers() orchestrates multiple provider lookups in sequence, returning
the first successful result with a confidence reason and diagnostic trace.
"""

import logging

import requests
from rapidfuzz import fuzz

from providers import openalex, s2

logger = logging.getLogger(__name__)

HIGH_CONFIDENCE_THRESHOLD = 95


def title_match_score(local: str, candidate: str) -> float:
    """Return the fuzzy similarity score between two paper titles.

    Returns 0.0 if either title is empty, since an empty string would
    produce a misleading similarity score.
    """
    if not local or not candidate:
        return 0.0

    return fuzz.token_set_ratio(local.lower(), candidate.lower())


def title_matches(local: str, candidate: str, threshold: int = 90) -> bool:
    """Check whether two paper titles refer to the same work."""
    score = title_match_score(local, candidate)
    result = score >= threshold

    logger.debug(
        "title_matches: score=%.1f threshold=%d result=%s local=%r candidate=%r",
        score,
        threshold,
        result,
        local[:80],
        candidate[:80],
    )

    return result


def try_providers(
    session: requests.Session,
    doi: str,
    title: str,
    oa_rate: float,
    s2_rate: float,
    fuzzy_threshold: int = 90,
) -> tuple[dict | None, str, list[str]]:
    """Try multiple providers in sequence to find an abstract for a paper.

    Cascade order: OA DOI -> OA title -> S2 DOI -> S2 title.
    DOI-based hits are always high confidence ("ok"). Title-based hits
    are validated with fuzzy matching — score >= 95 is "ok", score >= threshold
    but < 95 is "low_confidence", and score < threshold is treated as a miss.

    Returns (result_dict_or_None, reason_string, diagnostic_trace_list).
    """
    if not doi and not title:
        return (None, "no_match", [])

    trace: list[str] = []

    # --- Step 1: OA DOI (high confidence, no title matching needed) ---
    if doi:
        try:
            result = openalex.lookup_by_doi(session, doi, oa_rate)
        except Exception as exc:
            logger.warning("OA DOI lookup failed for doi=%s: %s", doi, exc)
            trace.append("oa_doi=error")
            result = None
        else:
            if result is not None:
                trace.append("oa_doi=hit")
                return (result, "ok", trace)
            trace.append("oa_doi=miss")

    # --- Step 2: OA title (needs fuzzy validation) ---
    if title:
        try:
            result = openalex.search_by_title(session, title, oa_rate)
        except Exception as exc:
            logger.warning("OA title search failed for title=%r: %s", title, exc)
            trace.append("oa_title=error")
            result = None
        else:
            if result is not None:
                score = title_match_score(title, result["matched_title"])
                if score >= fuzzy_threshold:
                    reason = (
                        "ok" if score >= HIGH_CONFIDENCE_THRESHOLD else "low_confidence"
                    )
                    trace.append("oa_title=hit")
                    return (result, reason, trace)
            trace.append("oa_title=miss")

    # --- Step 3: S2 DOI (high confidence, no title matching needed) ---
    if doi:
        try:
            result = s2.lookup_by_doi(session, doi, s2_rate)
        except Exception as exc:
            logger.warning("S2 DOI lookup failed for doi=%s: %s", doi, exc)
            trace.append("s2_doi=error")
            result = None
        else:
            if result is not None:
                trace.append("s2_doi=hit")
                return (result, "ok", trace)
            trace.append("s2_doi=miss")

    # --- Step 4: S2 title (needs fuzzy validation) ---
    if title:
        try:
            result = s2.match_by_title(session, title, s2_rate)
        except Exception as exc:
            logger.warning("S2 title match failed for title=%r: %s", title, exc)
            trace.append("s2_title=error")
            result = None
        else:
            if result is not None:
                score = title_match_score(title, result["matched_title"])
                if score >= fuzzy_threshold:
                    reason = (
                        "ok" if score >= HIGH_CONFIDENCE_THRESHOLD else "low_confidence"
                    )
                    trace.append("s2_title=hit")
                    return (result, reason, trace)
            trace.append("s2_title=miss")

    return (None, "no_match", trace)
