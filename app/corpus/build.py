"""Write the synthetic corpus to PDF files."""
from pathlib import Path

import pymupdf as fitz

from app.corpus.catalog import ClaimSpec, DocumentSpec


def _image_only_page(document: fitz.Document, text: str) -> None:
    source = fitz.open()
    try:
        draft = source.new_page(width=595, height=842)
        draft.insert_textbox(fitz.Rect(72, 72, 540, 770), text, fontsize=16, fontname="helv")
        pixmap = draft.get_pixmap(dpi=200)
    finally:
        source.close()
    page = document.new_page(width=595, height=842)
    page.insert_image(page.rect, pixmap=pixmap)


def write_document(spec: DocumentSpec, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    try:
        for number, text in enumerate(spec.pages, start=1):
            if number in spec.scanned_pages:
                _image_only_page(document, text)
                continue
            page = document.new_page(width=595, height=842)
            unused = page.insert_textbox(fitz.Rect(72, 72, 540, 770), text, fontsize=12, fontname="helv")
            if unused < 0:
                raise RuntimeError(f"Page text does not fit in {path}")
        document.save(path)
    finally:
        document.close()
    return path


def write_claim(spec: ClaimSpec, directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    return [write_document(document, directory / document.filename) for document in spec.documents]
