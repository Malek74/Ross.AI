"""Constrained, evidence-aware tools available to a domain specialist."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.embeddings import DomainIndex
from src.evidence_validation import validate_quote, validate_article_ref
from src.graphrag.retriever import GraphExpandedRetriever


@dataclass
class DomainTools:
    """Tool boundary for one legal domain and one optional contract."""

    index: DomainIndex
    contract: str = ""
    flags: list[dict[str, Any]] = field(default_factory=list)
    finished_summary: str | None = None
    _retriever: GraphExpandedRetriever | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._retriever = GraphExpandedRetriever(self.index)

    def definitions(self) -> list[dict[str, Any]]:
        """OpenAI-compatible function schemas; the model may only use these actions."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "search_statutes",
                    "description": "Search only this specialist's statute corpus for articles relevant to the legal issue.",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}, "top_k": {"type": "integer", "minimum": 1, "maximum": 10}},
                        "required": ["query"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_article",
                    "description": "Fetch one article by number, including its Arabic and English text.",
                    "parameters": {
                        "type": "object",
                        "properties": {"number": {"type": "string"}},
                        "required": ["number"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "flag_risk",
                    "description": "Record a contract-audit finding. Use only when quote is an exact quote from the submitted contract and the article number exists.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "quote": {"type": "string"}, "article": {"type": "string"},
                            "severity": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
                            "rationale": {"type": "string"}, "check_id": {"type": "string"},
                        },
                        "required": ["quote", "article", "severity", "rationale"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "finish",
                    "description": "Finish the audit or legal-chat answer after gathering sufficient evidence.",
                    "parameters": {
                        "type": "object",
                        "properties": {"summary": {"type": "string"}},
                        "required": ["summary"],
                        "additionalProperties": False,
                    },
                },
            },
        ]

    def search_statutes(self, query: str, top_k: int = 5) -> dict[str, Any]:
        results = self._retriever.search(query, top_k=min(max(top_k, 1), 10))
        return {"results": [self._public_article(article) for article in results]}

    def get_article(self, number: str) -> dict[str, Any]:
        article = self.index.get_article(number)
        if article is None:
            return {"found": False, "number": number}
        return {"found": True, "article": self._public_article(article)}

    def flag_risk(self, quote: str, article: str, severity: str, rationale: str, check_id: str = "") -> dict[str, Any]:
        if not self.contract:
            return {"accepted": False, "reason": "No contract was supplied; risks require contract evidence."}
        match = validate_quote(quote, self.contract)
        if not match.matched:
            return {"accepted": False, "reason": f"Quote not found in contract (best similarity: {match.similarity:.2f}). Use an exact substring."}
        if not validate_article_ref(article, self.index):
            return {"accepted": False, "reason": "Article does not exist in this specialist's corpus."}
        cited_article = self.index.get_article(article) or {}
        flag = {
            "check_id": check_id or None, "severity": severity, "evidence_span": quote,
            "quote_match": {"start": match.start, "end": match.end, "similarity": match.similarity},
            "article_ref": str(cited_article["number"]), "article_ar": cited_article.get("raw_ar", cited_article.get("text_ar", "")),
            "article_en": cited_article.get("text_en", ""), "rationale": rationale,
        }
        self.flags.append(flag)
        return {"accepted": True, "flag": flag}

    def finish(self, summary: str) -> dict[str, Any]:
        self.finished_summary = summary
        return {"finished": True, "summary": summary}

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        handler = getattr(self, name, None)
        if handler is None or name.startswith("_"):
            return {"error": f"Unknown tool '{name}'."}
        try:
            return handler(**arguments)
        except (TypeError, ValueError) as exc:
            return {"error": f"Invalid arguments for {name}: {exc}"}

    @staticmethod
    def _public_article(article: dict[str, Any]) -> dict[str, Any]:
        result = {
            "number": str(article["number"]), "text_ar": article.get("raw_ar", article.get("text_ar", "")),
            "text_en": article.get("text_en", ""), "score": article.get("score"),
        }
        if article.get("retrieval_source"):
            result["retrieval_source"] = article["retrieval_source"]
        return result
