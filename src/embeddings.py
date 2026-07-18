"""
embeddings.py
=============
Build and query per-domain FAISS indexes from article corpora.

Architecture (per AGENTS.md §2):
  • One FAISS index per domain  (data/index/<domain>/)
  • All indexes use the SAME embedding model (enforced via a metadata lock file)
  • Build once, query many times
  • The search_statutes() / get_article() tools in agents/tools.py call this module

Index directory layout:
  data/index/<domain>/
    ├── index.faiss       — flat L2 FAISS index
    ├── metadata.json     — {model, dim, count, built_at, source}
    └── articles.jsonl    — parallel article records (same row order as index vectors)

Usage
-----
  # Build (one-time, run from project root):
  python -m src.embeddings build civil
  python -m src.embeddings build labour

  # Query (at runtime):
  from src.embeddings import DomainIndex
  idx = DomainIndex.load("civil")
  results = idx.search("عقد باطل", top_k=8)
  article = idx.get_article("42")
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import faiss
import numpy as np
from tqdm import tqdm

# Allow running as script from repo root
_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE.parent))

from src.arabic_normalize import normalize_document
from src.llm_client import embed, settings as _llm_settings

logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).parent.parent
_INDEX_ROOT = _REPO_ROOT / "data" / "index"
_CORPUS_ROOT = _REPO_ROOT / "data" / "corpus"

# ── Constants ─────────────────────────────────────────────────────────────────

_EMBED_BATCH_SIZE = 64        # embed() already batches; this is per progress tick
_METADATA_FILENAME = "metadata.json"
_INDEX_FILENAME = "index.faiss"
_ARTICLES_FILENAME = "articles.jsonl"


# ── Domain index ──────────────────────────────────────────────────────────────

@dataclass
class DomainIndex:
    """
    A loaded, query-ready FAISS index for one domain.

    Attributes
    ----------
    domain : str
    index : faiss.Index
    articles : list[dict]  — parallel to index rows
    metadata : dict
    _number_to_idx : dict[str, int]  — article number → row index for get_article()
    """

    domain: str
    index: Any = field(repr=False)  # faiss.Index
    articles: list[dict] = field(repr=False)
    metadata: dict = field(default_factory=dict)
    _number_to_idx: dict[str, int] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        # Keys are numeral-normalized so lookups succeed regardless of whether
        # the caller (or the LLM) writes "552", "٥٥٢", or "مادة (552)".
        self._number_to_idx = {}
        for i, art in enumerate(self.articles):
            key = self._normalize_number(art["number"])
            self._number_to_idx.setdefault(key, i)

    @staticmethod
    def _normalize_number(number: str) -> str:
        from src.arabic_normalize import normalize_numerals

        return normalize_numerals(str(number)).strip()

    # ── Factories ─────────────────────────────────────────────────────────────

    @classmethod
    def load(cls, domain: str, index_root: Path | None = None) -> "DomainIndex":
        """
        Load a pre-built index from disk.

        Raises
        ------
        FileNotFoundError if the index hasn't been built yet.
        RuntimeError if the stored embedding model != the current one.
        """
        root = (index_root or _INDEX_ROOT) / domain
        idx_path = root / _INDEX_FILENAME
        meta_path = root / _METADATA_FILENAME
        arts_path = root / _ARTICLES_FILENAME

        if not idx_path.exists():
            raise FileNotFoundError(
                f"No FAISS index found for domain '{domain}' at {root}. "
                f"Run: python -m src.embeddings build {domain}"
            )

        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        _check_model_consistency(meta, domain)

        faiss_index = faiss.read_index(str(idx_path))

        with open(arts_path, encoding="utf-8") as f:
            articles = [json.loads(line) for line in f if line.strip()]

        logger.info(
            "Loaded %s index: %d articles, dim=%d, model=%s",
            domain,
            len(articles),
            meta["dim"],
            meta["model"],
        )
        return cls(domain=domain, index=faiss_index, articles=articles, metadata=meta)

    # ── Search ────────────────────────────────────────────────────────────────

    def search(self, query: str, top_k: int | None = None) -> list[dict]:
        """
        Semantic search over this domain's article index.

        Parameters
        ----------
        query : str
            Natural-language query (Arabic or English).
        top_k : int
            Number of results to return (default: settings.top_k).

        Returns
        -------
        list[dict]
            Ranked list of article dicts augmented with a `score` key.
            Articles are filtered to score > 0 (L2 distance < threshold).
        """
        k = top_k or _llm_settings.top_k
        # Normalize query for retrieval
        norm_query = normalize_document(query)
        vec = embed([norm_query])[0]
        q = np.array([vec], dtype="float32")
        faiss.normalize_L2(q)

        distances, indices = self.index.search(q, k)

        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx < 0:  # FAISS sentinel for "not enough results"
                continue
            art = dict(self.articles[idx])
            art["score"] = float(1.0 - dist)  # cosine-like: higher = better
            results.append(art)

        # Sort by score descending (FAISS returns ascending L2)
        results.sort(key=lambda x: x["score"], reverse=True)
        return results

    # ── Article lookup ────────────────────────────────────────────────────────

    def get_article(self, number: str) -> dict | None:
        """
        Fetch one article by its number (for cross-reference following).

        Parameters
        ----------
        number : str
            Article number as a string, e.g. "42", "42bis", "142".

        Returns
        -------
        dict | None
        """
        idx = self._number_to_idx.get(self._normalize_number(number))
        if idx is None:
            return None
        return self.articles[idx]

    def article_exists(self, number: str) -> bool:
        return self._normalize_number(number) in self._number_to_idx


# ── Index builder ─────────────────────────────────────────────────────────────

def build_index(
    domain: str,
    articles: list[dict],
    *,
    index_root: Path | None = None,
    batch_size: int = _EMBED_BATCH_SIZE,
) -> DomainIndex:
    """
    Embed all articles and write a FAISS IndexFlatIP index to disk.

    Uses Inner Product (IP) on L2-normalized vectors = cosine similarity.
    This is the standard setup for semantic search with normalized vectors.

    Parameters
    ----------
    domain : str
    articles : list[dict]   — from corpus_loader.load_tawasul() / load_dataflare()
    index_root : Path       — override default data/index/
    batch_size : int        — how many articles to embed per API call

    Returns
    -------
    DomainIndex  — ready for immediate querying (also persisted to disk)
    """
    if not articles:
        raise ValueError(f"Cannot build empty index for domain '{domain}'")

    root = (index_root or _INDEX_ROOT) / domain
    root.mkdir(parents=True, exist_ok=True)

    embedding_model = _llm_settings.embedding_model
    _enforce_model_lock(root, embedding_model, domain)

    # ── Build text list for embedding ─────────────────────────────────────────
    # Embed the Arabic text (pre-normalized). Prepend article number for context.
    texts: list[str] = []
    for art in articles:
        prefix = f"مادة {art['number']}: " if art.get("number") else ""
        body = art.get("text_ar") or art.get("raw_ar", "")
        texts.append(prefix + body)

    logger.info(
        "Embedding %d articles for domain '%s' using %s …",
        len(texts),
        domain,
        embedding_model,
    )

    # ── Embed in batches with progress bar ────────────────────────────────────
    all_vectors: list[list[float]] = []
    for i in tqdm(range(0, len(texts), batch_size), desc=f"Embedding {domain}"):
        batch = texts[i : i + batch_size]
        vecs = embed(batch)
        all_vectors.extend(vecs)

    dim = len(all_vectors[0])
    matrix = np.array(all_vectors, dtype="float32")
    faiss.normalize_L2(matrix)  # in-place L2 normalization → cosine similarity

    # ── Build FAISS index (IndexFlatIP for exact cosine search) ──────────────
    faiss_index = faiss.IndexFlatIP(dim)
    faiss_index.add(matrix)

    # ── Persist ───────────────────────────────────────────────────────────────
    idx_path = root / _INDEX_FILENAME
    arts_path = root / _ARTICLES_FILENAME
    meta_path = root / _METADATA_FILENAME

    faiss.write_index(faiss_index, str(idx_path))

    with open(arts_path, "w", encoding="utf-8") as f:
        for art in articles:
            f.write(json.dumps(art, ensure_ascii=False) + "\n")

    metadata = {
        "domain": domain,
        "model": embedding_model,
        "dim": dim,
        "count": len(articles),
        "built_at": datetime.now(timezone.utc).isoformat(),
        "source": articles[0].get("source", "unknown") if articles else "unknown",
    }
    meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info(
        "✓ Built %s index: %d articles, dim=%d → %s",
        domain,
        len(articles),
        dim,
        root,
    )

    return DomainIndex(domain=domain, index=faiss_index, articles=articles, metadata=metadata)


# ── Model consistency enforcement ─────────────────────────────────────────────

_LOCK_FILENAME = "embedding_model.lock"


def _enforce_model_lock(root: Path, model: str, domain: str) -> None:
    """
    On first build: write the model name to a lock file.
    On subsequent builds: ensure the same model is used.

    Raises RuntimeError if a different model is attempted.
    """
    # Global lock lives at data/index/ (root parent)
    global_lock = root.parent / _LOCK_FILENAME
    domain_lock = root / _LOCK_FILENAME

    for lock_path in [global_lock, domain_lock]:
        if lock_path.exists():
            locked_model = lock_path.read_text().strip()
            if locked_model != model:
                raise RuntimeError(
                    f"Embedding model mismatch! Existing indexes were built with "
                    f"'{locked_model}' but current EMBEDDING_MODEL='{model}'. "
                    f"To change the model, delete all indexes under data/index/ "
                    f"and rebuild from scratch."
                )
        else:
            lock_path.write_text(model)


def _check_model_consistency(meta: dict, domain: str) -> None:
    """Warn if the loaded index used a different model than currently configured."""
    current = _llm_settings.embedding_model
    stored = meta.get("model")
    if stored and stored != current:
        logger.warning(
            "Domain '%s' index was built with '%s' but EMBEDDING_MODEL='%s'. "
            "Queries will be WRONG. Rebuild the index or fix EMBEDDING_MODEL.",
            domain,
            stored,
            current,
        )


# ── Convenience: load or build ────────────────────────────────────────────────

def load_or_build(domain: str, articles: list[dict] | None = None) -> DomainIndex:
    """
    Load the index if it exists, otherwise build it from `articles`.

    Parameters
    ----------
    domain : str
    articles : list[dict] | None
        Required if the index doesn't exist yet.
    """
    try:
        return DomainIndex.load(domain)
    except FileNotFoundError:
        if articles is None:
            raise ValueError(
                f"No index for domain '{domain}' and no articles provided to build one."
            )
        return build_index(domain, articles)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _cli() -> None:
    """
    Usage:
        python -m src.embeddings build civil
        python -m src.embeddings build labour
        python -m src.embeddings smoke civil "عقد باطل"
    """
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    parser = argparse.ArgumentParser(description="Build or query a domain FAISS index.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # ── build sub-command ────────────────────────────────────────────────────
    bp = sub.add_parser("build", help="Build a FAISS index for a domain.")
    bp.add_argument(
        "domain",
        choices=["civil", "labour", "commercial", "criminal"],
        help="Domain to build.",
    )
    bp.add_argument(
        "--corpus-dir",
        default="data/corpus",
        help="Directory containing <domain>/articles.jsonl (default: data/corpus).",
    )

    # ── smoke sub-command ────────────────────────────────────────────────────
    sp = sub.add_parser("smoke", help="Run a retrieval smoke test.")
    sp.add_argument("domain", help="Domain index to query.")
    sp.add_argument("query", help="Query string (Arabic or English).")
    sp.add_argument("--top-k", type=int, default=5)

    args = parser.parse_args()

    if args.cmd == "build":
        from src.corpus_loader import load_tawasul, load_dataflare, load_corpus

        corpus_path = Path(args.corpus_dir) / args.domain / "articles.jsonl"
        if corpus_path.exists():
            logger.info("Loading corpus from %s …", corpus_path)
            articles = load_corpus(corpus_path)
        elif args.domain == "civil":
            logger.info("Corpus file not found — downloading from HuggingFace …")
            articles = load_tawasul()
            # save it so we don't re-download
            from src.corpus_loader import save_corpus
            save_corpus(articles, corpus_path)
        else:
            logger.info("Corpus file not found — downloading from HuggingFace …")
            articles = load_dataflare(args.domain)
            from src.corpus_loader import save_corpus
            save_corpus(articles, corpus_path)

        build_index(args.domain, articles)

    elif args.cmd == "smoke":
        idx = DomainIndex.load(args.domain)
        print(f"\nSmoke test — domain={args.domain}  query={args.query!r}\n")
        results = idx.search(args.query, top_k=args.top_k)
        for i, art in enumerate(results, 1):
            print(f"  [{i}] art {art['number']}  score={art['score']:.4f}")
            print(f"       AR: {art['text_ar'][:120]} …")
            if art.get("text_en"):
                print(f"       EN: {art['text_en'][:120]} …")
            print()


if __name__ == "__main__":
    _cli()
