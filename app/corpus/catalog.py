"""Labeled synthetic claims. Quotes here are the answer key for evaluation."""
from dataclasses import dataclass


@dataclass(frozen=True)
class DocumentSpec:
    filename: str
    document_type: str
    pages: tuple[str, ...]
    policy_version: str | None = None
    effective_date: str | None = None
    jurisdiction: str | None = None
    scanned_pages: tuple[int, ...] = ()


@dataclass(frozen=True)
class FactSpec:
    fact: str
    value: str
    filename: str
    page: int
    quote: str


@dataclass(frozen=True)
class QuerySpec:
    name: str
    query: str
    expected_quotes: tuple[str, ...] = ()
    expected_section_kinds: tuple[str, ...] = ()
    k: int = 8
    absent_quotes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ClaimSpec:
    key: str
    policy_number: str
    incident_date_claimed: str
    documents: tuple[DocumentSpec, ...]
    facts: tuple[FactSpec, ...] = ()
    queries: tuple[QuerySpec, ...] = ()


def _extra(number: int, key: str, policy: str, inception: str, incident: str, sentence: str) -> ClaimSpec:
    registration = f"AB{number:02d} CDE"
    return ClaimSpec(
        key=key,
        policy_number=policy,
        incident_date_claimed=incident,
        documents=(
            DocumentSpec(
                filename="policy_schedule.pdf",
                document_type="policy_schedule",
                policy_version="MOT-2026.1",
                effective_date=None,
                jurisdiction="England and Wales",
                pages=(
                    "\n".join(
                        [
                            "SCHEDULE — PERIOD OF INSURANCE",
                            f"Policy number {policy}",
                            "Policy version MOT-2026.1",
                            f"Policy period commences {inception} and ends one year later.",
                            "Jurisdiction: England and Wales.",
                            f"Vehicle registration {registration}",
                        ]
                    ),
                ),
            ),
            DocumentSpec(
                filename="claim_form.pdf",
                document_type="claim_form",
                pages=(
                    "\n".join(
                        [
                            "CLAIM DETAILS",
                            f"Claimed incident date: {incident}.",
                            f"Policy number {policy}.",
                        ]
                    ),
                ),
            ),
            DocumentSpec(
                filename="police_report.pdf",
                document_type="police_report",
                pages=(
                    "\n".join(
                        [
                            "STATEMENT",
                            f"Incident reported as occurring on {incident}.",
                            sentence,
                        ]
                    ),
                ),
            ),
        ),
    )


SEPTEMBER = ClaimSpec(
    key="september-collision",
    policy_number="POL-88421",
    incident_date_claimed="12 September 2026",
    documents=(
        DocumentSpec(
            filename="policy_schedule.pdf",
            document_type="policy_schedule",
            policy_version="MOT-2026.1",
            effective_date="2026-09-15",
            jurisdiction="England and Wales",
            pages=(
                "\n".join(
                    [
                        "MOTOR POLICY SCHEDULE",
                        "Policy number POL-88421",
                        "Policy version MOT-2026.1",
                        "Insured: A. Rahman",
                        "Vehicle: Ford Focus registration LK21 ABC",
                    ]
                ),
                "\n".join(
                    [
                        "SCHEDULE — PERIOD OF INSURANCE",
                        "Policy period commences 15 September 2026 and ends 14 September 2027.",
                        "Jurisdiction: England and Wales.",
                    ]
                ),
            ),
        ),
        DocumentSpec(
            filename="policy_wording.pdf",
            document_type="policy_wording",
            policy_version="MOT-2026.1",
            effective_date="2026-09-15",
            pages=(
                "\n".join(
                    [
                        "COVERAGE — ACCIDENTAL COLLISION DAMAGE",
                        "Accidental collision damage to the insured vehicle is covered when the incident occurs during the insured period.",
                    ]
                ),
                "\n".join(
                    [
                        "EXCLUSION — PRE-EXISTING DAMAGE",
                        "This policy does not cover pre-existing bumper damage or other damage that was present before the reported incident.",
                    ]
                ),
                "\n".join(
                    [
                        "EXCLUSION — BEFORE INCEPTION",
                        "Loss or damage that occurs before the policy period commences is not covered.",
                    ]
                ),
                "\n".join(
                    [
                        "DEFINITION — INSURED PERIOD",
                        "The insured period is the period shown on the policy schedule, beginning on the inception date and ending on the expiry date.",
                    ]
                ),
            ),
        ),
        DocumentSpec(
            filename="endorsement_e17.pdf",
            document_type="endorsement",
            policy_version="MOT-2026.1",
            effective_date="2026-09-15",
            pages=(
                "\n".join(
                    [
                        "ENDORSEMENT E-17 — GLASS ONLY WAIVER",
                        "With effect from 15 September 2026 this endorsement waives the before-inception exclusion for glass breakage only.",
                        "Collision damage remains subject to the insured period on the schedule.",
                        "Policy version MOT-2026.1.",
                    ]
                ),
            ),
        ),
        DocumentSpec(
            filename="claim_form.pdf",
            document_type="claim_form",
            pages=(
                "\n".join(
                    [
                        "CLAIM DETAILS",
                        "Claimed incident date: 16 September 2026.",
                        "The driver states the collision happened in the evening after the policy had started.",
                        "Policy number POL-88421.",
                    ]
                ),
            ),
        ),
        DocumentSpec(
            filename="police_report.pdf",
            document_type="police_report",
            pages=(
                "\n".join(
                    [
                        "STATEMENT",
                        "Incident reported as occurring on 12 September 2026 at 18:40 hours.",
                        "Location: High Street, Luton.",
                    ]
                ),
            ),
        ),
        DocumentSpec(
            filename="photograph_notes.pdf",
            document_type="photograph",
            pages=(
                "\n".join(
                    [
                        "PHOTOGRAPH NOTES",
                        "Photograph 3 shows rust and a faded scrape on the bumper that may be inconsistent with the reported collision.",
                    ]
                ),
            ),
        ),
        DocumentSpec(
            filename="garage_estimate.pdf",
            document_type="garage_estimate",
            pages=(
                "\n".join(
                    [
                        "ESTIMATE",
                        "Pre-existing bumper scuffs noted as pre-existing bumper damage: £420.00.",
                        "Front wing collision repair: £2180.00.",
                    ]
                ),
            ),
        ),
        DocumentSpec(
            filename="repair_invoice.pdf",
            document_type="invoice",
            pages=("INVOICE\nFinal repair invoice total: £2600.00.",),
        ),
        DocumentSpec(
            filename="prior_claim_history.pdf",
            document_type="claim_history",
            pages=(
                "\n".join(
                    [
                        "PRIOR CLAIMS",
                        "Previous claim CLM-2024-19 on 2 March 2024 for a cracked windscreen. No bumper damage was recorded.",
                    ]
                ),
            ),
        ),
        DocumentSpec(
            filename="claims_guideline.pdf",
            document_type="guideline",
            pages=(
                "\n".join(
                    [
                        "GUIDELINE — DATE CONFLICTS",
                        "When the police report and the claim form disagree on the incident date, the investigator confirms the date before coverage is assessed.",
                        "Do not treat the claim as declined solely because the dates conflict.",
                    ]
                ),
            ),
        ),
        DocumentSpec(
            filename="police_supplement_scan.pdf",
            document_type="police_report",
            scanned_pages=(1,),
            pages=("STATEMENT\nIncident reported as occurring on 12 September 2026.",),
        ),
    ),
    facts=(
        FactSpec("Policy number", "POL-88421", "policy_schedule.pdf", 1, "Policy number POL-88421"),
        FactSpec(
            "Policy inception date",
            "15 September 2026",
            "policy_schedule.pdf",
            2,
            "Policy period commences 15 September 2026",
        ),
        FactSpec("Vehicle registration", "LK21 ABC", "policy_schedule.pdf", 1, "registration LK21 ABC"),
        FactSpec(
            "Incident date on the claim form",
            "16 September 2026",
            "claim_form.pdf",
            1,
            "Claimed incident date: 16 September 2026",
        ),
        FactSpec(
            "Incident date on the police report",
            "12 September 2026",
            "police_report.pdf",
            1,
            "Incident reported as occurring on 12 September 2026",
        ),
        FactSpec(
            "Pre-existing damage exclusion",
            "This policy does not cover pre-existing bumper damage",
            "policy_wording.pdf",
            2,
            "This policy does not cover pre-existing bumper damage or other damage that was present before the reported incident.",
        ),
        FactSpec(
            "Before-inception exclusion",
            "before the policy period commences is not covered",
            "policy_wording.pdf",
            3,
            "Loss or damage that occurs before the policy period commences is not covered.",
        ),
        FactSpec(
            "Insured period definition",
            "The insured period is the period shown on the policy schedule",
            "policy_wording.pdf",
            4,
            "The insured period is the period shown on the policy schedule, beginning on the inception date and ending on the expiry date.",
        ),
        FactSpec(
            "Endorsement E-17",
            "Collision damage remains subject to the insured period on the schedule.",
            "endorsement_e17.pdf",
            1,
            "Collision damage remains subject to the insured period on the schedule.",
        ),
        FactSpec(
            "Pre-existing estimate line",
            "£420.00",
            "garage_estimate.pdf",
            1,
            "pre-existing bumper damage: £420.00.",
        ),
        FactSpec(
            "Collision repair amount",
            "£2180.00",
            "garage_estimate.pdf",
            1,
            "Front wing collision repair: £2180.00.",
        ),
    ),
    queries=(
        QuerySpec(
            name="collision cover",
            query="accidental collision damage covered during the insured period",
            expected_quotes=(
                "Accidental collision damage to the insured vehicle is covered when the incident occurs during the insured period.",
            ),
            k=5,
        ),
        QuerySpec(
            name="coverage bundle",
            query="Is this collision damage covered under the policy?",
            expected_section_kinds=("coverage", "exclusion", "endorsement", "definition"),
            k=8,
        ),
        QuerySpec(
            name="pre-existing damage",
            query="pre-existing bumper damage exclusion",
            expected_quotes=("This policy does not cover pre-existing bumper damage"),
            k=5,
        ),
        QuerySpec(
            name="isolation",
            query="Rear-end collision on 20 March 2026 was reported with matching dates.",
            absent_quotes=("Rear-end collision on 20 March 2026 was reported with matching dates.",),
            k=8,
        ),
    ),
)


EXTRAS = (
    _extra(1, "rear-end", "POL-10001", "1 March 2026", "20 March 2026", "Rear-end collision on 20 March 2026 was reported with matching dates."),
    _extra(2, "theft", "POL-10002", "1 April 2026", "18 April 2026", "Theft of the insured vehicle was reported on 18 April 2026."),
    _extra(3, "glass", "POL-10003", "1 May 2026", "9 May 2026", "Glass breakage on 9 May 2026 is the only damage claimed."),
    _extra(4, "parked", "POL-10004", "1 June 2026", "11 June 2026", "The parked vehicle was found damaged on 11 June 2026."),
    _extra(5, "mileage", "POL-10005", "1 July 2026", "19 July 2026", "Odometer on the July claim reads 84210 miles."),
    _extra(6, "total-loss", "POL-10006", "1 August 2026", "22 August 2026", "The engineer valuation for the total loss is £6400.00."),
    _extra(7, "wrong-registration", "POL-10007", "1 February 2026", "14 February 2026", "The police record registration MX19 ZZZ for this February collision."),
)


def all_claims() -> tuple[ClaimSpec, ...]:
    return (SEPTEMBER, *EXTRAS)


def claim_by_key(key: str) -> ClaimSpec:
    for claim in all_claims():
        if claim.key == key:
            return claim
    raise KeyError(key)
