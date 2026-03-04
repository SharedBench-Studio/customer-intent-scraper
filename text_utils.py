"""
text_utils.py — Shared text-processing utilities.

No Streamlit imports. No database imports. Safe to import from any script.
"""

import re

_NOISE_WORDS = frozenset([
    # Common English stop words
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "are", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "shall", "can",
    # Question / filler words
    "what", "how", "why", "when", "where", "which", "who", "whom", "whose",
    "if", "so", "then", "that", "this", "these", "those",
    "i", "my", "we", "our", "you", "your", "it", "its", "they", "their",
    "there", "here", "just", "very", "really", "actually", "also", "too",
    "any", "all", "some", "no", "not", "now", "about", "up", "out",
])


def is_meaningful_query(text: str) -> bool:
    """Return True if the query has enough topical content to be testable.

    Strips stop words and question words, then requires ≥ 2 remaining tokens.
    Filters noise like "If so, how" or "How should I do it?".

    Notes:
    - Non-string values (None, NaN, int) return False safely.
    - Non-ASCII and digit-only tokens are excluded by the [a-zA-Z] regex;
      queries that consist entirely of such tokens (e.g. "M365") may be
      filtered out even if they appear meaningful.
    """
    if not isinstance(text, str) or len(text) < 20:
        return False
    tokens = re.findall(r'\b[a-zA-Z]{2,}\b', text.lower())
    meaningful = [t for t in tokens if t not in _NOISE_WORDS]
    return len(meaningful) >= 2
