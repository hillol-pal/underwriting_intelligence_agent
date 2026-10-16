"""Ingest the synthetic corpus and print Phase 1 retrieval and extraction metrics."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.corpus.catalog import SEPTEMBER, QuerySpec, all_claims
from app.services import store
from app.services.eval_judge import EvalJudgeError, judge_retrieved
from app.services.evaluation import citation_correctness, fact_accuracy, score_retrieval
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
    print(
        "Retrieval headline is recall, blended "
        f"{settings.retrieval_semantic_weight:.0%} semantic and "
        f"{settings.retrieval_lexical_weight:.0%} lexical. Precision is reported and is not the pass gate."
    )
    for spec in SEPTEMBER.queries:
        hybrid = service.search(hero.claim_id, spec.query, k=spec.k, channel="hybrid")
        semantic = service.search(hero.claim_id, spec.query, k=spec.k, channel="semantic")
        lexical = service.search(hero.claim_id, spec.query, k=spec.k, channel="lexical")
        score = score_retrieval(spec, hybrid.hits, semantic.hits, lexical.hits)
        precision = "n/a" if score.hybrid_precision is None else f"{score.hybrid_precision:.2%}"
        print(
            f"Query {spec.name}: {'pass' if score.passed else 'fail'}  "
            f"recall={score.hybrid_recall:.2%}  precision={precision}  "
            f"semantic_recall={score.semantic_recall:.2%}  lexical_recall={score.lexical_recall:.2%}  "
            f"blended_recall={score.blended_recall:.2%}"
        )
        if not settings.xai_api_key:
            print(f"  xAI judge {spec.name}: skipped, XAI_API_KEY is not set")
            continue
        try:
            judged = judge_retrieved(
                spec.query,
                hybrid.hits,
                spec.expected_quotes,
                spec.expected_section_kinds,
            )
        except EvalJudgeError as exc:
            print(f"  xAI judge {spec.name}: failed ({exc})")
            continue
        judged_precision = "n/a" if judged.precision is None else f"{judged.precision:.2%}"
        print(
            f"  xAI judge {judged.model}: recall={judged.recall:.2%} precision={judged_precision} "
            "(recall is the judge headline)"
        )
    rear = next(claim for claim in loaded.values() if claim.policy_number == "POL-10001")
    sentence = "Rear-end collision on 20 March 2026 was reported with matching dates."
    rear_hybrid = service.search(rear.claim_id, sentence, k=5, channel="hybrid")
    rear_semantic = service.search(rear.claim_id, sentence, k=5, channel="semantic")
    rear_lexical = service.search(rear.claim_id, sentence, k=5, channel="lexical")
    rear_score = score_retrieval(
        QuerySpec(name="rear-end sentence", query=sentence, expected_quotes=(sentence,), k=5),
        rear_hybrid.hits,
        rear_semantic.hits,
        rear_lexical.hits,
    )
    print(
        "Rear-end sentence: "
        f"recall={rear_score.hybrid_recall:.2%}  blended_recall={rear_score.blended_recall:.2%}"
    )


if __name__ == "__main__":
    main()
