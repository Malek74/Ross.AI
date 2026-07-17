"""
arabic_normalize.py
===================
Arabic text normalization for retrieval.

Run before embedding either corpus articles or contract text.
Order matters: strip diacritics first, then normalise, then tatweel/punctuation.

Reference forms kept:
  • alef variants  → ا
  • hamza on/under alef → ء  (bare hamza, not removed)
  • alef-wasla → ا
  • taa marbuta → ه  (sometimes ة → ه helps retrieval cross-spelling)
  • waw variants → و
  • yaa variants / alef maqsura → ي
"""

import re
import unicodedata


# ── Arabic Unicode ranges ─────────────────────────────────────────────────────
# Tashkeel / diacritics (harakat + shadda + sukun + maddah + hamza-above/below)
_TASHKEEL = re.compile(
    r"[\u064B-\u065F\u0610-\u061A\u06D6-\u06DC\u06DF-\u06E4\u06E7\u06E8\u06EA-\u06ED]"
)

# Tatweel (kashida/elongation stroke)
_TATWEEL = re.compile(r"\u0640")

# Alef variants → bare alef ا
_ALEF = re.compile(r"[إأآٱ\u0671]")

# Alef-wasla (ٱ = \u0671 already covered above; keep pattern explicit)
_ALEF_WASLA = re.compile(r"\u0671")

# Taa marbuta → haa (helps cross-spelling retrieval)
_TAA_MARBUTA = re.compile(r"ة")

# Waw with hamza → plain waw
_WAW_HAMZA = re.compile(r"ؤ")

# Yaa with hamza / alef maqsura → yaa
_YAA_VARIANTS = re.compile(r"[ئى]")

# Repeated whitespace
_MULTI_SPACE = re.compile(r"\s+")

# Arabic-Indic numerals → ASCII numerals
_ARABIC_INDIC = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

# Persian/Extended-Arabic-Indic
_PERSIAN_INDIC = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")


def strip_diacritics(text: str) -> str:
    """Remove tashkeel (harakat, shadda, sukun, maddah, etc.)."""
    return _TASHKEEL.sub("", text)


def normalize_alef(text: str) -> str:
    """Fold all alef forms to bare alef ا."""
    return _ALEF.sub("ا", text)


def normalize_hamza(text: str) -> str:
    """Fold waw-with-hamza and yaa-with-hamza to their base letters."""
    text = _WAW_HAMZA.sub("و", text)
    text = _YAA_VARIANTS.sub("ي", text)
    return text


def normalize_taa_marbuta(text: str) -> str:
    """Fold taa marbuta → haa (improves recall on Arabic plurals/constructs)."""
    return _TAA_MARBUTA.sub("ه", text)


def normalize_numerals(text: str) -> str:
    """Convert Arabic-Indic and Persian-Indic numerals to ASCII."""
    return text.translate(_ARABIC_INDIC).translate(_PERSIAN_INDIC)


def remove_tatweel(text: str) -> str:
    """Remove the kashida / elongation stroke (tatweel)."""
    return _TATWEEL.sub("", text)


def clean_whitespace(text: str) -> str:
    return _MULTI_SPACE.sub(" ", text).strip()


def normalize(text: str, *, taa_marbuta: bool = True) -> str:
    """
    Full normalization pipeline.

    Parameters
    ----------
    text : str
        Raw Arabic (or mixed) text.
    taa_marbuta : bool
        If True (default), fold ة → ه.  Set False if you need to preserve
        morphological distinction (e.g. NER tagging).

    Returns
    -------
    str
        Normalized text, suitable for embedding or BM25 indexing.
    """
    text = strip_diacritics(text)
    text = remove_tatweel(text)
    text = normalize_alef(text)
    text = normalize_hamza(text)
    if taa_marbuta:
        text = normalize_taa_marbuta(text)
    text = normalize_numerals(text)
    text = clean_whitespace(text)
    return text


# ── OCR artifact cleaning ─────────────────────────────────────────────────────

# Common garbage sequences seen in TawasulAI dataset (extend as needed)
_OCR_GARBAGE = re.compile(
    r"(دودو|[ـ]{3,}|\u200b|\u200c|\u200d|\ufeff|\u202a-\u202e)"
)

# Repeated punctuation (e.g. "،،،" → "،")
_REPEATED_PUNCT = re.compile(r"([،؛:.،!؟]){2,}")


def clean_ocr(text: str) -> str:
    """
    Remove known OCR garbage from Egyptian-corpus datasets (TawasulAI, dataflare).
    Should be run BEFORE normalize() on raw corpus text.
    """
    text = _OCR_GARBAGE.sub(" ", text)
    text = _REPEATED_PUNCT.sub(r"\1", text)
    text = clean_whitespace(text)
    return text


def normalize_document(text: str) -> str:
    """Convenience: clean OCR noise then fully normalize."""
    return normalize(clean_ocr(text))


# ── Smoke test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    samples = [
        "إنَّ الْعَقْدَ يُعَدُّ مُبْرَماً",           # tashkeel
        "الأَلِفُ وَاوُ الْهَمْزَةِ",                  # alef/hamza variants
        "مُـكـتـبـة",                                   # tatweel
        "٢٠٢٥ م",                                       # Arabic-Indic numeral
        "دودودودو garbage text",                         # OCR junk
        "ما الذي يجعل العقد قابلاً للإبطال؟",           # query example from AGENTS.md
    ]
    for s in samples:
        print(f"IN : {s!r}")
        print(f"OUT: {normalize_document(s)!r}")
        print()
