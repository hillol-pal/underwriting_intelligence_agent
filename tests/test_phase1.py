"""Phase 1 document intelligence, retrieval, and ledger checks."""
import shutil
import tempfile
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.models import FindingType, VerificationStatus
from app.corpus.build import write_document
from app.corpus.catalog import SEPTEMBER, all_claims, claim_by_key
from app.main import app
from app.services import store
from app.services.chunking import chunk_page
from app.services.evaluation import citation_correctness, fact_accuracy, query_passed, recall_at_k
from app.services.extraction import SourcePage, extract_findings
from app.services.ingestion import read_pdf
from app.services.investigation import InvestigationService
from app.services.store import DatabaseUnavailable, with_database
from app.services.textutil import normalize


def test_catalog_covers_the_phase1_corpus():
    claims = all_claims()
    documents = sum(len(claim.documents) for claim in claims)
    assert 5 <= len(claims) <= 10
    assert 20 <= documents <= 40
    assert len(claims) == 8
    assert documents == 32


def test_long_section_keeps_the_surrounding_clause():
    body = "COVERAGE — ACCIDENTAL COLLISION DAMAGE\n" + ("damage " * 400)
    drafts = chunk_page(3, body)
    assert len(drafts) > 1
    assert {draft.section_kind for draft in drafts} == {"coverage"}
    assert len({draft.section_text for draft in drafts}) == 1
    assert all(draft.page_number == 3 for draft in drafts)


def _pages_from_spec(spec) -> tuple[list[SourcePage], dict[str, str]]:
    pages: list[SourcePage] = []
    document_ids: dict[str, str] = {}
    for document in spec.documents:
        document_ids[document.filename] = document.filename
        for number, text in enumerate(document.pages, start=1):
            pages.append(
                SourcePage(
                    document_id=document.filename,
                    filename=document.filename,
                    document_type=document.document_type,
                    page_number=number,
                    text=text,
                    unreadable=False,
                )
            )
    return pages, document_ids


def test_september_extraction_cites_conflicts_and_splits_money():
    pages, document_ids = _pages_from_spec(SEPTEMBER)
    findings = extract_findings("CLM-TEST", pages)
    assert fact_accuracy(SEPTEMBER.facts, findings, document_ids) == 1.0
    assert citation_correctness(
        findings,
        {(page.document_id, page.page_number): page.text for page in pages},
    ) == 1.0
    assert any(finding.finding_type == FindingType.CONTRADICTION for finding in findings)
    coverage = next(finding for finding in findings if finding.finding_type == FindingType.COVERAGE)
    assert coverage.verification_status == VerificationStatus.PENDING
    assert coverage.normalized_value == "Pending date verification"
    split = next(finding for finding in findings if finding.claim_or_policy_fact == "Repair amount split")
    assert "£2180.00" in split.normalized_value
    assert "£420.00" in split.normalized_value
    assert "£2600.00" in split.normalized_value
    assert not any(finding.verification_status == VerificationStatus.REJECTED for finding in findings)


def test_invoice_mismatch_is_arithmetic_not_a_model_opinion():
    pages = [
        SourcePage("estimate", "garage_estimate.pdf", "garage_estimate", 1, "ESTIMATE\nFront wing collision repair: £100.00.", False),
        SourcePage("invoice", "repair_invoice.pdf", "invoice", 1, "INVOICE\nFinal repair invoice total: £90.00.", False),
    ]
    findings = extract_findings("CLM-MONEY", pages)
    gap = next(finding for finding in findings if finding.claim_or_policy_fact.startswith("Invoice total"))
    assert gap.verification_status == VerificationStatus.UNRESOLVED
    assert "£90.00" in (gap.normalized_value or "")
    assert Decimal("100.00") != Decimal("90.00")


def test_digital_pdf_preserves_the_coverage_sentence(tmp_path: Path):
    wording = SEPTEMBER.documents[1]
    path = write_document(wording, tmp_path / wording.filename)
    pages = read_pdf(path)
    quote = "Accidental collision damage to the insured vehicle is covered when the incident occurs during the insured period."
    assert normalize(quote) in normalize(pages[0].text)


@pytest.fixture(scope="module")
def phase1_db():
    original = (settings.database_url, settings.embedding_provider, settings.upload_dir)
    settings.database_url = with_database(settings.database_url, "underwriting_agent_test")
    settings.embedding_provider = "local"
    settings.upload_dir = tempfile.mkdtemp(prefix="uw-uploads-")
    store.reset_schema_cache()
    try:
        store.init_db()
    except DatabaseUnavailable as exc:
        pytest.skip(str(exc))
    with store.connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM claims")
    yield
    settings.database_url, settings.embedding_provider, settings.upload_dir = original
    store.reset_schema_cache()


def test_corpus_retrieval_and_citations(phase1_db):
    service = InvestigationService()
    loaded = {claim.policy_number: claim for claim in service.load_catalog()}
    hero = loaded["POL-88421"]
    rear = loaded["POL-10001"]
    hero_findings = service.get_findings(hero.claim_id)
    documents = {item.filename: item.document_id for item in service.list_documents(hero.claim_id)}
    pages = {
        (row["document_id"], row["page_number"]): row["body"]
        for row in store.pages_for_claim(hero.claim_id)
    }
    assert fact_accuracy(SEPTEMBER.facts, hero_findings, documents) == 1.0
    assert citation_correctness(hero_findings, pages) == 1.0
    for spec in SEPTEMBER.queries:
        result = service.search(hero.claim_id, spec.query, k=spec.k)
        assert query_passed(spec, result.hits), spec.name
    rear_query = "Rear-end collision on 20 March 2026 was reported with matching dates."
    rear_hits = service.search(rear.claim_id, rear_query, k=5).hits
    assert recall_at_k([rear_query], [hit.text + " " + hit.surrounding_clause for hit in rear_hits], 5) == 1.0
    police_only = service.search(hero.claim_id, "September incident", document_type="police_report", k=8)
    assert police_only.hits
    assert {hit.document_type for hit in police_only.hits} == {"police_report"}
    versioned = service.search(hero.claim_id, "accidental collision damage", policy_version="MOT-2026.1", k=5)
    assert versioned.hits
    assert all(hit.policy_version == "MOT-2026.1" for hit in versioned.hits)
    missing = service.search(hero.claim_id, "accidental collision damage", policy_version="NOT-A-VERSION", k=5)
    assert missing.hits == []
    assert missing.evidence_sufficient is False
    report = service.get_report(hero.claim_id)
    assert report is not None
    assert report.human_review_required is True
    assert "cannot be determined" in report.coverage_analysis.lower()
    rear_findings = service.get_findings(rear.claim_id)
    assert not any(finding.finding_type == FindingType.CONTRADICTION for finding in rear_findings)
    rear_coverage = next(finding for finding in rear_findings if finding.finding_type == FindingType.COVERAGE)
    assert rear_coverage.verification_status == VerificationStatus.EXTRACTED
    scan = next(item for item in service.list_documents(hero.claim_id) if item.filename == "police_supplement_scan.pdf")
    if shutil.which("tesseract"):
        assert scan.ocr_pages == 1
    else:
        assert any(finding.claim_or_policy_fact.startswith("Unreadable page") for finding in hero_findings)


def test_api_uploads_a_pdf_and_searches_it(phase1_db):
    client = TestClient(app)
    created = client.post("/api/v1/claims", json={"policy_number": "POL-API", "incident_date_claimed": "1 March 2026"})
    assert created.status_code == 200
    claim_id = created.json()["claim"]["claim_id"]
    wording = claim_by_key("september-collision").documents[1]
    path = write_document(wording, Path(settings.upload_dir) / "api-wording.pdf")
    uploaded = client.post(
        f"/api/v1/claims/{claim_id}/documents",
        files={"file": ("policy_wording.pdf", path.read_bytes(), "application/pdf")},
    )
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["document_type"] == "policy_wording"
    searched = client.post(
        f"/api/v1/claims/{claim_id}/search",
        json={"query": "Is this collision damage covered under the policy?", "k": 8},
    )
    assert searched.status_code == 200, searched.text
    kinds = {hit["section_kind"] for hit in searched.json()["hits"]}
    assert {"coverage", "exclusion", "definition"} <= kinds
    report = client.get(f"/api/v1/claims/{claim_id}/report")
    assert report.status_code == 200
    assert report.json()["human_review_required"] is True
