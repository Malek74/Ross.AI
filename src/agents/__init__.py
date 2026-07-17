"""Domain specialists for the Egyptian-law paralegal."""

from src.agents.base_agent import DomainAgent
from src.agents.labour_agent import LabourAgent, create_labour_agent
from src.agents.orchestrator import ParalegalOrchestrator

__all__ = ["DomainAgent", "LabourAgent", "create_labour_agent", "ParalegalOrchestrator"]
