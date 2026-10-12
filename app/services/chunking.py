"""Split extracted pages on policy headings and keep the surrounding clause."""
from dataclasses import dataclass
from uuid import uuid4

from app.services.textutil import HEADING_RE, SECTION_KINDS


@dataclass
class ChunkDraft:
    chunk_id: str
    section_id: str
    page_number: int
    section_kind: str
    section_title: str
    text: str
    section_text: str


def _sections(page_text: str) -> list[tuple[str, str, str]]:
    kind = "body"
    title = "Body"
    buffer: list[str] = []
    sections: list[tuple[str, str, str]] = []

    def flush() -> None:
        body = "\n".join(buffer).strip()
        if body:
            sections.append((kind, title, body))

    for line in page_text.splitlines():
        match = HEADING_RE.match(line.strip())
        if match:
            flush()
            buffer = [line.strip()]
            kind = SECTION_KINDS[match.group(1)]
            title = line.strip()
        else:
            buffer.append(line)
    flush()
    return sections


def _windows(text: str, size: int = 900, overlap: int = 150) -> list[str]:
    if len(text) <= size:
        return [text]
    pieces: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        pieces.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap
    return pieces


def chunk_page(page_number: int, page_text: str) -> list[ChunkDraft]:
    drafts: list[ChunkDraft] = []
    for kind, title, body in _sections(page_text):
        section_id = uuid4().hex
        for piece in _windows(body):
            drafts.append(
                ChunkDraft(
                    chunk_id=uuid4().hex,
                    section_id=section_id,
                    page_number=page_number,
                    section_kind=kind,
                    section_title=title,
                    text=piece,
                    section_text=body,
                )
            )
    return drafts
