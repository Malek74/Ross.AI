"""
corpus_loader.py
================
Load, clean, and structure Egyptian-law article datasets from Hugging Face.

Two sources are supported:
  1. TawasulAI/egyptian-law-articles  — article-level, bilingual (Civil Code spine)
  2. dataflare/egypt-legal-corpus     — document-level, Arabic only (multi-domain breadth)

Each source produces a list of Article dicts:
  {
      "id":        str,   # e.g. "civil-42" or "labour-art-15"
      "number":    str,   # article number as a string (may be "42", "42bis", etc.)
      "domain":    str,   # "civil" | "labour" | "commercial" | ...
      "text_ar":   str,   # Arabic text (normalized)
      "text_en":   str,   # English text (normalized / empty for non-bilingual sources)
      "raw_ar":    str,   # Arabic text before normalization (for evidence spans)
      "source":    str,   # dataset name
  }
"""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path
from typing import Iterator

from tqdm import tqdm

# Inline import so this module works standalone too
try:
    from src.arabic_normalize import normalize_document, clean_ocr
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from src.arabic_normalize import normalize_document, clean_ocr

logger = logging.getLogger(__name__)

# ── Type alias ────────────────────────────────────────────────────────────────
Article = dict  # typed above in docstring for clarity


# ── TawasulAI source ─────────────────────────────────────────────────────────

def _stitch_tawasul(rows: list[dict]) -> list[dict]:
    """
    Merge page-split articles that share the same article `number`.
    TawasulAI has OCR-split articles across consecutive page rows.
    """
    seen: dict[str, dict] = {}
    order: list[str] = []

    for row in rows:
        num = str(row.get("number", "")).strip()
        if not num:
            continue
        if num not in seen:
            seen[num] = {
                "number": num,
                "text_ar": clean_ocr(row.get("text_ar") or ""),
                "text_en": row.get("text_en") or "",
                "page": row.get("page"),
            }
            order.append(num)
        else:
            # Append continuation text
            seen[num]["text_ar"] += " " + clean_ocr(row.get("text_ar") or "")
            seen[num]["text_en"] += " " + (row.get("text_en") or "")

    return [seen[n] for n in order]


def load_tawasul(domain: str = "civil") -> list[Article]:
    """
    Load TawasulAI/egyptian-law-articles from Hugging Face.

    Parameters
    ----------
    domain : str
        Stored as `article["domain"]`; defaults to "civil" since this
        dataset is essentially the Egyptian Civil Code.

    Returns
    -------
    list[Article]
    """
    import json
    from huggingface_hub import hf_hub_download

    logger.info("Loading TawasulAI/egyptian-law-articles …")
    path = hf_hub_download(
        repo_id="TawasulAI/egyptian-law-articles",
        filename="egyptian_law_articles.json",
        repo_type="dataset"
    )
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    raw_rows = data.get("articles", [])
    logger.info("  %d raw rows fetched", len(raw_rows))

    stitched = _stitch_tawasul(raw_rows)
    logger.info("  %d articles after page-stitch dedup", len(stitched))

    articles: list[Article] = []
    for row in tqdm(stitched, desc="Normalizing Civil articles", unit="art"):
        raw_ar = row["text_ar"]
        articles.append(
            {
                "id": f"{domain}-{row['number']}",
                "number": row["number"],
                "domain": domain,
                "text_ar": normalize_document(raw_ar),
                "text_en": row["text_en"].strip(),
                "raw_ar": raw_ar,
                "source": "TawasulAI/egyptian-law-articles",
            }
        )

    logger.info("  Loaded %d Civil Code articles.", len(articles))
    return articles


# ── dataflare source ──────────────────────────────────────────────────────────

# Article-boundary patterns common in Egyptian legal texts
_ARTICLE_HEADER = re.compile(
    r"""
    (?:                          # match boundary
      (?:^|\n)                   # start or newline
      (?:مادة|المادة)\s*         # مادة / المادة
      (?:\()?                    # optional open paren
      ([٠-٩0-9]+)               # article number (Arabic-Indic or ASCII)
      (?:\))?                    # optional close paren
      [\s\-–—:]*                 # separator
    )
    """,
    re.VERBOSE,
)


def _chunk_document(law_text: str, law_name: str, domain: str) -> list[dict]:
    """
    Split a full law document (one dataflare row) into article chunks.
    Uses the مادة / المادة header pattern as a boundary marker.
    Falls back to ~1500-char chunks if no headers found.
    """
    from src.arabic_normalize import normalize_numerals  # local import

    parts = _ARTICLE_HEADER.split(law_text)
    # split() returns [pre_text, num1, body1, num2, body2, ...]
    if len(parts) <= 1:
        # No article markers — fall back to fixed-size chunks
        chunk_size = 1500
        chunks = []
        for i, start in enumerate(range(0, len(law_text), chunk_size)):
            body = law_text[start : start + chunk_size]
            chunks.append(
                {
                    "number": f"chunk-{i+1}",
                    "text_ar": body,
                }
            )
        return chunks

    chunks: list[dict] = []
    # parts[0] is text before the first article header (preamble / title)
    for i in range(1, len(parts), 2):
        num = normalize_numerals(parts[i].strip())
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        chunks.append({"number": num, "text_ar": body})

    return chunks


# Mapping of Arabic law names to internal domain keys
_DOMAIN_FILTER: dict[str, list[str]] = {
    "labour": ["قانون العمل", "العمل 14"],
    "commercial": [
        "التجارة بوجه عام",
        "الالتزامات والعقود التجارية",
        "الأوراق التجارية",
        "الاوراق التجارية",
        "المحل التجارى",
        "الاثبات فى المواد التجارية",
        "الدفاتر التجارية",
        "الشركات التجارية",
        "قانون التجارة",
    ],
    "criminal": ["قانون العقوبات", "الإجراءات الجنائية"],
    "civil_procedure": ["قانون المرافعات", "قانون الإثبات"],
    "rent": ["قانون الايجارات", "قانون الإيجار"],
    "personal_status": ["الأحوال الشخصية", "قانون الخلع", "قانون الطفل"],
}


def _match_domain(law_name: str) -> str | None:
    """Return the internal domain key for a law_name row, or None if not matched."""
    for domain, keywords in _DOMAIN_FILTER.items():
        if any(kw in law_name for kw in keywords):
            return domain
    return None


def load_dataflare(domain: str) -> list[Article]:
    """
    Load dataflare/egypt-legal-corpus, filter to the requested domain, and
    re-chunk into article-level items.

    Parameters
    ----------
    domain : str
        One of the keys in _DOMAIN_FILTER (e.g. "labour", "commercial").

    Returns
    -------
    list[Article]
    """
    if domain not in _DOMAIN_FILTER:
        raise ValueError(
            f"Unknown domain '{domain}'. Supported: {list(_DOMAIN_FILTER)}"
        )

    from datasets import load_dataset  # type: ignore

    logger.info("Loading dataflare/egypt-legal-corpus for domain=%s …", domain)
    ds = load_dataset("dataflare/egypt-legal-corpus", split="train")

    keywords = _DOMAIN_FILTER[domain]
    filtered = [
        row for row in ds if any(kw in (row.get("law_name") or "") for kw in keywords)
    ]
    logger.info(
        "  %d/%d rows matched domain '%s'", len(filtered), len(ds), domain
    )

    articles: list[Article] = []
    for row in tqdm(filtered, desc=f"Chunking {domain} laws", unit="law"):
        raw_text = row.get("text") or row.get("content") or ""
        raw_text = clean_ocr(raw_text)
        chunks = _chunk_document(raw_text, row.get("law_name", ""), domain)

        for chunk in chunks:
            raw_ar = chunk["text_ar"]
            article_id = f"{domain}-{row.get('law_name','?')[:20]}-{chunk['number']}"
            articles.append(
                {
                    "id": article_id,
                    "number": chunk["number"],
                    "domain": domain,
                    "text_ar": normalize_document(raw_ar),
                    "text_en": "",  # dataflare is Arabic-only
                    "raw_ar": raw_ar,
                    "source": "dataflare/egypt-legal-corpus",
                }
            )

    logger.info("  Produced %d article chunks for domain '%s'.", len(articles), domain)
    return articles


# ── Official Labour PDF / Eval datasets (DECISIONS.md B7) ─────────────────────

def load_official_labour_pdf(pdf_path: Path) -> list[Article]:
    """
    Extract articles from the official Ministry of Labour Law 14/2025 PDF.
    Used to supplement or correct the dataflare corpus to ensure currency.
    """
    import fitz  # pymupdf
    logger.info("Extracting official Labour Law 14/2025 from %s", pdf_path)
    
    if not pdf_path.exists():
        logger.warning("Official Labour PDF not found at %s. Skipping.", pdf_path)
        return []

    doc = fitz.open(pdf_path)
    full_text = []
    for page in doc:
        full_text.append(page.get_text())
    doc.close()
    
    raw_text = "\n".join(full_text)
    raw_text = clean_ocr(raw_text)
    
    # We chunk it using the same header pattern
    chunks = _chunk_document(raw_text, "قانون العمل 14 لسنة 2025", "labour")
    articles: list[Article] = []
    for chunk in chunks:
        raw_ar = chunk["text_ar"]
        articles.append(
            {
                "id": f"labour-official-14-2025-{chunk['number']}",
                "number": chunk["number"],
                "domain": "labour",
                "text_ar": normalize_document(raw_ar),
                "text_en": "",
                "raw_ar": raw_ar,
                "source": "official_labour_pdf",
            }
        )
    logger.info("  Produced %d article chunks from official PDF.", len(articles))
    return articles


def load_eval_dataset(repo_id: str = "tarekys5/egyptian_legal_v2") -> list[dict]:
    """
    Load an evaluation dataset (e.g., IRAC-style question/answers) for testing.
    As per decisions, this is kept OUTSIDE the statute index.
    """
    from datasets import load_dataset  # type: ignore
    
    logger.info("Loading eval dataset from %s ...", repo_id)
    ds = load_dataset(repo_id, split="train")
    
    # Just return as a list of dictionaries for the orchestrator/evaluator to use
    eval_data = [row for row in ds]
    logger.info("  Loaded %d evaluation records.", len(eval_data))
    return eval_data


# ── Persistence ───────────────────────────────────────────────────────────────

def save_corpus(articles: list[Article], path: Path) -> None:
    """Save a corpus list to a JSONL file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for art in articles:
            f.write(json.dumps(art, ensure_ascii=False) + "\n")
    logger.info("Saved %d articles → %s", len(articles), path)


def load_corpus(path: Path) -> list[Article]:
    """Load a corpus from a JSONL file."""
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


# ── CLI entry point ───────────────────────────────────────────────────────────

def _cli() -> None:
    """
    Usage:
        python -m src.corpus_loader civil
        python -m src.corpus_loader labour
    """
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(
        description="Download and clean Egyptian law articles."
    )
    parser.add_argument(
        "domain",
        choices=["civil"] + list(_DOMAIN_FILTER),
        help="Domain corpus to build.",
    )
    parser.add_argument(
        "--out-dir",
        default="data/corpus",
        help="Output directory (default: data/corpus).",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_path = out_dir / args.domain / "articles.jsonl"

    if args.domain == "civil":
        articles = load_tawasul(domain="civil")
    else:
        articles = load_dataflare(domain=args.domain)

    save_corpus(articles, out_path)
    print(f"\n✓ {len(articles)} articles saved to {out_path}")


if __name__ == "__main__":
    _cli()
