"""
contract_loader.py
==================
Load a contract from PDF / DOCX / TXT / raw string and segment it into clauses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ContractDoc:
    text: str
    clauses: list[dict]
    source: str


# Clause boundary patterns (Arabic + English contracts)
_CLAUSE_PATTERNS = [
    # Arabic ordinals: أولاً، ثانياً  or  البند الأول
    re.compile(r"\n\s*(?:البند|المادة|الفقرة)\s+", re.UNICODE),
    # Numbered: 1. / 1) / (1) / ١. / ١)
    re.compile(r"\n\s*[\(]?[0-9٠-٩]+[\.\)]\s+"),
    # Lettered: (أ) / (a) / a)
    re.compile(r"\n\s*[\(][أ-يa-z][\)]\s+"),
    # Dash/bullet items
    re.compile(r"\n\s*[-–—•]\s+"),
]


def _extract_text_pdf(path: Path) -> str:
    import pymupdf
    doc = pymupdf.open(str(path))
    pages = []
    for page in doc:
        pages.append(page.get_text())
    doc.close()
    return "\n".join(pages)


def _extract_text_docx(path: Path) -> str:
    from docx import Document
    doc = Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def _extract_text_txt(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _segment_clauses(text: str) -> list[dict]:
    boundaries: list[int] = [0]

    for pattern in _CLAUSE_PATTERNS:
        for m in pattern.finditer(text):
            boundaries.append(m.start())

    # Also split on double newlines (paragraph boundaries)
    for m in re.finditer(r"\n\s*\n", text):
        boundaries.append(m.start())

    boundaries = sorted(set(boundaries))

    clauses = []
    for i, start in enumerate(boundaries):
        end = boundaries[i + 1] if i + 1 < len(boundaries) else len(text)
        chunk = text[start:end].strip()
        if len(chunk) < 20:
            continue
        clauses.append({
            "id": f"clause-{len(clauses) + 1}",
            "text": chunk,
            "start": start,
            "end": end,
        })

    if not clauses and text.strip():
        clauses.append({
            "id": "clause-1",
            "text": text.strip(),
            "start": 0,
            "end": len(text),
        })

    return clauses


def load_contract(source: str | Path) -> ContractDoc:
    path = Path(source) if not isinstance(source, Path) else source

    if path.exists():
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            text = _extract_text_pdf(path)
        elif suffix in (".docx", ".doc"):
            text = _extract_text_docx(path)
        else:
            text = _extract_text_txt(path)
        src_name = path.name
    else:
        text = str(source)
        src_name = "raw_text"

    clauses = _segment_clauses(text)
    return ContractDoc(text=text, clauses=clauses, source=src_name)
