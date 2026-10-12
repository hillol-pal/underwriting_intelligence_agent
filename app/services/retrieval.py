"""Hybrid retrieval: pgvector similarity, PostgreSQL full-text search, and a coverage bundle."""
from app.core.models import SearchHit, SearchResponse
from app.services import store
from app.services.embeddings import embed_query
from app.services.textutil import looks_like_coverage_question

BUNDLE_KINDS = ["coverage", "exclusion", "endorsement", "definition"]


def _hit(row: dict, score: float, matched_by: list[str]) -> SearchHit:
    return SearchHit(
        chunk_id=row["chunk_id"],
        document_id=row["document_id"],
        filename=row["filename"],
        document_type=row["document_type"],
        page_number=row["page_number"],
        section_kind=row["section_kind"],
        section_title=row["section_title"],
        text=row["body"],
        surrounding_clause=row["section_body"],
        score=round(score, 6),
        policy_version=row.get("policy_version"),
        effective_date=row.get("effective_date"),
        matched_by=matched_by,
    )


def search(
    claim_id: str,
    query: str,
    k: int = 8,
    document_type: str | None = None,
    section_kind: str | None = None,
    policy_version: str | None = None,
    effective_date: str | None = None,
) -> SearchResponse:
    if not query or not query.strip():
        return SearchResponse(
            query=query or "",
            hits=[],
            evidence_sufficient=False,
            note="Enter a question or a clause.",
        )
    filters = {
        "document_type": document_type,
        "section_kind": section_kind,
        "policy_version": policy_version,
        "effective_date": effective_date,
    }
    provider, vector = embed_query(query)
    vector_rows = store.vector_search(claim_id, provider, vector, max(k * 3, 15), **filters)
    lexical_rows = store.lexical_search(claim_id, query, max(k * 3, 15), **filters)
    fused: dict[str, dict] = {}
    for name, rows in (("vector", vector_rows), ("lexical", lexical_rows)):
        for rank, row in enumerate(rows, start=1):
            slot = fused.setdefault(row["chunk_id"], {"row": row, "score": 0.0, "matched_by": []})
            slot["score"] += 1.0 / (60 + rank)
            if name not in slot["matched_by"]:
                slot["matched_by"].append(name)
    ordered = sorted(fused.values(), key=lambda slot: slot["score"], reverse=True)[:k]
    hits = [_hit(slot["row"], slot["score"], slot["matched_by"]) for slot in ordered]

    note = None
    bundle = looks_like_coverage_question(query) and section_kind is None
    if bundle:
        present = {hit.section_kind for hit in hits}
        for row in store.sections_by_kind(claim_id, BUNDLE_KINDS, **filters):
            if row["section_kind"] in present:
                continue
            if any(hit.chunk_id == row["chunk_id"] for hit in hits):
                continue
            hits.append(_hit(row, 0.0, ["coverage_bundle"]))
            present.add(row["section_kind"])
        note = (
            "A coverage question also returns the exclusion, endorsement, insured-period definition, "
            "and coverage wording stored for this claim."
        )

    if not hits:
        note = "Retrieved evidence is insufficient. Upload another source or search with different wording."
    return SearchResponse(query=query, hits=hits, evidence_sufficient=bool(hits), note=note)
