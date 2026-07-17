"""
playbook_loader.py
==================
Load a domain playbook YAML and return its checks as structured data.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_PLAYBOOKS_DIR = Path(__file__).parent.parent / "playbooks"


def load_playbook(path: str | Path | None = None, domain: str = "civil") -> dict:
    if path is None:
        path = _PLAYBOOKS_DIR / f"{domain}.yaml"
    path = Path(path)
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_checks(playbook: dict) -> list[dict]:
    return playbook.get("checks", [])


def format_rubric(playbook: dict) -> str:
    checks = get_checks(playbook)
    lines = []
    for c in checks:
        lines.append(
            f"- [{c['check_id']}] {c['title_en']} ({c['title_ar']}) "
            f"| {c['article_ref']} | {c['criticality']}\n"
            f"  Rule: {c['rule']}"
        )
    return "\n".join(lines)
