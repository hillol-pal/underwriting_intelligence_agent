"""Claim investigation: ingest documents, retrieve evidence, and build the ledger."""
import logging
import time
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
    InvestigationRunView,
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
from app.core.logutil import event
from app.services.tracing import observation, set_outputs

logger = logging.getLogger("app.agents")


class IngestError(ValueError):
    pass


class InvestigationService:
    def create_claim(self, policy_number: str | None = None, incident_date_claimed: str | None = None) -> Claim:
        claim = Claim(
            policy_number=policy_number,
            incident_date_claimed=incident_date_claimed,
            status=ClaimStatus.RECEIVED,
        )
        stored = store.upsert_claim(claim)
        event(logger, "claim stored", claim_id=stored.claim_id, policy_number=policy_number, incident_date_claimed=incident_date_claimed, status=stored.status.value)
        return stored

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
        store.assert_no_fresh_run(claim_id)
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
        with observation("read_pdf", {"filename": safe_name}) as read_span:
            pages = read_pdf(destination)
            set_outputs(
                read_span,
                {
                    "pages": len(pages),
                    "ocr_pages": sum(1 for page in pages if page.ocr_used),
                    "unreadable_pages": sum(1 for page in pages if page.unreadable),
                },
            )
        event(
            logger,
            "document read",
            claim_id=claim_id,
            filename=safe_name,
            pages=[{"page": page.page_number, "ocr": page.ocr_used, "unreadable": page.unreadable, "text": page.text} for page in pages],
        )
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
        with observation("recompute_ledger", {"claim_id": claim_id, "filename": safe_name}) as ledger_span:
            findings = self._recompute(claim_id)
            set_outputs(
                ledger_span,
                {
                    "findings": len(findings),
                    "rows": [
                        {
                            "type": finding.finding_type.value,
                            "fact": finding.claim_or_policy_fact,
                            "status": finding.verification_status.value,
                            "value": finding.normalized_value,
                        }
                        for finding in findings
                    ],
                },
            )
        store.set_claim_status(claim_id, ClaimStatus.INVESTIGATING)
        summary = next(item for item in store.list_documents(claim_id) if item.document_id == document_id)
        return summary

    def _recompute(self, claim_id: str, run_id: str | None = None) -> list[Finding]:
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
        store.replace_extracted_findings(claim_id, findings, owner_run_id=run_id)
        return findings

    def load_spec(self, spec: ClaimSpec) -> Claim:
        with observation(
            "load_spec",
            {
                "spec": spec.key,
                "policy_number": spec.policy_number,
                "incident_date_claimed": spec.incident_date_claimed,
                "documents": [document.filename for document in spec.documents],
            },
        ) as span:
            claim = self.create_claim(spec.policy_number, spec.incident_date_claimed)
            directory = Path(settings.upload_dir) / claim.claim_id
            paths = write_claim(spec, directory)
            by_name = {document.filename: document for document in spec.documents}
            for path in paths:
                document = by_name[path.name]
                with observation(
                    "ingest_document",
                    {
                        "claim_id": claim.claim_id,
                        "filename": path.name,
                        "document_type": document.document_type,
                    },
                ) as doc_span:
                    summary = self.ingest_bytes(
                        claim.claim_id,
                        path.name,
                        path.read_bytes(),
                        document_type=document.document_type,
                        policy_version=document.policy_version,
                        effective_date=document.effective_date,
                        jurisdiction=document.jurisdiction,
                    )
                    set_outputs(
                        doc_span,
                        {
                            "document_id": summary.document_id,
                            "page_count": summary.page_count,
                            "ocr_pages": summary.ocr_pages,
                            "document_type": summary.document_type,
                        },
                    )
            stored = store.get_claim(claim.claim_id)
            set_outputs(span, {"claim_id": stored.claim_id, "status": stored.status.value})
            return stored

    def load_september_pack(self) -> Claim:
        with observation("load_september_pack", {"spec": "september-collision"}) as span:
            claim = self.load_spec(claim_by_key("september-collision"))
            set_outputs(span, {"claim_id": claim.claim_id, "status": claim.status.value, "policy_number": claim.policy_number})
            return claim

    def load_catalog(self) -> list[Claim]:
        return [self.load_spec(spec) for spec in all_claims()]

    def search(self, claim_id: str, query: str, **filters) -> SearchResponse:
        event(logger, "search start", claim_id=claim_id, query=query, filters=filters)
        result = retrieval.search(claim_id, query, **filters)
        event(
            logger,
            "search done",
            claim_id=claim_id,
            query=query,
            evidence_sufficient=result.evidence_sufficient,
            note=result.note,
            hits=[
                {
                    "filename": hit.filename,
                    "page": hit.page_number,
                    "kind": hit.section_kind,
                    "score": hit.score,
                    "matched_by": hit.matched_by,
                    "text": hit.text,
                    "surrounding_clause": hit.surrounding_clause,
                }
                for hit in result.hits
            ],
        )
        return result

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
                origin="seed",
            ),
        ]
        store.seed_ledger(claim_id, findings)
        store.set_claim_status(claim_id, ClaimStatus.INVESTIGATING)
        return findings

    def get_investigation(self, claim_id: str) -> InvestigationRunView | None:
        if store.get_claim(claim_id) is None:
            return None
        return store.latest_investigation_run(claim_id)

    def run_investigation(self, claim_id: str) -> dict | None:
        claim = store.get_claim(claim_id)
        if claim is None:
            return None
        if not settings.investigation_agent_enabled:
            store.set_claim_status(claim_id, ClaimStatus.PENDING_REVIEW)
            logger.info("investigation agent disabled claim_id=%s", claim_id)
            return {"status": "pending_review", "findings_count": len(store.list_findings(claim_id))}
        return self._run_agent(claim)

    def _run_agent(self, claim: Claim) -> dict:
        from app.agents.models import AgentConfigError, validate_agent_config

        snapshot = claim.status
        validate_agent_config()
        if not store.pages_for_claim(claim.claim_id):
            store.set_claim_status(claim.claim_id, ClaimStatus.PENDING_REVIEW)
            return {
                "status": "pending_review",
                "findings_count": len(store.list_findings(claim.claim_id)),
                "supervisor": "skipped",
                "reason": "no documents",
            }
        run_id = f"RUN-{uuid4().hex[:8].upper()}"
        store.insert_running_run(claim.claim_id, run_id, settings.llm_model, settings.llm_specialist_model)
        try:
            return self._run_agent_locked(claim.claim_id, snapshot, run_id)
        except Exception as exc:
            self._fail_run(claim.claim_id, run_id, snapshot, exc)
            raise

    def _run_agent_locked(self, claim_id: str, snapshot: ClaimStatus, run_id: str) -> dict:
        from app.agents.metrics import record_run
        from app.agents.models import AgentConfigError
        from app.agents.plan import build_investigation_plan
        from app.agents.prompts import FALLBACK_ADVISORY
        from app.agents.supervisor import InvestigationSupervisor
        from app.services.store import DatabaseUnavailable

        findings = store.list_findings(claim_id)
        if not any(finding.origin == "extraction" for finding in findings):
            findings = self._recompute(claim_id, run_id=run_id)
        extraction_ids = {finding.finding_id for finding in findings if finding.origin == "extraction"}
        plan = build_investigation_plan(claim_id, store.list_documents(claim_id), findings)
        store.save_run_plan(run_id, plan.model_dump(mode="json"))
        deadline = time.monotonic() + 180
        try:
            result = InvestigationSupervisor().plan_and_investigate(
                claim_id,
                plan,
                run_id=run_id,
                deadline=deadline,
            )
        except (AgentConfigError, DatabaseUnavailable):
            raise
        drafts = result.pop("_findings", [])
        outputs = {
            "advisory_summary": result.pop("_advisory", FALLBACK_ADVISORY),
            "specialists": result.pop("_outputs", []),
        }
        updated_plan = result.pop("_plan", plan)
        plan_payload = updated_plan.model_dump(mode="json")
        if result.get("status") == "failed":
            store.finish_run(
                run_id,
                "failed",
                plan_payload,
                outputs,
                0,
                error=result.get("error") or "supervisor failed",
            )
            store.delete_specialist_findings_for_run(claim_id, run_id)
            store.set_claim_status(claim_id, snapshot)
            record_run("failed")
            logger.error(
                "investigation failed run_id=%s claim_id=%s model=%s error=%s",
                run_id,
                claim_id,
                settings.llm_model,
                result.get("error"),
            )
            return self._public_result(claim_id, snapshot.value, result, findings_added=0)
        current_ids = {
            finding.finding_id
            for finding in store.list_findings(claim_id)
            if finding.origin == "extraction"
        }
        if current_ids != extraction_ids:
            store.finish_run(run_id, "failed", plan_payload, outputs, 0, error="ledger_changed")
            store.delete_specialist_findings_for_run(claim_id, run_id)
            store.set_claim_status(claim_id, snapshot)
            record_run("failed")
            logger.error("ledger_changed run_id=%s claim_id=%s", run_id, claim_id)
            result["status"] = "failed"
            result["error"] = "ledger_changed"
            return self._public_result(claim_id, snapshot.value, result, findings_added=0)
        store.replace_specialist_findings(claim_id, run_id, drafts)
        run_status = result.get("status") or "completed"
        store.finish_run(run_id, run_status, plan_payload, outputs, len(drafts))
        store.set_claim_status(claim_id, ClaimStatus.PENDING_REVIEW)
        record_run(run_status)
        logger.info(
            "investigation run_id=%s claim_id=%s status=%s model=%s",
            run_id,
            claim_id,
            run_status,
            settings.llm_model,
        )
        return self._public_result(claim_id, ClaimStatus.PENDING_REVIEW.value, result, findings_added=len(drafts))

    def _fail_run(self, claim_id: str, run_id: str, snapshot: ClaimStatus, exc: Exception) -> None:
        from app.agents.metrics import record_run
        from app.agents.supervisor import _redact

        message = _redact(str(exc))
        try:
            store.finish_run(run_id, "failed", None, [], 0, error=message)
            store.delete_specialist_findings_for_run(claim_id, run_id)
            store.set_claim_status(claim_id, snapshot)
        except Exception as cleanup:
            logger.error("database failure run_id=%s claim_id=%s error=%s", run_id, claim_id, cleanup)
        record_run("failed")
        logger.error("investigation failed run_id=%s claim_id=%s model=%s error=%s", run_id, claim_id, settings.llm_model, message)

    def _public_result(self, claim_id: str, claim_status: str, result: dict, findings_added: int) -> dict:
        return {
            "status": claim_status,
            "findings_count": len(store.list_findings(claim_id)),
            "supervisor": result.get("status"),
            "run_id": result.get("run_id"),
            "plan_id": result.get("plan_id"),
            "steps": result.get("steps") or [],
            "findings_added": findings_added,
            "error": result.get("error"),
        }
