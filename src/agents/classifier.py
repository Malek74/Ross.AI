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
    except (ValueError, TypeError, json.JSONDecodeError):
        return []

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
    return sorted(ranked, key=lambda item: item["confidence"], reverse=True)


def _parse_json(raw: str) -> Any:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0].strip()
    return json.loads(text)
