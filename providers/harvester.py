"""Fuzzy title comparison for validating API results against local records.

When external providers (OpenAlex, Semantic Scholar) return a paper, we need
to verify that the returned title actually matches the title we searched for.
token_set_ratio handles word reordering and minor differences well, making it
a good fit for academic titles that may vary in punctuation or subtitle format.
"""

import logging

from rapidfuzz import fuzz

logger = logging.getLogger(__name__)


def title_matches(local: str, candidate: str, threshold: int = 90) -> bool:
    """Check whether two paper titles refer to the same work.

    Returns False immediately if either title is empty, since an empty
    string would produce a misleading similarity score.
    """
    if not local or not candidate:
        return False

    score = fuzz.token_set_ratio(local.lower(), candidate.lower())
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
