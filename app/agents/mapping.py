"""Turn specialist payloads into ledger rows. Dates and money are checked again here."""
import logging
import re
from decimal import Decimal

from app.agents.metrics import record_citation_rejected, record_decision_drop
from app.agents.schemas import (
    ContradictionAnalysis,
    ContradictionCandidate,
    ContradictionKind,
    EvidenceAnalysis,
    EvidenceFact,
    EvidenceKind,
    LossAnalysis,
    LossLine,
    PolicyAnalysis,
    PolicyClause,
    ProposedStatus,
)
from app.core.models import Finding, FindingType, VerificationStatus
from app.services.dates import compare_dates, iso_date, parse_display_date
from app.services.extraction import REVIEWER, format_gbp, parse_gbp
from app.services.textutil import normalize, quote_supported

logger = logging.getLogger("app.agents")

_DATE_TOKEN = re.compile(r"\d{1,2} [A-Za-z]+ \d{4}")
_DECISION_PHRASES = (
    "coverage is granted",
    "coverage granted",
    "grant coverage",
    "are covered",
    "is covered",
    "within cover",
    "coverage applies",
    "claim is declined",
    "decline the claim",
    "deny the claim",
    "not covered",
    "coverage denied",
    "fraudulent",
    "fraud confirmed",
    "determine fraud",
    "this is fraud",
    "authorise payment",
    "authorize payment",
    "payment authorised",
    "payment authorized",
    "pay the invoice",
    "amount payable",
)
PHOTO_FACT = "Photographs may not match the reported collision"
PHOTO_ACTION = "Review the photographs against the reported collision."
DATE_CHECK_GAP = "Date comparison could not be checked"
POLICE_FACT_PREFIX = "Incident date on the police"
CLAIM_FORM_FACT = "Incident date on the claim form"
INCEPTION_FACT = "Policy inception date"
PRE_EXISTING_FACT = "Pre-existing damage on the estimate"
COLLISION_FACT = "Collision repair amount"
SPLIT_FACT = "Repair amount split"
INVOICE_GAP = "Invoice total does not match the estimate lines"


def contains_decision_language(text: str) -> bool:
    """Case-insensitive phrase check. `is covered` does not match inside `is not covered`."""
    if not text:
        return False
    lowered = text.lower()
    if "not covered" in lowered:
        return True
    masked = lowered.replace("is not covered", " ").replace("are not covered", " ")
    for phrase in _DECISION_PHRASES:
        if phrase == "not covered":
            continue
        haystack = masked if phrase in {"is covered", "are covered"} else lowered
        if phrase in haystack:
            return True
    return False


def _waiver_without_glass(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    return "waives the before-inception" in lowered and "glass" not in lowered


def _on_page(page_text: str, field_text: str | None) -> bool:
    if not field_text or not field_text.strip():
        return False
    return quote_supported(page_text, field_text)


def _blocked(text: str | None, page_text: str | None, *, page_exempt: bool) -> bool:
    if not text:
        return False
    if not contains_decision_language(text) and not _waiver_without_glass(text):
        return False
    if page_exempt and page_text is not None and _on_page(page_text, text):
        return False
    return True


def _index_pages(pages: list[dict]) -> tuple[dict, dict]:
    by_doc: dict[tuple[str, int], dict] = {}
    by_name: dict[tuple[str, int], dict] = {}
    for page in pages:
        by_doc[(page.get("document_id") or "", page.get("page_number"))] = page
        by_name[(page.get("filename") or "", page.get("page_number"))] = page
    return by_doc, by_name


def _resolve_page(citation, pages: list[dict]) -> dict | None:
    by_doc, by_name = _index_pages(pages)
    document_id = citation.document_id
    filename = citation.filename
    page_number = citation.page_number
    by_id = by_doc.get((document_id, page_number)) if document_id else None
    by_file = by_name.get((filename, page_number)) if filename else None
    if document_id and filename:
        if by_id is None or by_file is None:
            return None
        if by_id.get("document_id") != by_file.get("document_id"):
            return None
        return by_id
    return by_id or by_file


def _quote_ok(page_text: str, quote: str | None) -> bool:
    if not quote or not str(quote).strip():
        return False
    return quote_supported(page_text, quote)


def _ledger_ids(ledger: list[Finding]) -> set[str]:
    return {finding.finding_id for finding in ledger}


def _clean_refs(refs: list[str], ledger: list[Finding]) -> list[str]:
    known = _ledger_ids(ledger)
    return [ref for ref in refs if ref in known]


def _dedup_key(finding_type: FindingType, fact: str, value: str | None, document_id: str | None, page_number: int | None):
    return (finding_type.value, normalize(fact), normalize(value or ""), document_id, page_number)


def _known_keys(findings: list[Finding]) -> set:
    return {
        _dedup_key(
            finding.finding_type,
            finding.claim_or_policy_fact,
            finding.normalized_value,
            finding.source_document_id,
            finding.page_number,
        )
        for finding in findings
    }


def _gap(
    claim_id: str,
    run_id: str,
    specialist: str,
    fact: str,
    *,
    status: VerificationStatus = VerificationStatus.PENDING,
    value: str | None = None,
    page: dict | None = None,
    quote: str | None = None,
) -> Finding:
    return Finding(
        claim_id=claim_id,
        finding_type=FindingType.GAP,
        claim_or_policy_fact=fact[:200],
        normalized_value=value,
        source_document_id=None if page is None else page.get("document_id"),
        page_number=None if page is None else page.get("page_number"),
        quoted_source_text=quote,
        confidence=0.4,
        verification_status=status,
        next_action=fact[:300],
        responsible_reviewer=REVIEWER if status in {VerificationStatus.PENDING, VerificationStatus.UNRESOLVED} else None,
        origin="specialist",
        specialist=specialist,
        run_id=run_id,
    )


def _accept_gap(drafts: list[Finding], seen_facts: set[str], gap: Finding) -> None:
    key = normalize(gap.claim_or_policy_fact)
    if key in seen_facts:
        return
    seen_facts.add(key)
    drafts.append(gap)


def _drop_decision(specialist: str, reason: str) -> None:
    record_decision_drop()
    logger.warning("decision_language_rewritten specialist=%s reason=%s", specialist, reason)


def _reject_citation(specialist: str) -> None:
    record_citation_rejected()
    logger.warning("citation rejected specialist=%s", specialist)


def display_date_iso_set(text: str | None) -> frozenset[str]:
    found: set[str] = set()
    for match in _DATE_TOKEN.finditer(text or ""):
        parsed = iso_date(match.group(0))
        if parsed:
            found.add(parsed)
    return frozenset(found)


def _status_from_proposed(proposed: ProposedStatus) -> VerificationStatus | None:
    if proposed == ProposedStatus.INSUFFICIENT:
        return None
    if proposed == ProposedStatus.PENDING:
        return VerificationStatus.PENDING
    if proposed == ProposedStatus.UNRESOLVED:
        return VerificationStatus.UNRESOLVED
    return VerificationStatus.EXTRACTED


def _reviewer(status: VerificationStatus) -> str | None:
    if status in {VerificationStatus.PENDING, VerificationStatus.UNRESOLVED}:
        return REVIEWER
    return None


def _texts_allowed(specialist: str, page_text: str, fact: str, normalized: str | None, next_action: str | None, gaps: list[str]) -> bool:
    if _blocked(fact, page_text, page_exempt=True) or _blocked(normalized, page_text, page_exempt=True):
        _drop_decision(specialist, "fact")
        return False
    if _blocked(next_action, page_text, page_exempt=False):
        _drop_decision(specialist, "next_action")
        return False
    for gap in gaps:
        if _blocked(gap, page_text, page_exempt=False):
            _drop_decision(specialist, "gap")
            return False
    return True


def _one(findings: list[Finding], predicate) -> Finding | None:
    matches = [finding for finding in findings if predicate(finding)]
    if len(matches) != 1:
        return None
    return matches[0]


def map_policy(claim_id: str, run_id: str, analysis: PolicyAnalysis, pages: list[dict], ledger: list[Finding]) -> list[Finding]:
    drafts: list[Finding] = []
    keys = _known_keys(ledger)
    facts_seen = {normalize(finding.claim_or_policy_fact) for finding in ledger}
    for clause in analysis.clauses:
        _map_policy_clause(claim_id, run_id, clause, pages, ledger, drafts, keys, facts_seen)
    _map_reported_gaps(claim_id, run_id, "policy", analysis.gaps, analysis.steps, drafts, facts_seen)
    return drafts


def _map_policy_clause(claim_id, run_id, clause: PolicyClause, pages, ledger, drafts, keys, facts_seen) -> None:
    if clause.proposed_status == ProposedStatus.INSUFFICIENT:
        return
    page = _resolve_page(clause.citation, pages)
    if page is None or not _quote_ok(page.get("body") or "", clause.citation.quoted_source_text):
        _reject_citation("policy")
        _accept_gap(drafts, facts_seen, _gap(claim_id, run_id, "policy", "Citation rejected for a policy clause"))
        return
    page_text = page.get("body") or ""
    if not _texts_allowed("policy", page_text, clause.fact, clause.normalized_value, clause.next_action, []):
        return
    status = _status_from_proposed(clause.proposed_status) or VerificationStatus.EXTRACTED
    if status == VerificationStatus.UNRESOLVED:
        status = VerificationStatus.EXTRACTED
    value = clause.normalized_value if clause.normalized_value else clause.fact
    finding = Finding(
        claim_id=claim_id,
        finding_type=FindingType.POLICY_FACT,
        claim_or_policy_fact=clause.fact,
        normalized_value=value,
        source_document_id=page.get("document_id"),
        page_number=page.get("page_number"),
        quoted_source_text=clause.citation.quoted_source_text,
        confidence=clause.confidence,
        verification_status=status,
        depends_on=_clean_refs(clause.ledger_refs, ledger),
        next_action=clause.next_action,
        responsible_reviewer=_reviewer(status),
        origin="specialist",
        specialist="policy",
        run_id=run_id,
    )
    key = _dedup_key(finding.finding_type, finding.claim_or_policy_fact, finding.normalized_value, finding.source_document_id, finding.page_number)
    if key in keys:
        logger.info("already_on_ledger specialist=policy fact=%s", normalize(clause.fact)[:80])
        return
    keys.add(key)
    drafts.append(finding)


def map_evidence(claim_id: str, run_id: str, analysis: EvidenceAnalysis, pages: list[dict], ledger: list[Finding]) -> list[Finding]:
    drafts: list[Finding] = []
    keys = _known_keys(ledger)
    facts_seen = {normalize(finding.claim_or_policy_fact) for finding in ledger}
    for fact in analysis.facts:
        _map_evidence_fact(claim_id, run_id, fact, pages, ledger, drafts, keys, facts_seen)
    _map_reported_gaps(claim_id, run_id, "evidence", analysis.gaps, analysis.steps, drafts, facts_seen)
    return drafts


def _map_evidence_fact(claim_id, run_id, fact: EvidenceFact, pages, ledger, drafts, keys, facts_seen) -> None:
    if fact.proposed_status == ProposedStatus.INSUFFICIENT:
        return
    page = _resolve_page(fact.citation, pages)
    quote = fact.citation.quoted_source_text
    if page is None or not _quote_ok(page.get("body") or "", quote):
        _reject_citation("evidence")
        _accept_gap(drafts, facts_seen, _gap(claim_id, run_id, "evidence", "Citation rejected for an evidence fact"))
        return
    page_text = page.get("body") or ""
    if not _texts_allowed("evidence", page_text, fact.fact, fact.normalized_value, fact.next_action, []):
        return
    if fact.kind in {EvidenceKind.INCIDENT_DATE, EvidenceKind.INCEPTION_DATE}:
        value = fact.normalized_value or ""
        if parse_display_date(value) is None or normalize(value) not in normalize(quote):
            return
        lowered = value.lower()
        if "before inception" in lowered or "after inception" in lowered:
            return
        finding_type = FindingType.POLICY_FACT if fact.kind == EvidenceKind.INCEPTION_DATE else FindingType.CLAIM_FACT
        status = VerificationStatus.EXTRACTED
        normalized = value
        stored_fact = fact.fact
    elif fact.kind == EvidenceKind.DAMAGE and "may be inconsistent with the reported collision" in quote.lower():
        finding_type = FindingType.GAP
        status = VerificationStatus.PENDING
        stored_fact = PHOTO_FACT
        normalized = quote
        fact = fact.model_copy(update={"next_action": fact.next_action or PHOTO_ACTION})
    else:
        finding_type = FindingType.CLAIM_FACT
        status = VerificationStatus.EXTRACTED
        if fact.proposed_status == ProposedStatus.PENDING:
            status = VerificationStatus.PENDING
        stored_fact = fact.fact
        normalized = fact.normalized_value if fact.normalized_value is not None else quote
    finding = Finding(
        claim_id=claim_id,
        finding_type=finding_type,
        claim_or_policy_fact=stored_fact,
        normalized_value=normalized,
        source_document_id=page.get("document_id"),
        page_number=page.get("page_number"),
        quoted_source_text=quote,
        confidence=fact.confidence,
        verification_status=status,
        depends_on=_clean_refs(fact.ledger_refs, ledger),
        next_action=PHOTO_ACTION if stored_fact == PHOTO_FACT else fact.next_action,
        responsible_reviewer=_reviewer(status),
        origin="specialist",
        specialist="evidence",
        run_id=run_id,
    )
    key = _dedup_key(finding.finding_type, finding.claim_or_policy_fact, finding.normalized_value, finding.source_document_id, finding.page_number)
    fact_key = normalize(finding.claim_or_policy_fact)
    if finding_type == FindingType.GAP and fact_key in facts_seen:
        logger.info("already_on_ledger specialist=evidence fact=%s", fact_key[:80])
        return
    if key in keys:
        logger.info("already_on_ledger specialist=evidence fact=%s", fact_key[:80])
        return
    keys.add(key)
    facts_seen.add(fact_key)
    drafts.append(finding)


def map_contradiction(
    claim_id: str,
    run_id: str,
    analysis: ContradictionAnalysis,
    pages: list[dict],
    ledger: list[Finding],
) -> list[Finding]:
    drafts: list[Finding] = []
    facts_seen = {normalize(finding.claim_or_policy_fact) for finding in ledger}
    iso_sets = {
        display_date_iso_set(finding.normalized_value)
        for finding in ledger
        if finding.finding_type == FindingType.CONTRADICTION and display_date_iso_set(finding.normalized_value)
    }
    for candidate in analysis.contradictions:
        _map_contradiction_candidate(claim_id, run_id, candidate, pages, ledger, drafts, facts_seen, iso_sets)
    _map_reported_gaps(claim_id, run_id, "contradiction", analysis.gaps, analysis.steps, drafts, facts_seen)
    return drafts


def _map_contradiction_candidate(claim_id, run_id, candidate: ContradictionCandidate, pages, ledger, drafts, facts_seen, iso_sets) -> None:
    if _blocked(candidate.summary, None, page_exempt=False) or _blocked(candidate.next_action, None, page_exempt=False):
        _drop_decision("contradiction", "summary")
        return
    if "fraud" in candidate.summary.lower():
        _drop_decision("contradiction", "fraud")
        return
    if candidate.kind in {ContradictionKind.DATE_DISAGREEMENT, ContradictionKind.DATE_ORDER}:
        _map_date_candidate(claim_id, run_id, candidate, pages, ledger, drafts, facts_seen, iso_sets)
        return
    if candidate.kind == ContradictionKind.DAMAGE_VS_PHOTOS:
        if any(normalize(finding.claim_or_policy_fact) == normalize(PHOTO_FACT) for finding in ledger):
            logger.info("already_on_ledger specialist=contradiction fact=photograph")
            return
        page = _resolve_page(candidate.citation, pages)
        if page is None or not _quote_ok(page.get("body") or "", candidate.citation.quoted_source_text):
            _reject_citation("contradiction")
            _accept_gap(drafts, facts_seen, _gap(claim_id, run_id, "contradiction", "Citation rejected for a damage comparison"))
            return
        fact_name = "Photograph notes disagree with the reported collision"
        _append_contradiction(
            claim_id,
            run_id,
            drafts,
            facts_seen,
            iso_sets,
            fact_name,
            candidate.summary,
            page,
            candidate.citation.quoted_source_text,
            candidate.next_action,
            candidate.confidence,
            [],
        )


def _map_date_candidate(claim_id, run_id, candidate, pages, ledger, drafts, facts_seen, iso_sets) -> None:
    police = _one(
        ledger,
        lambda finding: finding.finding_type == FindingType.CLAIM_FACT
        and finding.claim_or_policy_fact.startswith(POLICE_FACT_PREFIX),
    )
    if candidate.kind == ContradictionKind.DATE_ORDER:
        inception = _one(
            ledger,
            lambda finding: finding.finding_type == FindingType.POLICY_FACT and finding.claim_or_policy_fact == INCEPTION_FACT,
        )
        if police is None or inception is None:
            return
        left_value = police.normalized_value or ""
        right_value = inception.normalized_value or ""
        if parse_display_date(left_value) is None or parse_display_date(right_value) is None:
            _accept_gap(drafts, facts_seen, _gap(claim_id, run_id, "contradiction", DATE_CHECK_GAP))
            return
        order = compare_dates(left_value, right_value)
        if order != "before":
            logger.warning("date tool disagreed with the candidate specialist=contradiction order=%s", order)
            return
        normalized = f"{left_value} is before inception {right_value}"
        fact_name = "Police incident date is before policy inception"
        refs = [police.finding_id, inception.finding_id]
    else:
        claim_form = _one(
            ledger,
            lambda finding: finding.finding_type == FindingType.CLAIM_FACT and finding.claim_or_policy_fact == CLAIM_FORM_FACT,
        )
        if police is None or claim_form is None:
            return
        left_value = police.normalized_value or ""
        right_value = claim_form.normalized_value or ""
        if parse_display_date(left_value) is None or parse_display_date(right_value) is None:
            _accept_gap(drafts, facts_seen, _gap(claim_id, run_id, "contradiction", DATE_CHECK_GAP))
            return
        order = compare_dates(left_value, right_value)
        if order in {"equal", "unparsed"}:
            logger.warning("date tool disagreed with the candidate specialist=contradiction order=%s", order)
            return
        normalized = f"{left_value} (police report) and {right_value} (claim form)"
        fact_name = "Incident date conflict"
        refs = [police.finding_id, claim_form.finding_id]
    iso_key = display_date_iso_set(normalized)
    if iso_key and iso_key in iso_sets:
        logger.info("already_on_ledger specialist=contradiction fact=%s", fact_name)
        return
    page = _resolve_page(candidate.citation, pages)
    quote = candidate.citation.quoted_source_text
    if page is None or not _quote_ok(page.get("body") or "", quote):
        _reject_citation("contradiction")
        _accept_gap(drafts, facts_seen, _gap(claim_id, run_id, "contradiction", "Citation rejected for a date comparison"))
        return
    _append_contradiction(
        claim_id,
        run_id,
        drafts,
        facts_seen,
        iso_sets,
        fact_name,
        normalized,
        page,
        quote,
        candidate.next_action,
        candidate.confidence,
        refs,
    )


def _append_contradiction(claim_id, run_id, drafts, facts_seen, iso_sets, fact_name, normalized, page, quote, next_action, confidence, refs) -> None:
    if "fraud" in fact_name.lower():
        return
    iso_key = display_date_iso_set(normalized)
    if iso_key and iso_key in iso_sets:
        logger.info("already_on_ledger specialist=contradiction fact=%s", fact_name)
        return
    finding = Finding(
        claim_id=claim_id,
        finding_type=FindingType.CONTRADICTION,
        claim_or_policy_fact=fact_name,
        normalized_value=normalized,
        source_document_id=page.get("document_id"),
        page_number=page.get("page_number"),
        quoted_source_text=quote,
        confidence=confidence,
        verification_status=VerificationStatus.UNRESOLVED,
        contradicts=list(refs),
        depends_on=list(refs),
        next_action=next_action,
        responsible_reviewer=REVIEWER,
        origin="specialist",
        specialist="contradiction",
        run_id=run_id,
    )
    drafts.append(finding)
    facts_seen.add(normalize(fact_name))
    if iso_key:
        iso_sets.add(iso_key)


def _classify_line(line: str) -> str | None:
    lowered = line.strip().lower()
    if lowered.startswith("final repair invoice"):
        return "invoice"
    if "pre-existing" in lowered:
        return "pre_existing"
    if "collision" in lowered:
        return "collision"
    return None


def map_loss(claim_id: str, run_id: str, analysis: LossAnalysis, pages: list[dict], ledger: list[Finding]) -> list[Finding]:
    drafts: list[Finding] = []
    keys = _known_keys(ledger)
    facts_seen = {normalize(finding.claim_or_policy_fact) for finding in ledger}
    accepted: list[tuple[str, Decimal, dict, str]] = []
    invoice_total: Decimal | None = None
    invoice_page: dict | None = None
    invoice_quote: str | None = None
    for line in analysis.lines:
        classified = _take_loss_line(claim_id, run_id, line, pages, ledger, drafts, keys, facts_seen)
        if classified is None:
            continue
        kind, amount, page, quote = classified
        if kind == "invoice":
            invoice_total = amount
            invoice_page = page
            invoice_quote = quote
            continue
        if kind in {"pre_existing", "collision"}:
            accepted.append((kind, amount, page, quote))
            _insert_loss_fact(claim_id, run_id, kind, amount, page, quote, line, drafts, keys)
    pre_total = sum((amount for kind, amount, _, _ in accepted if kind == "pre_existing"), Decimal("0.00"))
    collision_total = sum((amount for kind, amount, _, _ in accepted if kind == "collision"), Decimal("0.00"))
    estimate_total = (pre_total + collision_total).quantize(Decimal("0.01"))
    split_exists = any(finding.claim_or_policy_fact == SPLIT_FACT for finding in ledger)
    if invoice_total is not None and accepted and invoice_total != estimate_total:
        if not any(finding.claim_or_policy_fact == INVOICE_GAP for finding in ledger):
            value = f"Invoice {format_gbp(invoice_total)} versus estimate lines {format_gbp(estimate_total)}"
            gap = _gap(
                claim_id,
                run_id,
                "loss",
                INVOICE_GAP,
                status=VerificationStatus.UNRESOLVED,
                value=value,
                page=invoice_page,
                quote=invoice_quote,
            )
            gap.verification_status = VerificationStatus.UNRESOLVED
            gap.responsible_reviewer = REVIEWER
            _accept_gap(drafts, facts_seen, gap)
    if accepted and not split_exists and (invoice_total is None or invoice_total == estimate_total):
        parts = []
        if any(kind == "collision" for kind, _, _, _ in accepted):
            parts.append(f"Collision lines {format_gbp(collision_total)}")
        if any(kind == "pre_existing" for kind, _, _, _ in accepted):
            parts.append(f"pre-existing lines {format_gbp(pre_total)}")
        if invoice_total is not None:
            parts.append(f"invoice {format_gbp(invoice_total)}")
        source = accepted[0]
        finding = Finding(
            claim_id=claim_id,
            finding_type=FindingType.LOSS,
            claim_or_policy_fact=SPLIT_FACT,
            normalized_value="; ".join(parts),
            source_document_id=source[2].get("document_id"),
            page_number=source[2].get("page_number"),
            quoted_source_text=source[3],
            confidence=0.9,
            verification_status=VerificationStatus.EXTRACTED,
            origin="specialist",
            specialist="loss",
            run_id=run_id,
        )
        key = _dedup_key(finding.finding_type, finding.claim_or_policy_fact, finding.normalized_value, finding.source_document_id, finding.page_number)
        if key not in keys:
            drafts.append(finding)
    _map_reported_gaps(claim_id, run_id, "loss", analysis.gaps, analysis.steps, drafts, facts_seen)
    return drafts


def _take_loss_line(claim_id, run_id, line: LossLine, pages, ledger, drafts, keys, facts_seen):
    page = _resolve_page(line.citation, pages)
    quote = line.citation.quoted_source_text
    if page is None or not _quote_ok(page.get("body") or "", quote):
        _reject_citation("loss")
        _accept_gap(drafts, facts_seen, _gap(claim_id, run_id, "loss", "Citation rejected for a loss line"))
        return None
    if line.amount_text not in quote:
        _reject_citation("loss")
        return None
    amount = parse_gbp(line.amount_text)
    if amount is None:
        return None
    if _blocked(line.description, page.get("body") or "", page_exempt=True):
        _drop_decision("loss", "description")
        return None
    code_kind = _classify_line(quote)
    kind = code_kind or line.kind.value
    if code_kind and code_kind != line.kind.value:
        logger.warning("money kind overridden specialist=loss model_kind=%s code_kind=%s", line.kind.value, code_kind)
    return kind, amount, page, quote


def _insert_loss_fact(claim_id, run_id, kind, amount, page, quote, line, drafts, keys) -> None:
    fact_name = PRE_EXISTING_FACT if kind == "pre_existing" else COLLISION_FACT
    value = format_gbp(amount)
    finding = Finding(
        claim_id=claim_id,
        finding_type=FindingType.LOSS,
        claim_or_policy_fact=fact_name,
        normalized_value=value,
        source_document_id=page.get("document_id"),
        page_number=page.get("page_number"),
        quoted_source_text=quote,
        confidence=line.confidence,
        verification_status=VerificationStatus.EXTRACTED,
        origin="specialist",
        specialist="loss",
        run_id=run_id,
    )
    key = _dedup_key(finding.finding_type, finding.claim_or_policy_fact, finding.normalized_value, finding.source_document_id, finding.page_number)
    if key in keys:
        logger.info("already_on_ledger specialist=loss fact=%s", fact_name)
        return
    keys.add(key)
    drafts.append(finding)


def _map_reported_gaps(claim_id, run_id, specialist, gaps, steps, drafts, facts_seen) -> None:
    texts = list(gaps)
    for step in steps:
        if step.gap:
            texts.append(step.gap)
        if step.status == "insufficient":
            texts.append(f"{step.step_id} is insufficient")
    for text in texts:
        if _blocked(text, None, page_exempt=False):
            _drop_decision(specialist, "gap")
            continue
        _accept_gap(drafts, facts_seen, _gap(claim_id, run_id, specialist, text))


def blocked_step_gaps(claim_id: str, run_id: str, plan) -> list[Finding]:
    """One gap for each required step that is blocked before the model runs."""
    drafts: list[Finding] = []
    seen: set[str] = set()
    for step in plan.steps:
        if step.required and step.status.value == "blocked":
            text = step.skip_reason or f"Missing document for {step.step_id}"
            _accept_gap(drafts, seen, _gap(claim_id, run_id, step.specialist.value, text))
    return drafts
