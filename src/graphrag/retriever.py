"""
Graph-expanded retrieval: vector search → top-k, then follow cross-reference
edges to pull related articles the query didn't match directly.

This is the core GraphRAG capability described in AGENTS.md §2:
  search_statutes(query) → vector top-k → graph-expand via edges → merged results
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).parent.parent.parent
_INDEX_ROOT = _REPO_ROOT / "data" / "index"

_ARABIC_INDIC = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def _to_ascii(s: str) -> str:
    return s.translate(_ARABIC_INDIC)


class CrossReferenceGraph:
    """In-memory cross-reference graph for one domain."""

    def __init__(self, graph_data: dict) -> None:
        self.outgoing: dict[str, list[str]] = defaultdict(list)
        self.incoming: dict[str, list[str]] = defaultdict(list)

        for edge in graph_data.get("edges", []):
            src, tgt = str(edge["source"]), str(edge["target"])
            self.outgoing[src].append(tgt)
            self.incoming[tgt].append(src)

        self.stats = graph_data.get("stats", {})

    @classmethod
    def load(cls, domain: str, index_root: Path | None = None) -> "CrossReferenceGraph":
        root = (index_root or _INDEX_ROOT) / domain
        graph_path = root / "graph.json"

        if not graph_path.exists():
            logger.warning(
                "No graph.json for domain '%s' — graph expansion disabled.", domain
            )
            return cls({"edges": []})

        data = json.loads(graph_path.read_text(encoding="utf-8"))
        logger.info(
            "Loaded %s cross-reference graph: %d edges",
            domain,
            len(data.get("edges", [])),
        )
        return cls(data)

    def neighbors(self, article_num: str, *, direction: str = "both") -> list[str]:
        num = _to_ascii(str(article_num))
        result: list[str] = []
        if direction in ("out", "both"):
            result.extend(self.outgoing.get(num, []))
        if direction in ("in", "both"):
            result.extend(self.incoming.get(num, []))
        return list(dict.fromkeys(result))

    def expand(
        self,
        seed_articles: list[str],
        *,
        max_hops: int = 1,
        max_expanded: int = 5,
    ) -> list[str]:
        """
        BFS from seed articles along cross-reference edges.

        Returns article numbers discovered (excluding seeds), capped at max_expanded.
        """
        seeds = {_to_ascii(str(s)) for s in seed_articles}
        visited = set(seeds)
        frontier = list(seeds)

        expanded: list[str] = []

        for _hop in range(max_hops):
            next_frontier: list[str] = []
            for node in frontier:
                for neighbor in self.neighbors(node):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        next_frontier.append(neighbor)
                        expanded.append(neighbor)
                        if len(expanded) >= max_expanded:
                            return expanded
            frontier = next_frontier
            if not frontier:
                break

        return expanded


class GraphExpandedRetriever:
    """
    Wraps a DomainIndex with graph expansion.

    Flow: query → vector search top-k → take top results' article numbers →
    follow cross-reference edges → fetch those articles → merge and re-rank.
    """

    def __init__(self, domain_index: Any, graph: CrossReferenceGraph | None = None):
        self.index = domain_index
        self.graph = graph or CrossReferenceGraph.load(domain_index.domain)

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        expand_top: int = 3,
        max_hops: int = 1,
        max_expanded: int = 4,
    ) -> list[dict]:
        """
        Graph-expanded search.

        1. Vector search for top_k articles.
        2. Take the top `expand_top` results' article numbers.
        3. Follow cross-reference edges (up to max_hops) to find related articles.
        4. Fetch those expanded articles and append them (marked with source="graph").
        5. Return merged results, vector hits first, then graph-expanded.
        """
        vector_results = self.index.search(query, top_k=top_k)

        seed_nums = [
            _to_ascii(str(r["number"])) for r in vector_results[:expand_top]
        ]

        expanded_nums = self.graph.expand(
            seed_nums, max_hops=max_hops, max_expanded=max_expanded
        )

        already_returned = {_to_ascii(str(r["number"])) for r in vector_results}
        graph_results: list[dict] = []

        for num in expanded_nums:
            if num in already_returned:
                continue
            art = self.index.get_article(num)
            if art:
                enriched = dict(art)
                enriched["score"] = 0.0
                enriched["retrieval_source"] = "graph_expansion"
                graph_results.append(enriched)
                already_returned.add(num)

        for r in vector_results:
            r.setdefault("retrieval_source", "vector")

        return vector_results + graph_results
