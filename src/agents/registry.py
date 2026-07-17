"""
agents/registry.py
==================
Live + stub agent registry. The classifier and orchestrator read this
to know which domains exist and which are live.
"""

from __future__ import annotations

from src.agents.base_agent import DomainAgent, StubAgent

REGISTRY: dict[str, dict] = {
    "civil": {
        "agent": DomainAgent(
            name="civil",
            index_path="data/index/civil",
            playbook_path="playbooks/civil.yaml",
            domain_label="Civil Code",
            law_ref="Egyptian Civil Code (Law 131/1948)",
        ),
        "live": True,
        "label": "Civil Code",
        "description": "Contracts, obligations, capacity, consent, property, civil liability.",
    },
    "labour": {
        "agent": StubAgent("labour"),
        "live": False,
        "label": "Labour",
        "description": "Employment contracts, wages, termination (Labour Law 14/2025).",
    },
    "commercial": {
        "agent": DomainAgent(
            name="commercial",
            index_path="data/index/commercial",
            playbook_path="playbooks/commercial.yaml",
            domain_label="Commercial Code",
            law_ref="Egyptian Commercial Code (Law 17/1999)",
        ),
        "live": True,
        "label": "Commercial",
        "description": "Commercial contracts, merchant obligations, negotiable instruments, commercial agency, sale of establishments.",
    },
    "criminal": {
        "agent": StubAgent("criminal"),
        "live": False,
        "label": "Criminal",
        "description": "Criminal offences, penalties, criminal procedure.",
    },
    "finance": {
        "agent": StubAgent("finance"),
        "live": False,
        "label": "Finance / FRA",
        "description": "Financial regulation, tax, FRA oversight.",
    },
}


def get_agent(domain: str):
    entry = REGISTRY.get(domain)
    if entry is None:
        return None
    return entry["agent"]


def list_agents() -> list[dict]:
    return [
        {"domain": k, "label": v["label"], "live": v["live"], "description": v["description"]}
        for k, v in REGISTRY.items()
    ]


def live_agents() -> list[str]:
    return [k for k, v in REGISTRY.items() if v["live"]]
