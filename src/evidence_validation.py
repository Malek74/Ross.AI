"""
evidence_validation.py
======================
Anti-hallucination gate: validates that every citation in a flag
references a real substring of the contract and a real article.

Called inside the flag_risk tool — the agent cannot emit a flag
whose quote doesn't exist in the contract or whose article isn't
in the index.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.arabic_normalize import normalize


@dataclass
class QuoteMatch:
    matched: bool
    start: int
    end: int
    matched_text: str
    similarity: float


def _normalize_for_match(text: str) -> str:
    text = normalize(text, taa_marbuta=True)
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def validate_quote(quote: str, contract_text: str, threshold: float = 0.75) -> QuoteMatch:
    if not quote or not contract_text:
        return QuoteMatch(False, -1, -1, "", 0.0)

    norm_quote = _normalize_for_match(quote)
    norm_contract = _normalize_for_match(contract_text)

    if not norm_quote:
        return QuoteMatch(False, -1, -1, "", 0.0)

    # Exact normalized substring match
    idx = norm_contract.find(norm_quote)
    if idx >= 0:
        return QuoteMatch(
            matched=True,
            start=idx,
            end=idx + len(norm_quote),
            matched_text=norm_quote,
            similarity=1.0,
        )

    # Sliding window fuzzy match on word tokens
    quote_words = norm_quote.split()
    contract_words = norm_contract.split()

    if not quote_words or len(quote_words) > len(contract_words):
        return QuoteMatch(False, -1, -1, "", 0.0)

    window = len(quote_words)
    best_score = 0.0
    best_start = -1

    for i in range(len(contract_words) - window + 1):
        window_words = contract_words[i : i + window]
        matches = sum(1 for a, b in zip(quote_words, window_words) if a == b)
        score = matches / window
        if score > best_score:
            best_score = score
            best_start = i

    if best_score >= threshold:
        matched_words = contract_words[best_start : best_start + window]
        matched_text = " ".join(matched_words)
        char_start = norm_contract.find(matched_text)
        return QuoteMatch(
            matched=True,
            start=char_start if char_start >= 0 else 0,
            end=(char_start + len(matched_text)) if char_start >= 0 else len(matched_text),
            matched_text=matched_text,
            similarity=best_score,
        )

    return QuoteMatch(False, -1, -1, "", best_score)


def validate_article_ref(article_ref: str, index) -> bool:
    numbers = re.findall(r"\d+", article_ref)
    if not numbers:
        return False
    return any(index.article_exists(n) for n in numbers)
