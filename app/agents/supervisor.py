"""Agent stubs — Deep Agent supervisor and specialists."""
from abc import ABC, abstractmethod
from typing import Any

from app.core.models import Finding


class BaseSpecialist(ABC):
    """Base class for investigation specialists."""

    @abstractmethod
    def investigate(self, claim_id: str, context: dict[str, Any]) -> list[Finding]:
        """Produce structured findings for the Evidence Ledger."""
        pass


class EvidenceAnalyst(BaseSpecialist):
    def investigate(self, claim_id: str, context: dict[str, Any]) -> list[Finding]:
        # TODO: Extract facts from documents via retrieval + structured extraction
        return []


class PolicyAnalyst(BaseSpecialist):
    def investigate(self, claim_id: str, context: dict[str, Any]) -> list[Finding]:
        # TODO: Retrieve applicable clauses, exclusions, endorsements
        return []


class ContradictionAnalyst(BaseSpecialist):
    def investigate(self, claim_id: str, context: dict[str, Any]) -> list[Finding]:
        # TODO: Detect and record unresolved contradictions
        return []


class LossAssessor(BaseSpecialist):
    def investigate(self, claim_id: str, context: dict[str, Any]) -> list[Finding]:
        # TODO: Estimate exposure from repair estimates and invoices
        return []


class InvestigationSupervisor:
    """Deep Agent supervisor stub. Will use deepagents + LangGraph in Phase 2."""

    def __init__(self):
        self.specialists = {
            "evidence": EvidenceAnalyst(),
            "policy": PolicyAnalyst(),
            "contradiction": ContradictionAnalyst(),
            "loss": LossAssessor(),
        }

    def plan_and_investigate(self, claim_id: str) -> dict[str, Any]:
        """Plan investigation and delegate to specialists."""
        # TODO: Use Deep Agent to plan, then run specialists, update Evidence Ledger
        return {"status": "planned", "claim_id": claim_id, "specialists_invoked": list(self.specialists.keys())}
