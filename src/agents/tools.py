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
    revisions: list[dict[str, Any]] = field(default_factory=list)
    drafts: list[dict[str, Any]] = field(default_factory=list)
    finished_summary: str | None = None
    _retriever: GraphExpandedRetriever | None = field(default=None, init=False, repr=False)
    _get_article_calls: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        self._retriever = GraphExpandedRetriever(self.index)

    def definitions(self, *, mode: str = "audit") -> list[dict[str, Any]]:
        """OpenAI-compatible function schemas; the model may only use these actions."""
        core = [
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
                    "name": "revise_clause",
                    "description": "Rewrite a flagged contract clause to comply with the cited article. Preserve the original intent. Use only after flag_risk identified the issue.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "original_clause": {"type": "string", "description": "The exact clause text from the contract to revise."},
                            "revised_clause": {"type": "string", "description": "The rewritten clause that complies with the law."},
                            "article_ref": {"type": "string", "description": "Article number that governs the revision."},
                            "rationale": {"type": "string", "description": "Why this revision makes the clause compliant."},
                        },
                        "required": ["original_clause", "revised_clause", "article_ref", "rationale"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "draft_clause",
                    "description": "Draft a new contract clause grounded in retrieved articles. Use search_statutes first to find the governing articles.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "topic": {"type": "string", "description": "The subject of the clause (e.g. 'termination', 'liability cap')."},
                            "clause_text": {"type": "string", "description": "The drafted clause text."},
                            "article_ref": {"type": "string", "description": "Article number(s) grounding this clause."},
                            "rationale": {"type": "string", "description": "How the clause satisfies the cited articles."},
                        },
                        "required": ["topic", "clause_text", "article_ref", "rationale"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "validate_draft",
                    "description": "Self-audit a drafted or revised clause against the index. Search for articles that could conflict with the clause.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "clause_text": {"type": "string", "description": "The clause to validate."},
                        },
                        "required": ["clause_text"],
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
        return core

    def search_statutes(self, query: str, top_k: int = 5) -> dict[str, Any]:
        results = self._retriever.search(query, top_k=min(max(top_k, 1), 10))
        return {"results": [self._public_article(article) for article in results]}

    def get_article(self, number: str) -> dict[str, Any]:
        # Hard rail: weak models sometimes crawl the corpus article-by-article
        # instead of acting; cap lookups so the loop budget goes to real work.
        self._get_article_calls += 1
        if self._get_article_calls > 20:
            return {
                "found": False,
                "number": number,
                "note": "Article-lookup budget exhausted. Use what you have retrieved and proceed with the task (flag_risk / revise_clause / draft_clause / finish).",
            }
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
        cited_article = self._resolve_article(article)
        if cited_article is None:
            return {"accepted": False, "reason": "Article does not exist in this specialist's corpus."}
        flag = {
            "check_id": check_id or None, "severity": severity, "evidence_span": quote,
            "quote_match": {"start": match.start, "end": match.end, "similarity": match.similarity},
            "article_ref": str(cited_article["number"]), "article_ar": cited_article.get("raw_ar", cited_article.get("text_ar", "")),
            "article_en": cited_article.get("text_en", ""), "rationale": rationale,
        }
        self.flags.append(flag)
        return {"accepted": True, "flag": flag}

    def revise_clause(self, original_clause: str, revised_clause: str, article_ref: str, rationale: str) -> dict[str, Any]:
        if not self.contract:
            return {"accepted": False, "reason": "No contract was supplied."}
        match = validate_quote(original_clause, self.contract)
        if not match.matched:
            return {"accepted": False, "reason": f"Original clause not found in contract (best similarity: {match.similarity:.2f})."}
        if not validate_article_ref(article_ref, self.index):
            return {"accepted": False, "reason": "Article does not exist in this specialist's corpus."}
        revision = {
            "clause_original": original_clause,
            "clause_revised": revised_clause,
            "article_ref": article_ref,
            "rationale": rationale,
            "quote_match": {"start": match.start, "end": match.end, "similarity": match.similarity},
        }
        self.revisions.append(revision)
        return {"accepted": True, "revision": revision}

    def draft_clause(self, topic: str, clause_text: str, article_ref: str, rationale: str) -> dict[str, Any]:
        if not validate_article_ref(article_ref, self.index):
            return {"accepted": False, "reason": "Article does not exist in this specialist's corpus."}
        draft = {
            "topic": topic,
            "text": clause_text,
            "article_ref": article_ref,
            "rationale": rationale,
        }
        self.drafts.append(draft)
        return {"accepted": True, "draft": draft}

    def validate_draft(self, clause_text: str) -> dict[str, Any]:
        results = self._retriever.search(clause_text, top_k=5)
        potential_conflicts = []
        for article in results:
            potential_conflicts.append({
                "number": str(article["number"]),
                "text_ar": article.get("raw_ar", article.get("text_ar", "")),
                "text_en": article.get("text_en", ""),
                "score": article.get("score"),
            })
        return {"clause": clause_text, "related_articles": potential_conflicts}

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

    def _resolve_article(self, ref: str) -> dict[str, Any] | None:
        """Resolve a model-written ref ('مادة ٥٥٢ من القانون') to an index row.

        Mirrors validate_article_ref: exact lookup first, then each embedded
        number — so a ref that validates always resolves.
        """
        import re

        article = self.index.get_article(ref)
        if article is not None:
            return article
        for num in re.findall(r"\d+", str(ref)):
            article = self.index.get_article(num)
            if article is not None:
                return article
        return None

    @staticmethod
    def _public_article(article: dict[str, Any]) -> dict[str, Any]:
        result = {
            "number": str(article["number"]), "text_ar": article.get("raw_ar", article.get("text_ar", "")),
            "text_en": article.get("text_en", ""), "score": article.get("score"),
        }
        if article.get("retrieval_source"):
            result["retrieval_source"] = article["retrieval_source"]
        return result
