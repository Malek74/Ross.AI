#!/usr/bin/env python3
"""
build_corpus.py
===============
One-shot script: download → clean → embed → index for each domain.

Run from repo root:
    python build_corpus.py [--domain civil] [--smoke]

M0 target (AGENTS.md §10):
  • Download TawasulAI/egyptian-law-articles
  • Normalize + stitch page-split articles
  • Embed via OpenRouter (qwen/qwen3-embedding-8b)
  • Build data/index/civil/ FAISS index
  • Run a retrieval smoke test

Example:
    python build_corpus.py --domain civil --smoke
    python build_corpus.py --domain labour --smoke
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# ── Ensure src/ is importable from repo root ──────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))

from src.corpus_loader import (
    load_tawasul,
    load_dataflare,
    save_corpus,
    load_corpus,
)
from src.embeddings import build_index, DomainIndex
from src.graphrag.builder import build_cross_reference_graph

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

CORPUS_ROOT = Path("data/corpus")
INDEX_ROOT = Path("data/index")


def run_smoke_test(domain: str, queries: list[str] | None = None) -> None:
    """Load the index and run a few retrieval queries."""
    default_queries = {
        "civil": [
            "ما الذي يجعل العقد قابلاً للإبطال؟",        # What makes a contract voidable?
            "what makes a contract voidable",
            "الأهلية القانونية للتعاقد",                    # Legal capacity to contract
            "شروط صحة العقد",                               # Conditions for contract validity
        ],
        "labour": [
            "إنهاء عقد العمل",                             # Termination of employment
            "الأجر والراتب",                                # Wage and salary
        ],
        "commercial": [
            "الأوراق التجارية الكمبيالة",                   # Bills of exchange
            "بيع المحل التجاري",                             # Sale of commercial establishment
            "الوكالة التجارية",                              # Commercial agency
            "التزامات التاجر",                               # Merchant obligations
        ],
    }
    queries = queries or default_queries.get(domain, ["عقد"])

    print(f"\n{'='*60}")
    print(f"SMOKE TEST — domain: {domain}")
    print(f"{'='*60}")

    idx = DomainIndex.load(domain)
    print(f"Index: {idx.metadata['count']} articles, dim={idx.metadata['dim']}, model={idx.metadata['model']}\n")

    for q in queries:
        print(f"Query: {q!r}")
        results = idx.search(q, top_k=3)
        if not results:
            print("  ⚠ No results returned!")
        for i, art in enumerate(results, 1):
            ar_preview = art["text_ar"][:100].replace("\n", " ")
            en_preview = art.get("text_en", "")[:80].replace("\n", " ")
            print(f"  [{i}] Article {art['number']}  score={art['score']:.4f}")
            print(f"       AR: {ar_preview}…")
            if en_preview:
                print(f"       EN: {en_preview}…")
        print()

    # Test get_article() lookup
    sample_num = "42"
    art = idx.get_article(sample_num)
    if art:
        print(f"get_article('{sample_num}') ✓  → {art['text_ar'][:80]}…")
    else:
        # Try first article number in the index
        if idx.articles:
            first_num = str(idx.articles[0]["number"])
            art = idx.get_article(first_num)
            if art:
                print(f"get_article('{first_num}') ✓  → {art['text_ar'][:80]}…")
    print()


def build_domain(domain: str, *, force_rebuild: bool = False) -> None:
    corpus_path = CORPUS_ROOT / domain / "articles.jsonl"
    index_path = INDEX_ROOT / domain / "index.faiss"

    t0 = time.time()

    # ── Step 1: load or download corpus ──────────────────────────────────────
    if corpus_path.exists() and not force_rebuild:
        logger.info("Corpus file found at %s — loading …", corpus_path)
        articles = load_corpus(corpus_path)
        logger.info("  Loaded %d articles.", len(articles))
    else:
        logger.info("Downloading corpus for domain '%s' …", domain)
        if domain == "civil":
            articles = load_tawasul(domain="civil")
        elif domain == "labour":
            # Labour Law 12/2003 (dataflare) is REPEALED by 14/2025 — statute
            # spine is the official gazette PDF; tarekys5 Q&A fills explanations.
            from src.corpus_loader import load_official_labour_pdf, load_tarekys5_as_articles

            pdf_path = Path("data/corpus/labour/labour_law_14_2025.pdf")
            articles = load_official_labour_pdf(pdf_path)
            official_numbers = {a["number"] for a in articles}
            articles.extend(
                load_tarekys5_as_articles(domain="labour", exclude_numbers=official_numbers)
            )
        elif domain == "commercial":
            articles = load_dataflare(domain="commercial")
            from src.corpus_loader import load_tarekys5_as_articles
            tarekys_articles = load_tarekys5_as_articles(domain="commercial")
            articles.extend(tarekys_articles)

        save_corpus(articles, corpus_path)
        logger.info("  Saved %d articles → %s", len(articles), corpus_path)

    t1 = time.time()
    logger.info("Corpus ready in %.1fs", t1 - t0)

    # ── Step 2: build cross-reference graph ─────────────────────────────────────
    graph_path = INDEX_ROOT / domain / "graph.json"
    if graph_path.exists() and not force_rebuild:
        logger.info("Graph already exists at %s — skipping.", graph_path)
    else:
        logger.info("Building cross-reference graph for domain '%s' …", domain)
        graph = build_cross_reference_graph(domain, articles)
        logger.info(
            "  Graph: %d nodes, %d edges",
            graph["stats"]["node_count"],
            graph["stats"]["edge_count"],
        )

    # ── Step 3: build FAISS index ─────────────────────────────────────────────
    if index_path.exists() and not force_rebuild:
        logger.info("Index already exists at %s — skipping build.", index_path)
        logger.info("  (Pass --force to rebuild.)")
    else:
        logger.info("Building FAISS index for domain '%s' …", domain)
        build_index(domain, articles)
        t2 = time.time()
        logger.info("Index built in %.1fs", t2 - t1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build corpus + FAISS index for Egyptian law domains."
    )
    parser.add_argument(
        "--domain",
        choices=["civil", "labour", "commercial", "criminal", "all"],
        default="civil",
        help="Domain to build (default: civil). Use 'all' for all supported.",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Run a retrieval smoke test after building.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-download and re-embed even if files exist.",
    )
    args = parser.parse_args()

    domains = (
        ["civil", "labour", "commercial"] if args.domain == "all" else [args.domain]
    )

    for domain in domains:
        logger.info("\n%s\nProcessing domain: %s\n%s", "─" * 50, domain.upper(), "─" * 50)
        build_domain(domain, force_rebuild=args.force)

        if args.smoke:
            run_smoke_test(domain)

    print("\n✓ Done.")


if __name__ == "__main__":
    main()
