"""OpenAlex API provider for abstract harvesting.

Handles communication with the OpenAlex API (https://openalex.org)
to retrieve paper abstracts by DOI or title.
"""

import logging
import os

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
