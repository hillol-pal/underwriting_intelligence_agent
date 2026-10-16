"""Window, overlap, and heading behaviour of the page chunker."""
import pytest

from app.services.chunking import ChunkingConfig, chunk_page, split_sections, window_spans


def test_short_section_is_one_chunk_with_no_overlap():
    drafts = chunk_page(1, "COVERAGE\nAccidental collision damage is covered during the insured period.")
    assert len(drafts) == 1
    assert drafts[0].section_kind == "coverage"
    assert drafts[0].text == drafts[0].section_text
    assert drafts[0].page_number == 1


def test_two_headings_stay_in_separate_sections():
    page = "COVERAGE\nCollision cover.\n\nEXCLUSION\nPre-existing damage is excluded."
    sections = split_sections(page)
    assert [section.kind for section in sections] == ["coverage", "exclusion"]
    drafts = chunk_page(2, page)
    assert len({draft.section_id for draft in drafts}) == 2
    assert "excluded" not in drafts[0].section_text


def test_overlap_is_repeated_on_the_next_window():
    config = ChunkingConfig(window_size=10, overlap=3, boundary_margin=0)
    text = "abcdefghijKLMNO"
    spans = window_spans(text, config)
    assert spans == [(0, 10), (7, 15)]
    left = text[spans[0][0] : spans[0][1]]
    right = text[spans[1][0] : spans[1][1]]
    assert left[-3:] == right[:3] == "hij"


def test_boundary_margin_does_not_cut_a_word():
    config = ChunkingConfig(window_size=12, overlap=4, boundary_margin=6)
    text = "alpha beta gamma delta epsilon"
    spans = window_spans(text, config)
    for start, end in spans[:-1]:
        assert text[end - 1].isspace()
        assert start < end
    assert spans[-1][1] == len(text)


def test_later_window_keeps_the_heading():
    config = ChunkingConfig(window_size=40, overlap=10, boundary_margin=0)
    body = "EXCLUSION — pre-existing damage\n" + ("rust " * 40)
    drafts = chunk_page(4, body, config)
    assert len(drafts) > 1
    assert len({draft.section_text for draft in drafts}) == 1
    assert all(draft.text.startswith("EXCLUSION — pre-existing damage") for draft in drafts)
    assert all(draft.section_id == drafts[0].section_id for draft in drafts)


def test_overlap_must_be_smaller_than_the_window():
    with pytest.raises(ValueError):
        ChunkingConfig(window_size=10, overlap=10)
