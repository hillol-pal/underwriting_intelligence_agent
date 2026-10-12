"""Ingest the synthetic corpus and print Phase 1 retrieval and extraction metrics."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.corpus.catalog import SEPTEMBER, all_claims
from app.services import store
from app.services.evaluation import citation_correctness, fact_accuracy, query_passed, recall_at_k
from app.services.investigation import InvestigationService


def main() -> None:
    service = InvestigationService()
    loaded = {claim.policy_number: claim for claim in service.load_catalog()}
    documents = sum(len(spec.documents) for spec in all_claims())
    print(f"Claims: {len(loaded)}  Documents: {documents}")
    hero = loaded[SEPTEMBER.policy_number]
    findings = service.get_findings(hero.claim_id)
    document_ids = {item.filename: item.document_id for item in service.list_documents(hero.claim_id)}
    pages = {(row["document_id"], row["page_number"]): row["body"] for row in store.pages_for_claim(hero.claim_id)}
    print(f"Fact extraction accuracy: {fact_accuracy(SEPTEMBER.facts, findings, document_ids):.2%}")
    print(f"Citation correctness: {citation_correctness(findings, pages):.2%}")
    for spec in SEPTEMBER.queries:
        result = service.search(hero.claim_id, spec.query, k=spec.k)
        texts = [hit.text + "\n" + hit.surrounding_clause for hit in result.hits]
        if spec.expected_quotes:
            print(f"Recall@{spec.k} {spec.name}: {recall_at_k(spec.expected_quotes, texts, spec.k):.2%}")
        print(f"Query {spec.name}: {'pass' if query_passed(spec, result.hits) else 'fail'}")
    rear = next(claim for claim in loaded.values() if claim.policy_number == "POL-10001")
    sentence = "Rear-end collision on 20 March 2026 was reported with matching dates."
    rear_hits = service.search(rear.claim_id, sentence, k=5).hits
    print(
        "Recall@5 rear-end sentence: "
        f"{recall_at_k([sentence], [hit.text + ' ' + hit.surrounding_clause for hit in rear_hits], 5):.2%}"
    )


if __name__ == "__main__":
    main()
