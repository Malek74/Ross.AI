"""
Extract cross-reference edges from a corpus and persist the graph.

Each domain's corpus references other articles via patterns like:
  Arabic:  المادة ١٢٣ / المادتين ١٢٣ و ١٢٤ / المواد ١٢٠ إلى ١٢٥
  English: Article 123 / Articles 123 and 456 / Articles 12 to 15

The output is a JSON file per domain:
  data/index/<domain>/graph.json
  {
    "nodes": ["42", "131", ...],
    "edges": [{"source": "42", "target": "131"}, ...],
    "stats": {"node_count": ..., "edge_count": ..., ...}
  }
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from pathlib import Path

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).parent.parent.parent
_INDEX_ROOT = _REPO_ROOT / "data" / "index"

_ARABIC_INDIC = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")

_AR_LEGAL_KEYWORDS = re.compile(
    r"(?:المادة|المادتين|المواد|مادة|ماده|المنصوص|بموجب|أحكام|لنص|وفقاً|طبقاً)"
)

_EN_ARTICLE_REF = re.compile(r"[Aa]rticles?\s+(\d+)(?:\s+(?:and|to|or)\s+(\d+))?")
_EN_HEADER = re.compile(r"^Article\s+\d+\s*\n?")

_AR_NUMBER = re.compile(r"([٠-٩۰-۹0-9]{2,})")


def _to_ascii(s: str) -> str:
    return s.translate(_ARABIC_INDIC)


def _extract_refs_english(text: str, own: str, known: set[str]) -> set[str]:
    body = _EN_HEADER.sub("", text, count=1)
    refs: set[str] = set()
    for m in _EN_ARTICLE_REF.finditer(body):
        for g in m.groups():
            if g and g != own and g in known:
                refs.add(g)
    return refs


def _extract_refs_arabic(text: str, own: str, known: set[str]) -> set[str]:
    refs: set[str] = set()
    for m in _AR_NUMBER.finditer(text):
        num = _to_ascii(m.group(1))
        if num not in known or num == own:
            continue
        start = max(0, m.start() - 40)
        context = text[start : m.start()]
        if _AR_LEGAL_KEYWORDS.search(context):
            refs.add(num)
    return refs


def extract_cross_references(articles: list[dict]) -> dict:
    known = {_to_ascii(str(a["number"])) for a in articles}

    edges: list[dict[str, str]] = []
    seen_edges: set[tuple[str, str]] = set()

    for art in articles:
        own = _to_ascii(str(art["number"]))
        en = art.get("text_en", "")
        ar = art.get("raw_ar", "") or art.get("text_ar", "")

        refs = _extract_refs_english(en, own, known)
        refs |= _extract_refs_arabic(ar, own, known)

        for target in sorted(refs, key=lambda x: int(x) if x.isdigit() else 0):
            pair = (own, target)
            if pair not in seen_edges:
                seen_edges.add(pair)
                edges.append({"source": own, "target": target})

    nodes = sorted(known, key=lambda x: int(x) if x.isdigit() else 0)

    ref_counts = Counter(e["target"] for e in edges)

    stats = {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "articles_with_outgoing_refs": len({e["source"] for e in edges}),
        "most_referenced": ref_counts.most_common(10),
    }

    return {"nodes": nodes, "edges": edges, "stats": stats}


def build_cross_reference_graph(
    domain: str,
    articles: list[dict],
    *,
    index_root: Path | None = None,
) -> dict:
    root = (index_root or _INDEX_ROOT) / domain
    root.mkdir(parents=True, exist_ok=True)

    graph = extract_cross_references(articles)
    graph_path = root / "graph.json"
    graph_path.write_text(
        json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    logger.info(
        "Built %s cross-reference graph: %d nodes, %d edges → %s",
        domain,
        graph["stats"]["node_count"],
        graph["stats"]["edge_count"],
        graph_path,
    )
    return graph
