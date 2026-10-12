"""Retrieval and extraction metrics for the labeled synthetic corpus."""
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
