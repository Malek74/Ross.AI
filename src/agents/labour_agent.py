"""Labour-law specialist binding the reusable DomainAgent to Labour resources."""

from __future__ import annotations

from src.agents.base_agent import DomainAgent


class LabourAgent(DomainAgent):
    """Experimental specialist for Egyptian Labour Law; corpus currency must be verified."""

    def __init__(self) -> None:
        super().__init__(
            name="labour",
            index_path="data/index/labour",
            playbook_path="playbooks/labour.yaml",
            domain_label="Labour Law",
            law_ref="Egyptian Labour Law 14/2025 (pending corpus validation)",
        )


def create_labour_agent() -> LabourAgent:
    """Factory used by the registry once Labour Law 14/2025 is validated."""
    return LabourAgent()
