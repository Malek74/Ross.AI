"""Cheap-model domain-routing hint for the paralegal orchestrator."""

from __future__ import annotations

import json
from typing import Any

from src.llm_client import chat_classifier


def classify_domains(text: str, registry: dict[str, dict]) -> list[dict[str, Any]]:
    """Return ranked domain hints; malformed model output safely becomes no hint."""
    choices = [
        {"domain": domain, "label": entry["label"], "description": entry["description"]}
        for domain, entry in registry.items()
    ]
    messages = [
        {
            "role": "system",
            "content": (
                "Classify the Egyptian legal domains implicated by the input. "
                "Choose only from the supplied domains. Return strict JSON only: "
                '[{"domain":"...","confidence":0.0}].'
            ),
        },
        {"role": "user", "content": f"Domains:\n{json.dumps(choices, ensure_ascii=False)}\n\nInput:\n{text[:12000]}"},
    ]
    try:
        raw = chat_classifier(messages)
        data = _parse_json(raw)
    except Exception:
        return _embedding_fallback(text, registry)

    ranked: list[dict[str, Any]] = []
    for item in data if isinstance(data, list) else []:
        domain = item.get("domain") if isinstance(item, dict) else None
        confidence = item.get("confidence", 0.0) if isinstance(item, dict) else 0.0
        if domain not in registry:
            continue
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            continue
        if 0.0 <= confidence <= 1.0:
            ranked.append({"domain": domain, "confidence": confidence})
    if not ranked:
        # LLM gave no usable hint — fall back to retrieval similarity
        return _embedding_fallback(text, registry)
    return sorted(ranked, key=lambda item: item["confidence"], reverse=True)


def _embedding_fallback(text: str, registry: dict[str, dict]) -> list[dict[str, Any]]:
    """Rank domains by top-hit similarity in each domain's own FAISS index.

    No LLM call — keeps auto-routing alive when the classifier model is
    rate-limited or returns malformed output.

    DISABLED BY DEFAULT (CLASSIFIER_EMBED_FALLBACK=true to enable): raw cosine
    scores are not calibrated across heterogeneous indexes (Q&A-style rows
    outscore statute rows on any question phrasing), so the ranking misroutes.
    Needs per-domain score normalization before it can be trusted.
    """
    import os

    if os.environ.get("CLASSIFIER_EMBED_FALLBACK", "false").lower() != "true":
        return []
    scores: list[dict[str, Any]] = []
    for domain in registry:
        try:
            index = _cached_index(domain)
            results = index.search(text[:2000], top_k=1)
        except Exception:
            continue  # stub domain / missing index
        if results:
            scores.append(
                {"domain": domain, "confidence": round(float(results[0].get("score") or 0.0), 3)}
            )
    return sorted(scores, key=lambda item: item["confidence"], reverse=True)


_INDEX_CACHE: dict[str, Any] = {}


def _cached_index(domain: str) -> Any:
    if domain not in _INDEX_CACHE:
        from src.embeddings import DomainIndex

        _INDEX_CACHE[domain] = DomainIndex.load(domain)
    return _INDEX_CACHE[domain]


def _parse_json(raw: str) -> Any:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0].strip()
    return json.loads(text)
