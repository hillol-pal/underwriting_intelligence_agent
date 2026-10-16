"""Build the advisory investigation report from ledger findings."""
from app.core.models import Claim, Finding, FindingType, InvestigationReport, VerificationStatus


def _coverage_paragraph(findings: list[Finding]) -> str:
    unresolved = [
        finding
        for finding in findings
        if finding.verification_status == VerificationStatus.UNRESOLVED or finding.finding_type == FindingType.CONTRADICTION
    ]
    coverage = next((finding for finding in findings if finding.finding_type == FindingType.COVERAGE), None)
    if not findings:
        return "Coverage cannot be assessed because no evidence has been read."
    if unresolved:
        base = "Coverage cannot be determined until the conflicting evidence is resolved."
    elif coverage and coverage.normalized_value:
        base = coverage.normalized_value
    else:
        base = "Coverage cannot be determined from the documents read so far."
    extras = [
        finding.normalized_value
        for finding in findings
        if finding.finding_type == FindingType.POLICY_FACT
        and finding.normalized_value
        and "endorsement" in finding.claim_or_policy_fact.lower()
        and (finding.origin or "extraction") == "extraction"
    ]
    return " ".join(part for part in [base, *extras] if part)


def _financial_paragraph(findings: list[Finding]) -> str:
    split = next((finding for finding in findings if finding.claim_or_policy_fact == "Repair amount split"), None)
    if split and split.normalized_value:
        return (
            f"{split.normalized_value}. Pre-existing lines stay separate from the collision estimate "
            "until a reviewer accepts them."
        )
    return "Pending loss assessment"


def render_report(claim: Claim, findings: list[Finding]) -> InvestigationReport:
    gaps: list[str] = []
    steps: list[str] = []
    for finding in findings:
        needs_person = finding.verification_status in {VerificationStatus.UNRESOLVED, VerificationStatus.PENDING}
        material = finding.finding_type in {FindingType.GAP, FindingType.CONTRADICTION}
        if (needs_person or material) and finding.claim_or_policy_fact not in gaps:
            gaps.append(finding.claim_or_policy_fact)
        if finding.next_action and finding.next_action not in steps:
            steps.append(finding.next_action)
    if not findings:
        gaps = ["No documents have been read for this claim."]
        steps = ["Upload the policy, claim form, police report, and repair documents."]
    return InvestigationReport(
        claim_id=claim.claim_id,
        findings=findings,
        coverage_analysis=_coverage_paragraph(findings),
        evidence_gaps=gaps,
        financial_estimate=_financial_paragraph(findings),
        recommended_next_steps=steps,
        human_review_required=True,
    )
