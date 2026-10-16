"""Hybrid retrieval: pgvector similarity, PostgreSQL full-text search, and a coverage bundle.

Semantic and lexical lists are merged with weighted reciprocal rank fusion.
The default weights are 0.7 semantic and 0.3 lexical.
"""
import logging

from app.core.config import settings
from app.core.logutil import event
from app.core.models import SearchHit, SearchResponse
from app.services import store
from app.services.embeddings import embed_query
from app.services.textutil import looks_like_coverage_question

logger = logging.getLogger("app.retrieval")

BUNDLE_KINDS = ["coverage", "exclusion", "endorsement", "definition"]
RRF_CONSTANT = 60
CHANNELS = ("hybrid", "semantic", "lexical")


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


def fuse_rows(
    vector_rows: list[dict],
    lexical_rows: list[dict],
    k: int,
    semantic_weight: float | None = None,
    lexical_weight: float | None = None,
) -> list[dict]:
    """Merge two ranked lists. Rank 1 adds ``weight / 61``. Raw scores are not added."""
    semantic = settings.retrieval_semantic_weight if semantic_weight is None else semantic_weight
    lexical = settings.retrieval_lexical_weight if lexical_weight is None else lexical_weight
    fused: dict[str, dict] = {}
    for name, rows, weight in (
        ("vector", vector_rows, semantic),
        ("lexical", lexical_rows, lexical),
    ):
        for rank, row in enumerate(rows, start=1):
            slot = fused.setdefault(row["chunk_id"], {"row": row, "score": 0.0, "matched_by": []})
            slot["score"] += weight / (RRF_CONSTANT + rank)
            if name not in slot["matched_by"]:
                slot["matched_by"].append(name)
    ordered = sorted(fused.values(), key=lambda slot: (-slot["score"], slot["row"]["chunk_id"]))
    return ordered[:k]


def search(
    claim_id: str,
    query: str,
    k: int = 8,
    document_type: str | None = None,
    section_kind: str | None = None,
    policy_version: str | None = None,
    effective_date: str | None = None,
    channel: str = "hybrid",
) -> SearchResponse:
    if channel not in CHANNELS:
        raise ValueError(f"channel must be one of {CHANNELS}, got {channel!r}")
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
    limit = max(k * 3, 15)
    vector_rows: list[dict] = []
    lexical_rows: list[dict] = []
    if channel in {"hybrid", "semantic"}:
        provider, vector = embed_query(query)
        vector_rows = store.vector_search(claim_id, provider, vector, limit, **filters)
    if channel in {"hybrid", "lexical"}:
        lexical_rows = store.lexical_search(claim_id, query, limit, **filters)
    event(
        logger,
        "retrieval candidates",
        claim_id=claim_id,
        query=query,
        channel=channel,
        vector_hits=[{"id": row["chunk_id"], "kind": row["section_kind"], "text": row["body"]} for row in vector_rows],
        lexical_hits=[{"id": row["chunk_id"], "kind": row["section_kind"], "text": row["body"]} for row in lexical_rows],
    )
    ordered = fuse_rows(vector_rows, lexical_rows, k)
    hits = [_hit(slot["row"], slot["score"], slot["matched_by"]) for slot in ordered]

    note = None
    bundle = channel == "hybrid" and looks_like_coverage_question(query) and section_kind is None
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
