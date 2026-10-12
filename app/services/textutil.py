"""Shared text helpers for chunking, citation checks, and retrieval."""
import re

HEADING_RE = re.compile(
    r"^(PHOTOGRAPH NOTES|CLAIM DETAILS|PRIOR CLAIMS|COVERAGE|EXCLUSION|ENDORSEMENT|"
    r"DEFINITION|SCHEDULE|ESTIMATE|INVOICE|STATEMENT|GUIDELINE)\b.*$"
)

SECTION_KINDS = {
    "COVERAGE": "coverage",
    "EXCLUSION": "exclusion",
    "ENDORSEMENT": "endorsement",
    "DEFINITION": "definition",
    "SCHEDULE": "schedule",
    "CLAIM DETAILS": "claim_details",
    "ESTIMATE": "estimate",
    "INVOICE": "invoice",
    "STATEMENT": "statement",
    "PRIOR CLAIMS": "prior_claims",
    "GUIDELINE": "guideline",
    "PHOTOGRAPH NOTES": "photograph_notes",
}

COVERAGE_QUERY_RE = re.compile(r"\b(cover|coverage|covered|exclusion|endorsement)\b", re.IGNORECASE)


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip().lower()


def quote_supported(page_text: str, quote: str | None) -> bool:
    if not quote:
        return True
    return normalize(quote) in normalize(page_text)


def looks_like_coverage_question(query: str) -> bool:
    return COVERAGE_QUERY_RE.search(query or "") is not None
