"""
agents/tools.py
===============
Tool definitions (OpenAI function-calling schema) and execution logic
for the domain specialist agent.

Tools:
  • search_statutes — semantic search over the domain's FAISS index
  • get_article     — fetch one article by number
  • flag_risk       — record a risk (validates quote + article existence)
  • finish          — agent signals it is done
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from src.evidence_validation import validate_quote, validate_article_ref

logger = logging.getLogger(__name__)

# ── OpenAI function-calling schemas ──────────────────────────────────────────

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_statutes",
            "description": (
                "Semantic search over this domain's statute articles. "
                "Returns top-k matching articles with Arabic and English text."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural-language query (Arabic or English).",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of results (default: 8).",
                        "default": 8,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_article",
            "description": "Fetch one article by its number to read the full text or follow a cross-reference.",
            "parameters": {
                "type": "object",
                "properties": {
                    "number": {
                        "type": "string",
                        "description": "Article number, e.g. '42', '125'.",
                    },
                },
                "required": ["number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "flag_risk",
            "description": (
                "Record a contract risk. The quote MUST be an exact substring "
                "of the contract text. The article number MUST exist in the index. "
                "Invalid citations are REJECTED."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "clause_id": {
                        "type": "string",
                        "description": "ID of the contract clause (e.g. 'clause-3').",
                    },
                    "quote": {
                        "type": "string",
                        "description": "Exact substring from the contract text that constitutes the risk.",
                    },
                    "article_number": {
                        "type": "string",
                        "description": "Civil Code article number (e.g. '125').",
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["HIGH", "MEDIUM", "LOW"],
                        "description": "HIGH = void/voidable, MEDIUM = enforceability risk, LOW = best-practice.",
                    },
                    "rationale": {
                        "type": "string",
                        "description": "Brief explanation of why this clause is risky, referencing the article.",
                    },
                },
                "required": ["clause_id", "quote", "article_number", "severity", "rationale"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": "Signal that the audit is complete. Call this when you have thoroughly reviewed the contract.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Brief summary of findings.",
                    },
                },
                "required": ["summary"],
            },
        },
    },
]


# ── Tool execution context ───────────────────────────────────────────────────

@dataclass
class ToolContext:
    domain_index: Any
    contract_text: str
    flags: list[dict] = field(default_factory=list)
    finished: bool = False
    finish_summary: str = ""


def execute_tool(name: str, arguments: dict, ctx: ToolContext) -> dict:
    if name == "search_statutes":
        return _exec_search(arguments, ctx)
    elif name == "get_article":
        return _exec_get_article(arguments, ctx)
    elif name == "flag_risk":
        return _exec_flag_risk(arguments, ctx)
    elif name == "finish":
        return _exec_finish(arguments, ctx)
    else:
        return {"error": f"Unknown tool: {name}"}


def _exec_search(args: dict, ctx: ToolContext) -> dict:
    query = args.get("query", "")
    top_k = args.get("top_k", 8)
    results = ctx.domain_index.search(query, top_k=top_k)
    return {
        "results": [
            {
                "number": r["number"],
                "text_ar": r["text_ar"][:500],
                "text_en": r.get("text_en", "")[:500],
                "score": round(r["score"], 4),
            }
            for r in results
        ]
    }


def _exec_get_article(args: dict, ctx: ToolContext) -> dict:
    number = args.get("number", "")
    article = ctx.domain_index.get_article(number)
    if article is None:
        return {"error": f"Article {number} not found in the index."}
    return {
        "number": article["number"],
        "text_ar": article.get("text_ar", ""),
        "text_en": article.get("text_en", ""),
    }


def _exec_flag_risk(args: dict, ctx: ToolContext) -> dict:
    quote = args.get("quote", "")
    article_number = args.get("article_number", "")

    # Validate quote is a real substring
    match = validate_quote(quote, ctx.contract_text)
    if not match.matched:
        logger.warning("REJECTED flag: quote not found in contract (similarity=%.2f)", match.similarity)
        return {
            "accepted": False,
            "reason": f"Quote not found in contract text (best similarity: {match.similarity:.2f}). "
                      "Use an exact substring from the contract.",
        }

    # Validate article exists
    if not validate_article_ref(article_number, ctx.domain_index):
        logger.warning("REJECTED flag: article %s not in index", article_number)
        return {
            "accepted": False,
            "reason": f"Article {article_number} not found in the index. "
                      "Use search_statutes or get_article to find the correct number.",
        }

    article = ctx.domain_index.get_article(article_number)

    flag = {
        "clause_id": args.get("clause_id", ""),
        "quote": quote,
        "quote_match": {
            "start": match.start,
            "end": match.end,
            "similarity": match.similarity,
        },
        "article_number": article_number,
        "article_ar": article.get("text_ar", "") if article else "",
        "article_en": article.get("text_en", "") if article else "",
        "severity": args.get("severity", "MEDIUM"),
        "rationale": args.get("rationale", ""),
    }

    ctx.flags.append(flag)
    logger.info("ACCEPTED flag: art %s, severity %s", article_number, flag["severity"])
    return {"accepted": True, "flag_index": len(ctx.flags) - 1}


def _exec_finish(args: dict, ctx: ToolContext) -> dict:
    ctx.finished = True
    ctx.finish_summary = args.get("summary", "")
    return {"status": "done", "total_flags": len(ctx.flags)}
