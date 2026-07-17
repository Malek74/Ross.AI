"""LLM-powered synthesis: merge, dedupe, and resolve multi-domain audit flags."""

from __future__ import annotations

import json
from typing import Any

from src.llm_client import get_client, settings
from src.prompt_templates import SYNTHESIZER_SYSTEM


def synthesize_flags(
    consultations: dict[str, dict[str, Any]],
    *,
    fallback_summary: str = "",
) -> dict[str, Any]:
    """Merge specialist results into one cited memo via an LLM call.

    For single-domain results with no conflicts, skips the LLM call and
    returns a fast deduped result. For multi-domain or when conflicts are
    possible, uses the synthesizer LLM to merge properly.
    """
    live_results = {
        domain: result
        for domain, result in consultations.items()
        if result.get("status") != "recognized_not_available"
    }
    stub_domains = [
        domain
        for domain, result in consultations.items()
        if result.get("status") == "recognized_not_available"
    ]

    all_flags_count = sum(len(r.get("flags", [])) for r in live_results.values())

    if len(live_results) <= 1 and all_flags_count <= 1:
        return _fast_dedup(consultations, fallback_summary, stub_domains)

    return _llm_synthesize(live_results, stub_domains, fallback_summary)


def _fast_dedup(
    consultations: dict[str, dict[str, Any]],
    fallback_summary: str,
    stub_domains: list[str],
) -> dict[str, Any]:
    """Quick path: single domain or trivial results — no LLM needed."""
    flags_by_domain: dict[str, list[dict[str, Any]]] = {}
    seen: set[tuple[str, str]] = set()
    summary_parts: list[str] = []

    for domain, result in consultations.items():
        if result.get("status") == "recognized_not_available":
            continue
        if result.get("summary"):
            summary_parts.append(result["summary"])
        flags: list[dict[str, Any]] = []
        for flag in result.get("flags", []):
            key = (flag.get("evidence_span", ""), flag.get("article_ref", ""))
            if key not in seen:
                seen.add(key)
                flags.append(flag)
        if flags:
            flags_by_domain[domain] = flags

    summary = fallback_summary or " ".join(summary_parts)
    if stub_domains:
        summary += f" (Note: {', '.join(stub_domains)} specialist(s) not yet available.)"

    return {"summary": summary, "flags_by_domain": flags_by_domain}


def _llm_synthesize(
    live_results: dict[str, dict[str, Any]],
    stub_domains: list[str],
    fallback_summary: str,
) -> dict[str, Any]:
    """Use the LLM to merge multi-domain findings with conflict resolution."""
    specialist_data: list[dict[str, Any]] = []
    for domain, result in live_results.items():
        specialist_data.append({
            "domain": domain,
            "summary": result.get("summary", ""),
            "flags": result.get("flags", []),
        })
    if stub_domains:
        for domain in stub_domains:
            specialist_data.append({
                "domain": domain,
                "status": "recognized_not_available",
            })

    user_content = (
        "Specialist findings to synthesize:\n\n"
        + json.dumps(specialist_data, ensure_ascii=False, indent=2)
    )

    client = get_client()
    response = client.chat.completions.create(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": SYNTHESIZER_SYSTEM},
            {"role": "user", "content": user_content},
        ],
        temperature=0.0,
        max_tokens=4096,
        extra_body=settings.extra_body,
    )

    raw = response.choices[0].message.content or ""

    try:
        parsed = _parse_json(raw)
        if isinstance(parsed, dict) and "flags_by_domain" in parsed:
            return {
                "summary": parsed.get("summary", fallback_summary),
                "flags_by_domain": parsed["flags_by_domain"],
            }
    except (json.JSONDecodeError, ValueError):
        pass

    return _fast_dedup(
        {d: r for d, r in live_results.items()},
        fallback_summary or raw,
        stub_domains,
    )


def _parse_json(raw: str) -> Any:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0].strip()
    return json.loads(text)
