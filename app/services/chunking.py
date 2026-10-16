"""Split one extracted page into chunks that retrieval can cite.

The strategy has two steps.

1. Split the page on a known heading (COVERAGE, EXCLUSION, ENDORSEMENT, and
   the other labels in ``textutil.SECTION_KINDS``). Text before the first
   heading is one ``body`` section. A window never crosses a heading or a page.
2. If a section is longer than ``window_size`` characters, slide a window
   across it. The next window starts ``overlap`` characters before the previous
   one ended, so a sentence on the cut is in both chunks.

Every window of a section shares one ``section_id``. ``text`` is the window
that gets embedded. ``section_text`` is the whole section and is what search
returns as the surrounding clause.

Pages in the labeled motor pack are a few hundred characters, so each section
is one chunk. The window matters for a long wording clause. Change the sizes
with ``CHUNK_WINDOW_SIZE``, ``CHUNK_OVERLAP``, and ``CHUNK_BOUNDARY_MARGIN``,
or pass a ``ChunkingConfig`` into ``chunk_page``.
"""
import logging
from dataclasses import dataclass
from uuid import uuid4

from app.core.config import settings
from app.core.logutil import event

logger = logging.getLogger("app.chunking")
from app.services.textutil import HEADING_RE, SECTION_KINDS


@dataclass(frozen=True)
class ChunkDraft:
    chunk_id: str
    section_id: str
    page_number: int
    section_kind: str
    section_title: str
    text: str
    section_text: str


@dataclass(frozen=True)
class Section:
    """One heading block on a page, before it is windowed."""

    kind: str
    title: str
    text: str
    headed: bool


@dataclass(frozen=True)
class ChunkingConfig:
    """Character window applied inside a single section.

    ``overlap`` is how many characters the next window repeats.
    ``boundary_margin`` is how far back from the hard cut the splitter looks
    for a space or newline. Zero keeps an exact character cut.
    """

    window_size: int = 900
    overlap: int = 150
    boundary_margin: int = 40

    def __post_init__(self) -> None:
        if self.window_size < 1:
            raise ValueError("chunk window_size must be at least 1")
        if self.overlap < 0:
            raise ValueError("chunk overlap must be zero or positive")
        if self.overlap >= self.window_size:
            raise ValueError("chunk overlap must be smaller than window_size so the window moves forward")
        if self.boundary_margin < 0:
            raise ValueError("chunk boundary_margin must be zero or positive")


def config_from_settings() -> ChunkingConfig:
    return ChunkingConfig(
        window_size=int(settings.chunk_window_size),
        overlap=int(settings.chunk_overlap),
        boundary_margin=int(settings.chunk_boundary_margin),
    )


def split_sections(page_text: str) -> list[Section]:
    """Group page lines by heading. Lines above the first heading are ``body``."""
    kind = "body"
    title = "Body"
    headed = False
    lines: list[str] = []
    sections: list[Section] = []

    def flush() -> None:
        body = "\n".join(lines).strip()
        if body:
            sections.append(Section(kind=kind, title=title, text=body, headed=headed))

    for line in (page_text or "").splitlines():
        match = HEADING_RE.match(line.strip())
        if match is None:
            lines.append(line)
            continue
        flush()
        lines = [line.strip()]
        kind = SECTION_KINDS[match.group(1)]
        title = line.strip()
        headed = True
    flush()
    return sections


def window_spans(text: str, config: ChunkingConfig) -> list[tuple[int, int]]:
    """Return ``[start, end)`` spans. Neighbouring spans share ``config.overlap`` characters."""
    length = len(text)
    if length == 0:
        return []
    if length <= config.window_size:
        return [(0, length)]

    spans: list[tuple[int, int]] = []
    start = 0
    while start < length:
        hard_end = min(length, start + config.window_size)
        end = _end_on_boundary(text, start, hard_end, config)
        if end <= start:
            end = hard_end
        spans.append((start, end))
        if end >= length:
            break
        next_start = end - config.overlap
        if next_start <= start:
            next_start = start + 1
        start = next_start
    return spans


def _end_on_boundary(text: str, start: int, hard_end: int, config: ChunkingConfig) -> int:
    """Prefer a space or newline near ``hard_end`` so the cut is not mid-word."""
    if hard_end >= len(text) or config.boundary_margin <= 0:
        return hard_end
    earliest = max(start + 1, hard_end - config.boundary_margin)
    if earliest >= hard_end:
        return hard_end
    cut = max(text.rfind(" ", earliest, hard_end), text.rfind("\n", earliest, hard_end))
    if cut < earliest:
        return hard_end
    return cut + 1


def window_text(section: Section, start: int, end: int) -> str:
    """Slice the section. Later windows keep the heading line when the body continues below it."""
    piece = section.text[start:end]
    if start == 0 or not section.headed:
        return piece
    heading, separator, rest = section.text.partition("\n")
    if not separator or not rest.strip() or piece.startswith(heading):
        return piece
    return f"{heading}\n{piece}"


def chunk_page(page_number: int, page_text: str, config: ChunkingConfig | None = None) -> list[ChunkDraft]:
    """Turn one page into embeddable chunks. ``config`` defaults to the settings values."""
    chosen = config if config is not None else config_from_settings()
    drafts: list[ChunkDraft] = []
    for section in split_sections(page_text):
        section_id = uuid4().hex
        for start, end in window_spans(section.text, chosen):
            drafts.append(
                ChunkDraft(
                    chunk_id=uuid4().hex,
                    section_id=section_id,
                    page_number=page_number,
                    section_kind=section.kind,
                    section_title=section.title,
                    text=window_text(section, start, end),
                    section_text=section.text,
                )
            )
    event(
        logger,
        "page chunked",
        page_number=page_number,
        chunks=[
            {"kind": draft.section_kind, "title": draft.section_title, "text": draft.text, "section_text": draft.section_text}
            for draft in drafts
        ],
    )
    return drafts
