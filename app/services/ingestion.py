"""Read PDFs with PyMuPDF and OCR image-only pages with Tesseract when it is installed."""
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pymupdf as fitz

from app.services.dates import INCEPTION_RE, POLICY_VERSION_RE, iso_date


@dataclass
class ReadPage:
    page_number: int
    text: str
    ocr_used: bool
    unreadable: bool


def classify_document(filename: str, first_page_text: str = "") -> str:
    name = filename.lower()
    rules = (
        ("history", "claim_history"),
        ("guideline", "guideline"),
        ("endorsement", "endorsement"),
        ("schedule", "policy_schedule"),
        ("wording", "policy_wording"),
        ("police", "police_report"),
        ("supplement", "police_report"),
        ("estimate", "garage_estimate"),
        ("invoice", "invoice"),
        ("photo", "photograph"),
        ("claim", "claim_form"),
    )
    for needle, document_type in rules:
        if needle in name:
            return document_type
    header = first_page_text.lower()
    if "endorsement" in header:
        return "endorsement"
    if "police" in header or header.startswith("statement"):
        return "police_report"
    if "estimate" in header:
        return "garage_estimate"
    if "invoice" in header:
        return "invoice"
    if "schedule" in header:
        return "policy_schedule"
    return "unknown"


def infer_metadata(
    text: str,
    policy_version: str | None,
    effective_date: str | None,
    jurisdiction: str | None,
) -> tuple[str | None, str | None, str | None]:
    if not policy_version:
        match = POLICY_VERSION_RE.search(text)
        policy_version = match.group(1) if match else None
    if not effective_date:
        match = INCEPTION_RE.search(text)
        effective_date = iso_date(match.group(1)) if match else None
    if not jurisdiction and "England and Wales" in text:
        jurisdiction = "England and Wales"
    return policy_version, effective_date, jurisdiction


def _ocr_pixmap(pixmap: fitz.Pixmap) -> str:
    if shutil.which("tesseract") is None:
        return ""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
        image_path = handle.name
    try:
        pixmap.save(image_path)
        completed = subprocess.run(
            ["tesseract", image_path, "stdout"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    finally:
        Path(image_path).unlink(missing_ok=True)
    return completed.stdout or ""


def read_pdf(path: Path) -> list[ReadPage]:
    document = fitz.open(path)
    pages: list[ReadPage] = []
    try:
        for index, page in enumerate(document, start=1):
            text = page.get_text("text").strip()
            if text:
                pages.append(ReadPage(index, text, False, False))
                continue
            ocr_text = _ocr_pixmap(page.get_pixmap(dpi=200)).strip()
            if ocr_text:
                pages.append(ReadPage(index, ocr_text, True, False))
            else:
                pages.append(ReadPage(index, "", False, True))
    finally:
        document.close()
    return pages
