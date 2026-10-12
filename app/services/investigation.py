"""Claim investigation: ingest documents, retrieve evidence, and build the ledger."""
from pathlib import Path
from uuid import uuid4

import pymupdf as fitz

from app.core.config import settings
from app.core.models import (
    Claim,
    ClaimStatus,
    DocumentSummary,
    Finding,
    FindingType,
    InvestigationReport,
    SearchResponse,
    VerificationStatus,
)
from app.corpus.build import write_claim
from app.corpus.catalog import ClaimSpec, all_claims, claim_by_key
from app.services import retrieval, store
from app.services.chunking import chunk_page
from app.services.embeddings import embed_texts
from app.services.extraction import SourcePage, extract_findings
from app.services.ingestion import classify_document, infer_metadata, read_pdf
from app.services.reporting import render_report


class IngestError(ValueError):
    pass


class InvestigationService:
    def create_claim(self, policy_number: str | None = None, incident_date_claimed: str | None = None) -> Claim:
        claim = Claim(
            policy_number=policy_number,
            incident_date_claimed=incident_date_claimed,
            status=ClaimStatus.RECEIVED,
        )
        return store.upsert_claim(claim)

    def get_claim(self, claim_id: str) -> Claim | None:
        return store.get_claim(claim_id)

    def list_documents(self, claim_id: str) -> list[DocumentSummary]:
        return store.list_documents(claim_id)

    def ingest_bytes(
        self,
        claim_id: str,
        filename: str,
        data: bytes,
        document_type: str | None = None,
        policy_version: str | None = None,
        effective_date: str | None = None,
        jurisdiction: str | None = None,
    ) -> DocumentSummary:
        claim = store.get_claim(claim_id)
        if claim is None:
            raise IngestError("Claim not found")
        safe_name = Path(filename or "upload.pdf").name
        if not safe_name.lower().endswith(".pdf"):
            raise IngestError("Only PDF documents are accepted in this phase.")
        if not data:
            raise IngestError("The uploaded file is empty.")
        try:
            fitz.open(stream=data, filetype="pdf").close()
        except Exception as exc:
            raise IngestError("The file is not a readable PDF.") from exc

        destination = Path(settings.upload_dir) / claim_id / safe_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        pages = read_pdf(destination)
        combined = "\n".join(page.text for page in pages)
        resolved_type = document_type or classify_document(safe_name, pages[0].text if pages else "")
        policy_version, effective_date, jurisdiction = infer_metadata(
            combined, policy_version, effective_date, jurisdiction
        )
        document_id = uuid4().hex
        chunk_rows = []
        texts: list[str] = []
        drafts = []
        for page in pages:
            for draft in chunk_page(page.page_number, page.text):
                drafts.append(draft)
                texts.append(draft.text)
        provider, vectors = embed_texts(texts, "passage") if texts else ("local", [])
        for draft, vector in zip(drafts, vectors):
            chunk_rows.append(
                {
                    "chunk_id": draft.chunk_id,
                    "section_id": draft.section_id,
                    "claim_id": claim_id,
                    "document_id": document_id,
                    "filename": safe_name,
                    "document_type": resolved_type,
                    "page_number": draft.page_number,
                    "section_kind": draft.section_kind,
                    "section_title": draft.section_title,
                    "body": draft.text,
                    "section_body": draft.section_text,
                    "policy_version": policy_version,
                    "effective_date": effective_date,
                    "jurisdiction": jurisdiction,
                    "embedding": vector,
                    "embedding_provider": provider,
                }
            )
        store.save_ingested_document(
            {
                "document_id": document_id,
                "claim_id": claim_id,
                "filename": safe_name,
                "document_type": resolved_type,
                "policy_version": policy_version,
                "effective_date": effective_date,
                "jurisdiction": jurisdiction,
                "storage_path": str(destination),
                "page_count": len(pages),
                "ocr_pages": sum(1 for page in pages if page.ocr_used),
            },
            [
                {
                    "document_id": document_id,
                    "claim_id": claim_id,
                    "page_number": page.page_number,
                    "body": page.text,
                    "ocr_used": page.ocr_used,
                    "unreadable": page.unreadable,
                }
                for page in pages
            ],
            chunk_rows,
        )
        self._recompute(claim_id)
        store.set_claim_status(claim_id, ClaimStatus.INVESTIGATING)
        summary = next(item for item in store.list_documents(claim_id) if item.document_id == document_id)
        return summary

    def _recompute(self, claim_id: str) -> list[Finding]:
        pages = [
            SourcePage(
                document_id=row["document_id"],
                filename=row["filename"],
                document_type=row["document_type"],
                page_number=row["page_number"],
                text=row["body"],
                unreadable=row["unreadable"],
            )
            for row in store.pages_for_claim(claim_id)
        ]
        findings = extract_findings(claim_id, pages)
        store.replace_findings(claim_id, findings)
        return findings

    def load_spec(self, spec: ClaimSpec) -> Claim:
        claim = self.create_claim(spec.policy_number, spec.incident_date_claimed)
        directory = Path(settings.upload_dir) / claim.claim_id
        paths = write_claim(spec, directory)
        by_name = {document.filename: document for document in spec.documents}
        for path in paths:
            document = by_name[path.name]
            self.ingest_bytes(
                claim.claim_id,
                path.name,
                path.read_bytes(),
                document_type=document.document_type,
                policy_version=document.policy_version,
                effective_date=document.effective_date,
                jurisdiction=document.jurisdiction,
            )
        return store.get_claim(claim.claim_id)

    def load_september_pack(self) -> Claim:
        return self.load_spec(claim_by_key("september-collision"))

    def load_catalog(self) -> list[Claim]:
        return [self.load_spec(spec) for spec in all_claims()]

    def search(self, claim_id: str, query: str, **filters) -> SearchResponse:
        return retrieval.search(claim_id, query, **filters)

    def get_findings(self, claim_id: str) -> list[Finding]:
        return store.list_findings(claim_id)

    def get_report(self, claim_id: str) -> InvestigationReport | None:
        claim = store.get_claim(claim_id)
        if claim is None:
            return None
        return render_report(claim, store.list_findings(claim_id))

    def seed_example(self, claim_id: str) -> list[Finding]:
        claim = store.get_claim(claim_id)
        if claim is None:
            raise IngestError("Claim not found")
        findings = [
            Finding(
                claim_id=claim_id,
                finding_type=FindingType.POLICY_FACT,
                claim_or_policy_fact="Policy inception date",
                normalized_value="15 September",
                source_document_id="policy_schedule.pdf",
                page_number=2,
                quoted_source_text="Policy period commences 15 September 2026",
                confidence=0.95,
                verification_status=VerificationStatus.VERIFIED,
            ),
            Finding(
                claim_id=claim_id,
                finding_type=FindingType.CONTRADICTION,
                claim_or_policy_fact="Incident date conflict",
                normalized_value="12 Sep (police) vs 16 Sep (claim form)",
                source_document_id="police_report.pdf",
                page_number=1,
                quoted_source_text="Incident reported as occurring on 12 September",
                confidence=0.8,
                verification_status=VerificationStatus.UNRESOLVED,
                next_action="Investigator to confirm incident date with police and claimant",
                responsible_reviewer="claims_investigator",
            ),
            Finding(
                claim_id=claim_id,
                finding_type=FindingType.COVERAGE,
                claim_or_policy_fact="Coverage applicability",
                normalized_value="Pending date verification",
                confidence=0.3,
                verification_status=VerificationStatus.PENDING,
                depends_on=["F-incident-date"],
                next_action="Resolve incident date before coverage determination",
            ),
        ]
        store.replace_findings(claim_id, findings)
        store.set_claim_status(claim_id, ClaimStatus.INVESTIGATING)
        return findings

    def run_investigation(self, claim_id: str) -> dict | None:
        claim = store.get_claim(claim_id)
        if claim is None:
            return None
        store.set_claim_status(claim_id, ClaimStatus.PENDING_REVIEW)
        return {"status": "pending_review", "findings_count": len(store.list_findings(claim_id))}
