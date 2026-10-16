"""Code-owned investigation plan. The supervisor model follows it and does not rewrite it."""
from enum import Enum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.core.models import Finding, FindingType
from app.services.dates import parse_display_date
from app.services.store import DatabaseUnavailable, pages_for_claim


class PlanStepName(str, Enum):
    POLICY_WORDING = "policy_wording"
    EXCLUSIONS = "exclusions"
    ENDORSEMENT_E17 = "endorsement_e17"
    INSURED_PERIOD = "insured_period"
    EVIDENCE_DATES = "evidence_dates"
    EVIDENCE_PARTIES = "evidence_parties"
    EVIDENCE_DAMAGE = "evidence_damage"
    CONTRADICTION_DATES = "contradiction_dates"
    CONTRADICTION_DAMAGE = "contradiction_damage"
    LOSS_SPLIT = "loss_split"


class SpecialistName(str, Enum):
    POLICY = "policy"
    EVIDENCE = "evidence"
    CONTRADICTION = "contradiction"
    LOSS = "loss"


class PlanStepStatus(str, Enum):
    READY = "ready"
    SKIPPED = "skipped"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    INSUFFICIENT = "insufficient"


class PlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_id: str
    name: PlanStepName
    specialist: SpecialistName
    order: int
    required: bool
    condition: str
    objective: str
    search_queries: list[str]
    status: PlanStepStatus = PlanStepStatus.READY
    skip_reason: str | None = None
    depends_on_steps: list[str] = Field(default_factory=list)


class InvestigationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: str
    claim_id: str
    version: Literal[1] = 1
    created_by: Literal["code"] = "code"
    steps: list[PlanStep]


def _document_type(document: object) -> str:
    if isinstance(document, dict):
        return str(document.get("document_type") or "")
    return str(getattr(document, "document_type", "") or "")


def _has_pages(claim_id: str, documents: list) -> bool:
    for document in documents:
        if getattr(document, "page_count", 0):
            return True
        pages = getattr(document, "pages", None)
        if pages:
            return True
        if isinstance(document, dict) and (document.get("page_count") or document.get("pages")):
            return True
    try:
        return bool(pages_for_claim(claim_id))
    except DatabaseUnavailable:
        return False


def _page_contains_e17(claim_id: str) -> bool:
    try:
        pages = pages_for_claim(claim_id)
    except DatabaseUnavailable:
        return False
    return any("E-17" in (page.get("body") or "") for page in pages)


def _incident_dates(findings: list[Finding]) -> list:
    parsed = []
    for finding in findings:
        if finding.finding_type != FindingType.CLAIM_FACT:
            continue
        if not finding.claim_or_policy_fact.startswith("Incident date"):
            continue
        parsed_date = parse_display_date(finding.normalized_value or "")
        if parsed_date is not None:
            parsed.append((finding, parsed_date))
    return parsed


def _step(
    name: PlanStepName,
    specialist: SpecialistName,
    order: int,
    required: bool,
    condition: str,
    objective: str,
    queries: list[str],
    status: PlanStepStatus,
    skip_reason: str | None = None,
    depends_on: list[str] | None = None,
) -> PlanStep:
    return PlanStep(
        step_id=name.value,
        name=name,
        specialist=specialist,
        order=order,
        required=required,
        condition=condition,
        objective=objective,
        search_queries=queries,
        status=status,
        skip_reason=skip_reason,
        depends_on_steps=depends_on or [],
    )


def build_investigation_plan(claim_id: str, documents: list, findings: list[Finding]) -> InvestigationPlan:
    """Build the ten-step plan from document types and the extraction ledger.

    This function does not call a model. `created_by` is the literal "code".
    """
    types = {_document_type(document) for document in documents}
    has_pages = _has_pages(claim_id, documents)
    wording_ready = "policy_wording" in types
    has_endorsement = "endorsement" in types or _page_contains_e17(claim_id)
    has_schedule = "policy_schedule" in types
    has_definition = any(
        finding.finding_type == FindingType.POLICY_FACT and finding.claim_or_policy_fact == "Insured period definition"
        for finding in findings
    )
    has_photograph = "photograph" in types
    has_photo_gap = any(
        finding.finding_type == FindingType.GAP
        and finding.claim_or_policy_fact == "Photographs may not match the reported collision"
        for finding in findings
    )
    has_money_doc = "garage_estimate" in types or "invoice" in types

    if wording_ready:
        wording = _step(
            PlanStepName.POLICY_WORDING,
            SpecialistName.POLICY,
            10,
            True,
            "A policy_wording document exists.",
            "Cite the accidental collision wording.",
            ["accidental collision damage during the insured period"],
            PlanStepStatus.READY,
        )
    else:
        wording = _step(
            PlanStepName.POLICY_WORDING,
            SpecialistName.POLICY,
            10,
            True,
            "A policy_wording document exists.",
            "Cite the accidental collision wording.",
            ["accidental collision damage during the insured period"],
            PlanStepStatus.BLOCKED,
            "No policy wording document is on the claim.",
        )

    if wording.status == PlanStepStatus.READY:
        exclusions = _step(
            PlanStepName.EXCLUSIONS,
            SpecialistName.POLICY,
            20,
            True,
            "The policy wording step is ready.",
            "Cite the pre-existing damage exclusion and the before-inception exclusion.",
            ["pre-existing bumper damage", "loss before the policy period commences"],
            PlanStepStatus.READY,
            depends_on=[PlanStepName.POLICY_WORDING.value],
        )
    else:
        exclusions = _step(
            PlanStepName.EXCLUSIONS,
            SpecialistName.POLICY,
            20,
            True,
            "The policy wording step is ready.",
            "Cite the pre-existing damage exclusion and the before-inception exclusion.",
            ["pre-existing bumper damage", "loss before the policy period commences"],
            PlanStepStatus.BLOCKED,
            "Policy wording is blocked, so exclusions stay blocked.",
            depends_on=[PlanStepName.POLICY_WORDING.value],
        )

    endorsement_queries = [
        "endorsement E-17 glass waiver",
        "collision remains subject to the insured period",
    ]
    if wording.status != PlanStepStatus.READY:
        endorsement = _step(
            PlanStepName.ENDORSEMENT_E17,
            SpecialistName.POLICY,
            30,
            True,
            "An endorsement document exists or a page contains E-17.",
            "Cite endorsement E-17 and the sentence that keeps collision inside the insured period.",
            endorsement_queries,
            PlanStepStatus.BLOCKED,
            "Policy wording is blocked, so endorsement E-17 stays blocked.",
            depends_on=[PlanStepName.POLICY_WORDING.value],
        )
    elif has_endorsement:
        endorsement = _step(
            PlanStepName.ENDORSEMENT_E17,
            SpecialistName.POLICY,
            30,
            True,
            "An endorsement document exists or a page contains E-17.",
            "Cite endorsement E-17 and the sentence that keeps collision inside the insured period.",
            endorsement_queries,
            PlanStepStatus.READY,
            depends_on=[PlanStepName.POLICY_WORDING.value],
        )
    else:
        endorsement = _step(
            PlanStepName.ENDORSEMENT_E17,
            SpecialistName.POLICY,
            30,
            False,
            "An endorsement document exists or a page contains E-17.",
            "Cite endorsement E-17 and the sentence that keeps collision inside the insured period.",
            endorsement_queries,
            PlanStepStatus.SKIPPED,
            "No endorsement document and no page contains E-17.",
            depends_on=[PlanStepName.POLICY_WORDING.value],
        )

    if has_schedule or has_definition:
        insured = _step(
            PlanStepName.INSURED_PERIOD,
            SpecialistName.POLICY,
            40,
            True,
            "A policy_schedule document exists, or the ledger has Insured period definition.",
            "Cite the schedule inception sentence and the insured-period definition.",
            ["policy period commences", "insured period definition"],
            PlanStepStatus.READY,
        )
    else:
        insured = _step(
            PlanStepName.INSURED_PERIOD,
            SpecialistName.POLICY,
            40,
            True,
            "A policy_schedule document exists, or the ledger has Insured period definition.",
            "Cite the schedule inception sentence and the insured-period definition.",
            ["policy period commences", "insured period definition"],
            PlanStepStatus.BLOCKED,
            "No policy schedule and no insured-period definition on the ledger.",
        )

    if has_pages:
        dates = _step(
            PlanStepName.EVIDENCE_DATES,
            SpecialistName.EVIDENCE,
            50,
            True,
            "The claim has at least one page.",
            "Cite the claimed incident date and the police incident date as printed.",
            ["claimed incident date", "incident reported as occurring"],
            PlanStepStatus.READY,
        )
        parties = _step(
            PlanStepName.EVIDENCE_PARTIES,
            SpecialistName.EVIDENCE,
            60,
            False,
            "The claim has at least one page. Parties are not required.",
            "Cite the insured name, the registration, and the location when they are printed.",
            ["insured name", "registration", "location"],
            PlanStepStatus.READY,
        )
    else:
        dates = _step(
            PlanStepName.EVIDENCE_DATES,
            SpecialistName.EVIDENCE,
            50,
            False,
            "The claim has at least one page.",
            "Cite the claimed incident date and the police incident date as printed.",
            ["claimed incident date", "incident reported as occurring"],
            PlanStepStatus.BLOCKED,
            "No pages have been read for this claim.",
        )
        parties = _step(
            PlanStepName.EVIDENCE_PARTIES,
            SpecialistName.EVIDENCE,
            60,
            False,
            "The claim has at least one page. Parties are not required.",
            "Cite the insured name, the registration, and the location when they are printed.",
            ["insured name", "registration", "location"],
            PlanStepStatus.BLOCKED,
            "No pages have been read for this claim.",
        )

    if has_photograph:
        damage = _step(
            PlanStepName.EVIDENCE_DAMAGE,
            SpecialistName.EVIDENCE,
            70,
            True,
            "A photograph document exists.",
            "Cite the photograph notes, including rust and the bumper scrape.",
            ["photograph notes", "rust", "bumper"],
            PlanStepStatus.READY,
        )
    else:
        damage = _step(
            PlanStepName.EVIDENCE_DAMAGE,
            SpecialistName.EVIDENCE,
            70,
            False,
            "A photograph document exists.",
            "Cite the photograph notes, including rust and the bumper scrape.",
            ["photograph notes", "rust", "bumper"],
            PlanStepStatus.SKIPPED,
            "No photograph document is on the claim.",
        )

    incident = _incident_dates(findings)
    distinct_dates = {item[1] for item in incident}
    police_dated = any(item[0].claim_or_policy_fact.startswith("Incident date on the police") for item in incident)
    inception_dated = any(
        finding.finding_type == FindingType.POLICY_FACT
        and finding.claim_or_policy_fact == "Policy inception date"
        and parse_display_date(finding.normalized_value or "") is not None
        for finding in findings
    )
    dates_required = len(distinct_dates) >= 2 or (police_dated and inception_dated)
    contradiction_dates = _step(
        PlanStepName.CONTRADICTION_DATES,
        SpecialistName.CONTRADICTION,
        80,
        dates_required,
        "Two incident dates differ, or a police date and an inception date are both on the ledger.",
        "Compare Incident date on the police report with Incident date on the claim form, and with Policy inception date.",
        [],
        PlanStepStatus.READY,
    )

    if has_photograph or has_photo_gap:
        contradiction_damage = _step(
            PlanStepName.CONTRADICTION_DAMAGE,
            SpecialistName.CONTRADICTION,
            90,
            True,
            "A photograph document or the photograph gap is on the ledger.",
            "Compare the photograph notes with the reported collision.",
            ["photograph notes versus the reported collision"],
            PlanStepStatus.READY,
        )
    else:
        contradiction_damage = _step(
            PlanStepName.CONTRADICTION_DAMAGE,
            SpecialistName.CONTRADICTION,
            90,
            False,
            "A photograph document or the photograph gap is on the ledger.",
            "Compare the photograph notes with the reported collision.",
            ["photograph notes versus the reported collision"],
            PlanStepStatus.SKIPPED,
            "No photograph document and no photograph gap on the ledger.",
        )

    if has_money_doc:
        loss = _step(
            PlanStepName.LOSS_SPLIT,
            SpecialistName.LOSS,
            100,
            True,
            "A garage estimate or an invoice exists.",
            "Cite the pre-existing bumper line, the collision repair line, and the invoice total.",
            ["pre-existing bumper", "collision repair", "invoice total"],
            PlanStepStatus.READY,
        )
    else:
        loss = _step(
            PlanStepName.LOSS_SPLIT,
            SpecialistName.LOSS,
            100,
            False,
            "A garage estimate or an invoice exists.",
            "Cite the pre-existing bumper line, the collision repair line, and the invoice total.",
            ["pre-existing bumper", "collision repair", "invoice total"],
            PlanStepStatus.SKIPPED,
            "No garage estimate or invoice is on the claim.",
        )

    return InvestigationPlan(
        plan_id=f"PLN-{uuid4().hex[:8].upper()}",
        claim_id=claim_id,
        steps=[
            wording,
            exclusions,
            endorsement,
            insured,
            dates,
            parties,
            damage,
            contradiction_dates,
            contradiction_damage,
            loss,
        ],
    )


def ready_steps(plan: InvestigationPlan, specialist: SpecialistName) -> list[PlanStep]:
    return [step for step in plan.steps if step.specialist == specialist and step.status == PlanStepStatus.READY]


def specialists_to_call(plan: InvestigationPlan) -> list[SpecialistName]:
    """Call a specialist only when at least one of its steps is ready."""
    return [name for name in SpecialistName if ready_steps(plan, name)]
