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
      (?:^|\s)                   # start or ANY whitespace (OCR text often has no newlines)
      (?:مادة|المادة)\s*         # مادة / المادة
      (?:\()?                    # optional open paren
      ([٠-٩0-9]+)               # article number (Arabic-Indic or ASCII)
      (?:\))?                    # optional close paren
      [\s]*[\-–—:)]              # header separator (excludes prose cross-references)
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
        row for row in ds 
        if any(kw in (row.get("law_name") or "") for kw in keywords)
        and "السعودي" not in (row.get("law_name") or "")
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
    import urllib.request
    
    if not pdf_path.exists():
        logger.info("Official Labour PDF not found. Downloading...")
        # labour.gov.eg copy has moved (404) — official-gazette mirror on manshurat.org
        url = "https://manshurat.org/sites/default/files/qnwn_lml_ljdyd_14_lsn_2025_m_q.pdf"
        try:
            pdf_path.parent.mkdir(parents=True, exist_ok=True)
            urllib.request.urlretrieve(url, pdf_path)
            logger.info("Downloaded official Labour Law 14/2025 PDF to %s", pdf_path)
        except Exception as e:
            logger.warning("Failed to download official Labour PDF: %s. Skipping.", e)
            return []

    logger.info("Extracting official Labour Law 14/2025 from %s", pdf_path)
    import unicodedata

    doc = fitz.open(pdf_path)
    raw_text = "\n".join(page.get_text() for page in doc)
    doc.close()

    # Gazette PDFs extract as Arabic presentation forms with REVERSED parens and
    # (inconsistently) reversed digit runs: article 142 extracts as "مادة)٢٤١(".
    # NFKC folds the ligatures; digits are disambiguated below by walking the
    # header sequence, which must ascend one article at a time.
    text = unicodedata.normalize("NFKC", raw_text)
    trans = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
    # مادة not preceded by an Arabic letter (excludes بالمادة/للمادة cross-refs)
    header = re.compile(r"(?<![ء-ي])م\s?ادة\s*\)\s*([0-9٠-٩۰-۹]+)\s*\(\s*:?")
    matches = list(header.finditer(text))

    articles: list[Article] = []
    prev = 0
    for i, m in enumerate(matches):
        digits = m.group(1).translate(trans)
        candidates = {int(digits), int(digits[::-1])}
        if prev + 1 in candidates:
            num = prev + 1
        else:
            bigger = sorted(c for c in candidates if c > prev)
            num = bigger[0] if bigger else max(candidates)
        prev = num

        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        raw_ar = text[body_start:body_end].strip()
        if not raw_ar:
            continue
        articles.append(
            {
                "id": f"labour-official-14-2025-{num}",
                "number": str(num),
                "domain": "labour",
                "text_ar": normalize_document(raw_ar),
                "text_en": "",
                "raw_ar": raw_ar,
                "source": "official_labour_pdf",
            }
        )
    logger.info(
        "  Extracted %d articles (numbers %s → %s) from official Labour Law 14/2025.",
        len(articles),
        articles[0]["number"] if articles else "-",
        articles[-1]["number"] if articles else "-",
    )
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


_QA_ARTICLE_NUM = re.compile(r"مادة\s*(?:الجزء\s+\S+\s*)?\(\s*([٠-٩0-9]+)\s*\)")


def load_tarekys5_as_articles(
    domain: str, exclude_numbers: set[str] | None = None
) -> list[Article]:
    """
    Extract the tarekys5 Q&A dataset and format it as Articles to be embedded
    in the FAISS index.

    Rows are filtered by the LAW TITLE in the `article` field (not the Q&A body,
    which lets other domains' rows leak in), and the real article number is
    parsed out of that title so citations validate. Rows whose parsed number is
    in `exclude_numbers` (already covered by statute text) get a "qa-" prefix
    instead of colliding with the statute row.
    """
    from datasets import load_dataset  # type: ignore
    logger.info("Loading tarekys5/egyptian_legal_v2 to embed for domain '%s' ...", domain)
    ds = load_dataset("tarekys5/egyptian_legal_v2", split="train")

    title_filters = {
        "labour": ["قانون العمل"],
        "commercial": ["قانون التجارة", "قانون التجاره"],
        "civil": ["القانون المدني"],
    }
    wanted = title_filters.get(domain, _DOMAIN_FILTER.get(domain, []))
    exclude_numbers = exclude_numbers or set()

    articles: list[Article] = []
    for i, row in enumerate(ds):
        title = str(row.get("article") or "")
        if not any(kw in title for kw in wanted):
            continue
        m = _QA_ARTICLE_NUM.search(title)
        if not m:
            continue
        from src.arabic_normalize import normalize_numerals
        parsed_num = normalize_numerals(m.group(1))
        number = f"qa-{parsed_num}" if parsed_num in exclude_numbers else parsed_num

        formatted_text = (
            f"سؤال: {row.get('instruction', '')}\n"
            f"التفاصيل: {row.get('input', '')}\n"
            f"الإجابة: {row.get('output', '')}\n"
            f"السند القانوني: {row.get('legal_basis', '')}"
        )
        
        articles.append({
            "id": f"tarekys5-qa-{i}",
            "number": number,
            "domain": domain,
            "text_ar": normalize_document(formatted_text),
            "text_en": "",
            "raw_ar": formatted_text,
            "source": "tarekys5/egyptian_legal_v2"
        })
        
    # Several Q&A rows can explain the same article — keep the longest per number
    # so the index has one canonical row per citation target.
    by_number: dict[str, Article] = {}
    for art in articles:
        prev = by_number.get(art["number"])
        if prev is None or len(art["raw_ar"]) > len(prev["raw_ar"]):
            by_number[art["number"]] = art
    articles = list(by_number.values())

    logger.info("  Filtered and formatted %d Q&A records for domain '%s'.", len(articles), domain)
    return articles


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
    elif args.domain == "labour":
        # Labour Law 12/2003 (dataflare) is REPEALED by 14/2025 — the statute
        # spine is the official gazette PDF; tarekys5 Q&A fills explanations.
        pdf_path = Path("data/corpus/labour/labour_law_14_2025.pdf")
        articles = load_official_labour_pdf(pdf_path)
        official_numbers = {a["number"] for a in articles}
        articles.extend(
            load_tarekys5_as_articles(domain="labour", exclude_numbers=official_numbers)
        )
    elif args.domain == "commercial":
        articles = load_dataflare(domain="commercial")
        tarekys_articles = load_tarekys5_as_articles(domain="commercial")
        articles.extend(tarekys_articles)
    else:
        articles = load_dataflare(domain=args.domain)

    save_corpus(articles, out_path)
    print(f"\n✓ {len(articles)} articles saved to {out_path}")


if __name__ == "__main__":
    _cli()
