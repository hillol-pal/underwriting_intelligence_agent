"""Retrieval and extraction metrics for the labeled synthetic corpus.

Recall is the pass gate for retrieved documents. Precision is reported and does
not fail a query. Semantic and lexical recall are blended 70:30, matching the
weights in retrieval fusion.
"""
from dataclasses import dataclass

from app.core.config import settings
from app.core.models import Finding
from app.corpus.catalog import FactSpec, QuerySpec
from app.services.textutil import normalize, quote_supported


def citation_correctness(findings: list[Finding], pages: dict[tuple[str, int], str]) -> float:
    cited = [finding for finding in findings if finding.quoted_source_text]
    if not cited:
        return 1.0
    correct = 0
    for finding in cited:
        page_text = pages.get((finding.source_document_id or "", finding.page_number or -1), "")
        if quote_supported(page_text, finding.quoted_source_text):
            correct += 1
    return correct / len(cited)


def fact_accuracy(facts: tuple[FactSpec, ...] | list[FactSpec], findings: list[Finding], document_ids: dict[str, str]) -> float:
    if not facts:
        return 1.0
    hits = 0
    for fact in facts:
        document_id = document_ids.get(fact.filename)
        for finding in findings:
            if finding.source_document_id != document_id or finding.page_number != fact.page:
                continue
            blob = normalize(f"{finding.quoted_source_text or ''} {finding.normalized_value or ''}")
            if normalize(fact.quote) in blob and normalize(fact.value) in blob:
                hits += 1
                break
    return hits / len(facts)


def recall_at_k(expected_quotes: tuple[str, ...] | list[str], hit_texts: list[str], k: int) -> float:
    if not expected_quotes:
        return 1.0
    blob = normalize("\n".join(hit_texts[:k]))
    found = sum(1 for quote in expected_quotes if normalize(quote) in blob)
    return found / len(expected_quotes)


def query_passed(spec: QuerySpec, hits: list) -> bool:
    """Pass on full recall of the expected quotes and section kinds. Precision is not a gate."""
    texts = [f"{hit.text}\n{hit.surrounding_clause}" for hit in hits]
    if spec.expected_quotes and recall_at_k(spec.expected_quotes, texts, spec.k) < 1.0:
        return False
    if spec.expected_section_kinds:
        kinds = {hit.section_kind for hit in hits}
        if any(kind not in kinds for kind in spec.expected_section_kinds):
            return False
    if spec.absent_quotes:
        blob = normalize("\n".join(texts))
        if any(normalize(quote) in blob for quote in spec.absent_quotes):
            return False
    return True


def precision_at_k(
    expected_quotes: tuple[str, ...] | list[str],
    hit_texts: list[str],
    k: int,
    expected_section_kinds: tuple[str, ...] | list[str] = (),
    hit_kinds: list[str] | None = None,
) -> float | None:
    """Fraction of the top k hits that contain an expected quote or an expected section kind.

    Returns None when the query has no positive expectation to be precise about.
    """
    quotes = [quote for quote in expected_quotes if quote]
    kinds = [kind for kind in expected_section_kinds if kind]
    if not quotes and not kinds:
        return None
    chosen = hit_texts[:k]
    if not chosen:
        return 0.0
    relevant = 0
    for index, text in enumerate(chosen):
        blob = normalize(text)
        kind = hit_kinds[index] if hit_kinds and index < len(hit_kinds) else ""
        quote_hit = any(normalize(quote) in blob for quote in quotes)
        kind_hit = kind in kinds
        if quote_hit or kind_hit:
            relevant += 1
    return relevant / len(chosen)


def blended_recall(semantic_recall: float, lexical_recall: float) -> float:
    """70:30 semantic to lexical. Recall only. Precision is not in this number."""
    semantic = float(settings.retrieval_semantic_weight)
    lexical = float(settings.retrieval_lexical_weight)
    return (semantic * semantic_recall) + (lexical * lexical_recall)


def hit_text(hit) -> str:
    return f"{hit.text}\n{hit.surrounding_clause}"


@dataclass(frozen=True)
class RetrievalScore:
    """Recall is ``blended_recall``. Precision is recorded and is not the headline."""

    hybrid_recall: float
    hybrid_precision: float | None
    semantic_recall: float
    lexical_recall: float
    blended_recall: float
    passed: bool


def _channel_recall(spec: QuerySpec, hits: list) -> float:
    texts = [hit_text(hit) for hit in hits]
    if spec.expected_quotes:
        return recall_at_k(spec.expected_quotes, texts, spec.k)
    if spec.expected_section_kinds:
        found = {hit.section_kind for hit in hits}
        present = sum(1 for kind in spec.expected_section_kinds if kind in found)
        return present / len(spec.expected_section_kinds)
    return 1.0 if query_passed(spec, hits) else 0.0


def score_retrieval(spec: QuerySpec, hybrid_hits: list, semantic_hits: list, lexical_hits: list) -> RetrievalScore:
    hybrid_texts = [hit_text(hit) for hit in hybrid_hits]
    semantic = _channel_recall(spec, semantic_hits)
    lexical = _channel_recall(spec, lexical_hits)
    return RetrievalScore(
        hybrid_recall=_channel_recall(spec, hybrid_hits),
        hybrid_precision=precision_at_k(
            spec.expected_quotes,
            hybrid_texts,
            spec.k,
            spec.expected_section_kinds,
            [hit.section_kind for hit in hybrid_hits],
        ),
        semantic_recall=semantic,
        lexical_recall=lexical,
        blended_recall=blended_recall(semantic, lexical),
        passed=query_passed(spec, hybrid_hits),
    )
