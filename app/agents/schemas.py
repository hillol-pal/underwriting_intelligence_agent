"""Pydantic contracts for specialist output. The model cannot mint finding ids."""
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProposedStatus(str, Enum):
    EXTRACTED = "extracted"
    UNRESOLVED = "unresolved"
    PENDING = "pending"
    INSUFFICIENT = "insufficient"


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str | None = None
    filename: str | None = None
    page_number: int = Field(ge=1)
    quoted_source_text: str = Field(min_length=8, max_length=800)
    section_kind: str | None = None

    @model_validator(mode="after")
    def locator(self) -> "Citation":
        if not (self.document_id or self.filename):
            raise ValueError("citation needs document_id or filename")
        return self


class StepReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_id: str
    status: Literal["completed", "insufficient"]
    gap: str | None = None


class PolicyTopic(str, Enum):
    COVERAGE_WORDING = "coverage_wording"
    EXCLUSION = "exclusion"
    ENDORSEMENT = "endorsement"
    INSURED_PERIOD = "insured_period"
    SCHEDULE = "schedule"
    OTHER = "other"


class PolicyEffect(str, Enum):
    DESCRIBES_COVER = "describes_cover"
    EXCLUDES = "excludes"
    WAIVES_FOR_GLASS_ONLY = "waives_for_glass_only"
    DEFINES_PERIOD = "defines_period"
    UNKNOWN = "unknown"


class PolicyClause(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: PolicyTopic
    effect: PolicyEffect
    fact: str = Field(min_length=3, max_length=200)
    normalized_value: str | None = Field(default=None, max_length=500)
    citation: Citation
    proposed_status: ProposedStatus = ProposedStatus.EXTRACTED
    confidence: float = Field(default=0.5, ge=0, le=1)
    ledger_refs: list[str] = Field(default_factory=list)
    next_action: str | None = Field(default=None, max_length=300)


class PolicyAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_name: Literal["PolicyAnalysis"] = "PolicyAnalysis"
    evidence_sufficient: bool
    steps: list[StepReport]
    clauses: list[PolicyClause] = Field(default_factory=list, max_length=12)
    gaps: list[str] = Field(default_factory=list, max_length=8)


class EvidenceKind(str, Enum):
    INCIDENT_DATE = "incident_date"
    INCEPTION_DATE = "inception_date"
    PARTY = "party"
    VEHICLE = "vehicle"
    LOCATION = "location"
    DAMAGE = "damage"
    OTHER = "other"


class EvidenceFact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: EvidenceKind
    fact: str = Field(min_length=3, max_length=200)
    normalized_value: str | None = Field(default=None, max_length=500)
    citation: Citation
    proposed_status: ProposedStatus = ProposedStatus.EXTRACTED
    confidence: float = Field(default=0.5, ge=0, le=1)
    ledger_refs: list[str] = Field(default_factory=list)
    next_action: str | None = Field(default=None, max_length=300)


class EvidenceAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_name: Literal["EvidenceAnalysis"] = "EvidenceAnalysis"
    evidence_sufficient: bool
    steps: list[StepReport]
    facts: list[EvidenceFact] = Field(default_factory=list, max_length=16)
    gaps: list[str] = Field(default_factory=list, max_length=8)


class ContradictionKind(str, Enum):
    DATE_ORDER = "date_order"
    DATE_DISAGREEMENT = "date_disagreement"
    DAMAGE_VS_PHOTOS = "damage_vs_photos"
    OTHER = "other"


class ContradictionCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: ContradictionKind
    summary: str = Field(min_length=3, max_length=300)
    left_ledger_ref: str | None = None
    right_ledger_ref: str | None = None
    left_value: str | None = None
    right_value: str | None = None
    citation: Citation
    next_action: str = Field(min_length=3, max_length=300)
    confidence: float = Field(default=0.5, ge=0, le=1)


class ContradictionAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_name: Literal["ContradictionAnalysis"] = "ContradictionAnalysis"
    evidence_sufficient: bool
    steps: list[StepReport]
    contradictions: list[ContradictionCandidate] = Field(default_factory=list, max_length=8)
    unresolved_material: bool
    gaps: list[str] = Field(default_factory=list, max_length=8)


class LossLineKind(str, Enum):
    PRE_EXISTING = "pre_existing"
    COLLISION = "collision"
    INVOICE = "invoice"
    OTHER = "other"


class LossLine(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: LossLineKind
    description: str = Field(min_length=3, max_length=200)
    amount_text: str = Field(min_length=2, max_length=40)
    citation: Citation
    confidence: float = Field(default=0.5, ge=0, le=1)


class LossAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_name: Literal["LossAnalysis"] = "LossAnalysis"
    evidence_sufficient: bool
    steps: list[StepReport]
    lines: list[LossLine] = Field(default_factory=list, max_length=12)
    gaps: list[str] = Field(default_factory=list, max_length=8)


class StepOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_id: str
    specialist: Literal["policy", "evidence", "contradiction", "loss"]
    status: Literal["completed", "insufficient", "failed", "skipped", "blocked"]
    evidence_sufficient: bool = False
    error: str | None = None


class SupervisorResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_name: Literal["SupervisorResult"] = "SupervisorResult"
    claim_id: str
    plan_id: str
    outcomes: list[StepOutcome]
    advisory_summary: str = Field(max_length=800)
