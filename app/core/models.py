"""Core domain models and Evidence Ledger schemas."""
from datetime import datetime
from enum import Enum
from typing import Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    EXTRACTED = "extracted"
    UNRESOLVED = "unresolved"
    PENDING = "pending"
    REJECTED = "rejected"


class FindingType(str, Enum):
    POLICY_FACT = "policy_fact"
    CLAIM_FACT = "claim_fact"
    CONTRADICTION = "contradiction"
    COVERAGE = "coverage"
    LOSS = "loss"
    GAP = "gap"


class Finding(BaseModel):
    """Single entry in the Evidence Ledger."""
    finding_id: str = Field(default_factory=lambda: f"F-{uuid4().hex[:8].upper()}")
    claim_id: str
    finding_type: FindingType
    claim_or_policy_fact: str
    normalized_value: Optional[str] = None
    source_document_id: Optional[str] = None
    page_number: Optional[int] = None
    quoted_source_text: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    verification_status: VerificationStatus = VerificationStatus.PENDING
    contradicts: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    next_action: Optional[str] = None
    responsible_reviewer: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    origin: Literal["extraction", "specialist", "seed"] = "extraction"
    specialist: Optional[str] = None
    run_id: Optional[str] = None


class ClaimStatus(str, Enum):
    RECEIVED = "received"
    PROCESSING = "processing"
    INVESTIGATING = "investigating"
    PENDING_REVIEW = "pending_review"
    COMPLETED = "completed"
    ESCALATED = "escalated"


class Claim(BaseModel):
    claim_id: str = Field(default_factory=lambda: f"CLM-{uuid4().hex[:8].upper()}")
    policy_number: Optional[str] = None
    incident_date_claimed: Optional[str] = None
    status: ClaimStatus = ClaimStatus.RECEIVED
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class InvestigationReport(BaseModel):
    claim_id: str
    findings: list[Finding]
    coverage_analysis: str
    evidence_gaps: list[str]
    financial_estimate: Optional[str] = None
    recommended_next_steps: list[str]
    human_review_required: bool = True
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class DocumentSummary(BaseModel):
    document_id: str
    claim_id: str
    filename: str
    document_type: str
    policy_version: Optional[str] = None
    effective_date: Optional[str] = None
    jurisdiction: Optional[str] = None
    page_count: int
    ocr_pages: int = 0


class SearchHit(BaseModel):
    chunk_id: str
    document_id: str
    filename: str
    document_type: str
    page_number: int
    section_kind: str
    section_title: str
    text: str
    surrounding_clause: str
    score: float
    policy_version: Optional[str] = None
    effective_date: Optional[str] = None
    matched_by: list[str] = Field(default_factory=list)


class SearchResponse(BaseModel):
    query: str
    hits: list[SearchHit]
    evidence_sufficient: bool
    note: Optional[str] = None


class InvestigationStepView(BaseModel):
    step_id: str
    specialist: str
    status: str
    skip_reason: Optional[str] = None


class InvestigationRunView(BaseModel):
    run_id: str
    claim_id: str
    status: str
    plan_id: str
    supervisor_model: str
    specialist_model: str
    steps: list[InvestigationStepView]
    findings_added: int
    error: Optional[str] = None
    stale_reason: Optional[str] = None
    started_at: datetime
    finished_at: Optional[datetime] = None
