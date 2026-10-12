"""API routes for claim investigation."""
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.core.models import Claim, DocumentSummary, Finding, InvestigationReport, SearchResponse
from app.services.investigation import IngestError, InvestigationService
from app.services.store import DatabaseUnavailable

router = APIRouter()
investigation_service = InvestigationService()


class CreateClaimRequest(BaseModel):
    policy_number: str | None = None
    incident_date_claimed: str | None = None


class CreateClaimResponse(BaseModel):
    claim: Claim
    message: str


class DemoResponse(BaseModel):
    claim: Claim
    documents: int
    findings: int
    message: str


class SearchRequest(BaseModel):
    query: str
    document_type: str | None = None
    section_kind: str | None = None
    policy_version: str | None = None
    effective_date: str | None = None
    k: int = Field(default=8, ge=1, le=30)


def _unavailable(exc: DatabaseUnavailable) -> HTTPException:
    return HTTPException(status_code=503, detail=str(exc))


@router.post("/claims", response_model=CreateClaimResponse)
async def create_claim(request: CreateClaimRequest):
    """Create a claim. Documents are read after they are uploaded."""
    try:
        claim = investigation_service.create_claim(
            policy_number=request.policy_number,
            incident_date_claimed=request.incident_date_claimed,
        )
    except DatabaseUnavailable as exc:
        raise _unavailable(exc) from exc
    return CreateClaimResponse(claim=claim, message="Claim created. Upload documents to start the investigation.")


@router.post("/demo/september-collision", response_model=DemoResponse)
async def load_september_collision():
    """Create the labeled September collision claim and ingest its document pack."""
    try:
        claim = investigation_service.load_september_pack()
        documents = investigation_service.list_documents(claim.claim_id)
        findings = investigation_service.get_findings(claim.claim_id)
    except DatabaseUnavailable as exc:
        raise _unavailable(exc) from exc
    return DemoResponse(
        claim=claim,
        documents=len(documents),
        findings=len(findings),
        message="September collision pack ingested. Coverage stays pending human review.",
    )


@router.post("/claims/{claim_id}/documents", response_model=DocumentSummary)
async def upload_document(
    claim_id: str,
    file: UploadFile = File(...),
    document_type: str | None = Form(None),
    policy_version: str | None = Form(None),
    effective_date: str | None = Form(None),
    jurisdiction: str | None = Form(None),
):
    """Store a PDF, extract pages, and refresh the evidence ledger."""
    try:
        if investigation_service.get_claim(claim_id) is None:
            raise HTTPException(status_code=404, detail="Claim not found")
        data = await file.read()
        return investigation_service.ingest_bytes(
            claim_id,
            file.filename or "upload.pdf",
            data,
            document_type=document_type or None,
            policy_version=policy_version or None,
            effective_date=effective_date or None,
            jurisdiction=jurisdiction or None,
        )
    except DatabaseUnavailable as exc:
        raise _unavailable(exc) from exc
    except IngestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/claims/{claim_id}/documents", response_model=list[DocumentSummary])
async def list_documents(claim_id: str):
    try:
        if investigation_service.get_claim(claim_id) is None:
            raise HTTPException(status_code=404, detail="Claim not found")
        return investigation_service.list_documents(claim_id)
    except DatabaseUnavailable as exc:
        raise _unavailable(exc) from exc


@router.post("/claims/{claim_id}/search", response_model=SearchResponse)
async def search_claim(claim_id: str, request: SearchRequest):
    try:
        if investigation_service.get_claim(claim_id) is None:
            raise HTTPException(status_code=404, detail="Claim not found")
        return investigation_service.search(
            claim_id,
            request.query,
            k=request.k,
            document_type=request.document_type,
            section_kind=request.section_kind,
            policy_version=request.policy_version,
            effective_date=request.effective_date,
        )
    except DatabaseUnavailable as exc:
        raise _unavailable(exc) from exc


@router.get("/claims/{claim_id}", response_model=Claim)
async def get_claim(claim_id: str):
    try:
        claim = investigation_service.get_claim(claim_id)
    except DatabaseUnavailable as exc:
        raise _unavailable(exc) from exc
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    return claim


@router.get("/claims/{claim_id}/findings", response_model=list[Finding])
async def get_findings(claim_id: str):
    """Return the Evidence Ledger for a claim."""
    try:
        if investigation_service.get_claim(claim_id) is None:
            raise HTTPException(status_code=404, detail="Claim not found")
        return investigation_service.get_findings(claim_id)
    except DatabaseUnavailable as exc:
        raise _unavailable(exc) from exc


@router.get("/claims/{claim_id}/report", response_model=InvestigationReport)
async def get_report(claim_id: str):
    """Return the current advisory investigation report."""
    try:
        report = investigation_service.get_report(claim_id)
    except DatabaseUnavailable as exc:
        raise _unavailable(exc) from exc
    if not report:
        raise HTTPException(status_code=404, detail="Claim not found")
    return report


@router.post("/claims/{claim_id}/seed-example")
async def seed_example(claim_id: str):
    """Replace the ledger with the Phase 0 sample rows. This does not read a PDF."""
    try:
        findings = investigation_service.seed_example(claim_id)
    except DatabaseUnavailable as exc:
        raise _unavailable(exc) from exc
    except IngestError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"claim_id": claim_id, "findings": len(findings), "message": "Sample ledger rows loaded."}


@router.post("/claims/{claim_id}/investigate")
async def trigger_investigation(claim_id: str):
    """Mark the claim ready for human review. This does not decide coverage."""
    try:
        result = investigation_service.run_investigation(claim_id)
    except DatabaseUnavailable as exc:
        raise _unavailable(exc) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    return {"claim_id": claim_id, "status": "investigation_triggered", "details": result}
