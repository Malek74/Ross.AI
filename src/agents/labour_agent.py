"""Labour-law specialist binding the reusable DomainAgent to Labour resources."""

from __future__ import annotations

from src.agents.base_agent import DomainAgent


class LabourAgent(DomainAgent):
    """Egyptian Labour Law No. 14 of 2025 specialist."""

    def __init__(self) -> None:
        super().__init__(
            name="labour",
            index_path="data/index/labour",
            playbook_path="playbooks/labour.yaml",
            domain_label="Labour Law",
            law_ref="Egyptian Labour Law No. 14 of 2025",
        )


def create_labour_agent() -> LabourAgent:
    """Factory used by the domain-specialist registry."""
    return LabourAgent()
