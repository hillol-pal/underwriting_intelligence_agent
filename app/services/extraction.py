"""Turn page text into Evidence Ledger findings.

Dates, money, and coverage status come from ordinary code. A conflict stays unresolved.
Nothing in this module rejects a claim.
"""
import logging
import re
from dataclasses import dataclass
from decimal import Decimal

from app.core.logutil import event
from app.core.models import Finding, FindingType, VerificationStatus

logger = logging.getLogger("app.extraction")
from app.services.dates import (
    CLAIMED_INCIDENT_RE,
    INCEPTION_RE,
    POLICE_INCIDENT_RE,
    POLICY_NUMBER_RE,
    REGISTRATION_RE,
    parse_display_date,
)
from app.services.textutil import quote_supported

REVIEWER = "claims_investigator"


@dataclass
class SourcePage:
    document_id: str
    filename: str
    document_type: str
    page_number: int
    text: str
    unreadable: bool


@dataclass
class _Hit:
    value: str
    quote: str
    page: SourcePage


def quote_for_phrase(page_text: str, phrase: str) -> str | None:
    """Return the page substring for a phrase, allowing line wraps inside the PDF."""
    words = [word for word in phrase.split() if word]
    if not words:
        return None
    pattern = r"\s+".join(re.escape(word) for word in words)
    match = re.search(pattern, page_text, flags=re.IGNORECASE)
    return match.group(0) if match else None


def _money(line: str) -> Decimal | None:
    match = re.search(r"£(\d[\d,]*\.\d{2}|\d[\d,]*)", line)
    if not match:
        return None
    return Decimal(match.group(1).replace(",", "")).quantize(Decimal("0.01"))


def parse_gbp(text: str) -> Decimal | None:
    """Public name for the estimate-line parser. `_money` stays the alias."""
    return _money(text)


def _gbp(amount: Decimal) -> str:
    return f"£{amount:.2f}"


def format_gbp(amount: Decimal) -> str:
    """Public name for the ledger spelling. `_gbp` stays the alias."""
    return _gbp(amount)


def _fact(
    claim_id: str,
    finding_type: FindingType,
    fact: str,
    page: SourcePage,
    quote: str,
    value: str | None = None,
    status: VerificationStatus = VerificationStatus.EXTRACTED,
    confidence: float = 0.9,
    next_action: str | None = None,
    contradicts: list[str] | None = None,
    depends_on: list[str] | None = None,
) -> Finding | None:
    if not quote_supported(page.text, quote):
        return None
    return Finding(
        claim_id=claim_id,
        finding_type=finding_type,
        claim_or_policy_fact=fact,
        normalized_value=value if value is not None else quote,
        source_document_id=page.document_id,
        page_number=page.page_number,
        quoted_source_text=quote,
        confidence=confidence,
        verification_status=status,
        contradicts=contradicts or [],
        depends_on=depends_on or [],
        next_action=next_action,
        responsible_reviewer=REVIEWER if status != VerificationStatus.EXTRACTED else None,
    )


def _prefer(hits: list[_Hit]) -> list[_Hit]:
    chosen: dict[str, _Hit] = {}
    ordered = sorted(hits, key=lambda hit: ("scan" in hit.page.filename.lower(), hit.page.page_number))
    for hit in ordered:
        chosen.setdefault(hit.value, hit)
    return list(chosen.values())


def extract_findings(claim_id: str, pages: list[SourcePage]) -> list[Finding]:
    findings: list[Finding] = []
    inception_hits: list[_Hit] = []
    claimed_hits: list[_Hit] = []
    police_hits: list[_Hit] = []
    pre_lines: list[tuple[SourcePage, str, Decimal]] = []
    collision_lines: list[tuple[SourcePage, str, Decimal]] = []
    invoice_lines: list[tuple[SourcePage, str, Decimal]] = []

    for page in pages:
        if page.unreadable or not page.text.strip():
            findings.append(
                Finding(
                    claim_id=claim_id,
                    finding_type=FindingType.GAP,
                    claim_or_policy_fact=f"Unreadable page {page.page_number} of {page.filename}",
                    normalized_value="No text layer and OCR produced no text",
                    source_document_id=page.document_id,
                    page_number=page.page_number,
                    confidence=0.99,
                    verification_status=VerificationStatus.PENDING,
                    next_action="Install Tesseract or supply a text PDF for this page.",
                    responsible_reviewer=REVIEWER,
                )
            )
            continue

        for match in INCEPTION_RE.finditer(page.text):
            inception_hits.append(_Hit(match.group(1), match.group(0), page))
        for match in CLAIMED_INCIDENT_RE.finditer(page.text):
            claimed_hits.append(_Hit(match.group(1), match.group(0), page))
        for match in POLICE_INCIDENT_RE.finditer(page.text):
            police_hits.append(_Hit(match.group(1), match.group(0), page))
        for match in POLICY_NUMBER_RE.finditer(page.text):
            finding = _fact(
                claim_id,
                FindingType.POLICY_FACT,
                "Policy number",
                page,
                match.group(0),
                match.group(1),
            )
            if finding:
                findings.append(finding)
        for match in REGISTRATION_RE.finditer(page.text):
            line = quote_for_phrase(page.text, match.group(0)) or match.group(0)
            finding = _fact(
                claim_id,
                FindingType.POLICY_FACT,
                "Vehicle registration",
                page,
                line,
                match.group(1),
            )
            if finding:
                findings.append(finding)

        exclusion = quote_for_phrase(page.text, "this policy does not cover pre-existing bumper damage or other damage that was present before the reported incident.")
        if exclusion:
            finding = _fact(claim_id, FindingType.POLICY_FACT, "Pre-existing damage exclusion", page, exclusion)
            if finding:
                findings.append(finding)
        before = quote_for_phrase(page.text, "Loss or damage that occurs before the policy period commences is not covered.")
        if before:
            finding = _fact(claim_id, FindingType.POLICY_FACT, "Before-inception exclusion", page, before)
            if finding:
                findings.append(finding)
        definition = quote_for_phrase(
            page.text,
            "The insured period is the period shown on the policy schedule, beginning on the inception date and ending on the expiry date.",
        )
        if definition:
            finding = _fact(claim_id, FindingType.POLICY_FACT, "Insured period definition", page, definition)
            if finding:
                findings.append(finding)
        endorsement = quote_for_phrase(page.text, "Collision damage remains subject to the insured period on the schedule.")
        if endorsement:
            finding = _fact(
                claim_id,
                FindingType.POLICY_FACT,
                "Endorsement E-17 keeps collision subject to the insured period",
                page,
                endorsement,
            )
            if finding:
                findings.append(finding)
        photo = quote_for_phrase(
            page.text,
            "Photograph 3 shows rust and a faded scrape on the bumper that may be inconsistent with the reported collision.",
        )
        if photo:
            finding = _fact(
                claim_id,
                FindingType.GAP,
                "Photographs may not match the reported collision",
                page,
                photo,
                status=VerificationStatus.PENDING,
                confidence=0.55,
                next_action="Review the photographs against the reported collision.",
            )
            if finding:
                findings.append(finding)

        for line in page.text.splitlines():
            stripped = line.strip()
            lower = stripped.lower()
            amount = _money(stripped)
            if amount is None:
                continue
            if lower.startswith("final repair invoice"):
                invoice_lines.append((page, stripped, amount))
            elif "pre-existing" in lower:
                pre_lines.append((page, stripped, amount))
            elif "collision" in lower:
                collision_lines.append((page, stripped, amount))

    schedule_hits = [hit for hit in inception_hits if hit.page.document_type == "policy_schedule"] or inception_hits
    inception = _prefer(schedule_hits)[:1]
    claimed = _prefer([hit for hit in claimed_hits if hit.page.document_type == "claim_form"] or claimed_hits)
    police = _prefer([hit for hit in police_hits if hit.page.document_type == "police_report"] or police_hits)

    date_findings: list[Finding] = []
    for hit in inception:
        finding = _fact(claim_id, FindingType.POLICY_FACT, "Policy inception date", hit.page, hit.quote, hit.value)
        if finding:
            date_findings.append(finding)
    for hit in claimed:
        finding = _fact(claim_id, FindingType.CLAIM_FACT, "Incident date on the claim form", hit.page, hit.quote, hit.value)
        if finding:
            date_findings.append(finding)
    for hit in police:
        finding = _fact(claim_id, FindingType.CLAIM_FACT, "Incident date on the police report", hit.page, hit.quote, hit.value)
        if finding:
            date_findings.append(finding)
    findings.extend(date_findings)

    inception_hit = inception[0] if inception else None
    claimed_hit = claimed[0] if claimed else None
    police_hit = police[0] if police else None
    inception_date = parse_display_date(inception_hit.value) if inception_hit else None
    claimed_date = parse_display_date(claimed_hit.value) if claimed_hit else None
    police_date = parse_display_date(police_hit.value) if police_hit else None

    conflict_ids: list[str] = []
    if claimed_hit and police_hit and claimed_hit.value != police_hit.value:
        claimed_finding = next(item for item in date_findings if item.claim_or_policy_fact.startswith("Incident date on the claim"))
        police_finding = next(item for item in date_findings if item.claim_or_policy_fact.startswith("Incident date on the police"))
        conflict = _fact(
            claim_id,
            FindingType.CONTRADICTION,
            "Incident date conflict",
            police_hit.page,
            police_hit.quote,
            f"{police_hit.value} (police report) and {claimed_hit.value} (claim form)",
            status=VerificationStatus.UNRESOLVED,
            confidence=0.8,
            next_action="Investigator to confirm the incident date with the police and the policyholder.",
            contradicts=[claimed_finding.finding_id],
        )
        if conflict:
            findings.append(conflict)
            conflict_ids.extend([police_finding.finding_id, claimed_finding.finding_id, conflict.finding_id])

    before_inception = bool(inception_date and police_date and police_date < inception_date)
    if before_inception and inception_hit and police_hit:
        order = _fact(
            claim_id,
            FindingType.CONTRADICTION,
            "Police incident date is before policy inception",
            inception_hit.page,
            inception_hit.quote,
            f"{police_hit.value} is before inception {inception_hit.value}",
            status=VerificationStatus.UNRESOLVED,
            confidence=0.85,
            next_action="Confirm whether the incident was before inception. Coverage stays pending.",
        )
        if order:
            findings.append(order)
            conflict_ids.append(order.finding_id)

    dates_agree = bool(claimed_date and police_date and claimed_date == police_date)
    inside_period = bool(dates_agree and inception_date and police_date and police_date >= inception_date)
    if inception_hit or claimed_hit or police_hit:
        if inside_period and inception_hit and police_hit:
            coverage = Finding(
                claim_id=claim_id,
                finding_type=FindingType.COVERAGE,
                claim_or_policy_fact="Coverage applicability",
                normalized_value=(
                    f"The incident date {police_hit.value} is on or after inception {inception_hit.value}. "
                    "Exclusions and endorsements still need a reviewer."
                ),
                confidence=0.6,
                verification_status=VerificationStatus.EXTRACTED,
                depends_on=[item.finding_id for item in date_findings],
                next_action="Reviewer to apply the exclusion and any endorsement before a coverage decision.",
                responsible_reviewer=REVIEWER,
            )
        else:
            coverage = Finding(
                claim_id=claim_id,
                finding_type=FindingType.COVERAGE,
                claim_or_policy_fact="Coverage applicability",
                normalized_value="Pending date verification",
                confidence=0.3,
                verification_status=VerificationStatus.PENDING,
                depends_on=[item.finding_id for item in date_findings] + conflict_ids,
                next_action="Resolve the incident date, then apply the exclusion, endorsement, and insured-period definition.",
                responsible_reviewer=REVIEWER,
            )
        findings.append(coverage)

    for page, line, _amount in pre_lines:
        finding = _fact(
            claim_id,
            FindingType.LOSS,
            "Pre-existing damage on the estimate",
            page,
            line,
            _gbp(_amount),
            next_action="Keep pre-existing damage separate from the collision repair amount.",
            status=VerificationStatus.EXTRACTED,
        )
        if finding:
            finding.responsible_reviewer = REVIEWER
            findings.append(finding)
    for page, line, _amount in collision_lines:
        finding = _fact(claim_id, FindingType.LOSS, "Collision repair amount", page, line, _gbp(_amount))
        if finding:
            findings.append(finding)

    pre_total = sum((amount for _, _, amount in pre_lines), Decimal("0.00"))
    collision_total = sum((amount for _, _, amount in collision_lines), Decimal("0.00"))
    if pre_lines or collision_lines or invoice_lines:
        parts = []
        if collision_lines:
            parts.append(f"Collision lines {_gbp(collision_total)}")
        if pre_lines:
            parts.append(f"pre-existing lines {_gbp(pre_total)}")
        if invoice_lines:
            invoice_total = invoice_lines[0][2]
            parts.append(f"invoice {_gbp(invoice_total)}")
            if pre_lines or collision_lines:
                expected = pre_total + collision_total
                if invoice_total != expected:
                    gap = _fact(
                        claim_id,
                        FindingType.GAP,
                        "Invoice total does not match the estimate lines",
                        invoice_lines[0][0],
                        invoice_lines[0][1],
                        f"Invoice {_gbp(invoice_total)} versus estimate lines {_gbp(expected)}",
                        status=VerificationStatus.UNRESOLVED,
                        confidence=0.95,
                        next_action="Investigator to reconcile the invoice with the estimate.",
                    )
                    if gap:
                        findings.append(gap)
        if parts:
            source_page, source_line, _ = (collision_lines or pre_lines or invoice_lines)[0]
            summary = _fact(
                claim_id,
                FindingType.LOSS,
                "Repair amount split",
                source_page,
                source_line,
                "; ".join(parts),
            )
            if summary:
                findings.append(summary)

    event(
        logger,
        "findings extracted",
        claim_id=claim_id,
        count=len(findings),
        findings=[
            {
                "type": finding.finding_type.value,
                "fact": finding.claim_or_policy_fact,
                "value": finding.normalized_value,
                "page": finding.page_number,
                "quote": finding.quoted_source_text,
                "status": finding.verification_status.value,
            }
            for finding in findings
        ],
    )
    return findings
