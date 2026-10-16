"""Recall-first retrieval metrics and the xAI judge. No live xAI call."""
import pytest

from app.core.config import Settings, settings
from app.corpus.catalog import QuerySpec
from app.services.eval_judge import EvalJudgeError, judge_retrieved
from app.services.evaluation import blended_recall, precision_at_k, query_passed, score_retrieval
from app.services.retrieval import fuse_rows, search


class Hit:
    def __init__(self, text: str, kind: str = "body", clause: str = ""):
        self.text = text
        self.surrounding_clause = clause
        self.section_kind = kind
        self.filename = "policy_wording.pdf"
        self.page_number = 1


def test_fusion_weights_semantic_above_lexical():
    semantic = [{"chunk_id": "semantic"}]
    lexical = [{"chunk_id": "lexical"}]
    fused = fuse_rows(semantic, lexical, k=2, semantic_weight=0.7, lexical_weight=0.3)
    assert [slot["row"]["chunk_id"] for slot in fused] == ["semantic", "lexical"]
    assert fused[0]["score"] == pytest.approx(0.7 / 61)
    assert fused[1]["score"] == pytest.approx(0.3 / 61)


def test_fusion_adds_both_channels_for_the_same_chunk():
    row = [{"chunk_id": "both"}]
    fused = fuse_rows(row, row, k=1, semantic_weight=0.7, lexical_weight=0.3)
    assert fused[0]["matched_by"] == ["vector", "lexical"]
    assert fused[0]["score"] == pytest.approx((0.7 + 0.3) / 61)


def test_default_weights_are_seventy_thirty():
    assert Settings.model_fields["retrieval_semantic_weight"].default == 0.7
    assert Settings.model_fields["retrieval_lexical_weight"].default == 0.3
    assert Settings.model_fields["xai_eval_model"].default == "grok-4.7"


def test_recall_passes_when_precision_is_partial():
    spec = QuerySpec(name="period", query="insured period", expected_quotes=("insured period",), k=2)
    hits = [Hit("during the insured period"), Hit("unrelated invoice total")]
    assert query_passed(spec, hits) is True
    assert precision_at_k(["insured period"], ["during the insured period", "unrelated invoice total"], 2) == 0.5
    score = score_retrieval(spec, hits, hits, [Hit("no date here")])
    assert score.passed is True
    assert score.hybrid_recall == 1.0
    assert score.semantic_recall == 1.0
    assert score.lexical_recall == 0.0
    assert score.blended_recall == pytest.approx(blended_recall(1.0, 0.0))
    assert score.hybrid_precision == 0.5


def test_unknown_channel_is_rejected_before_a_database_call():
    with pytest.raises(ValueError):
        search("CLM-TEST", "collision", channel="bm25")


def test_judge_recall_is_the_headline_and_does_not_call_the_network(monkeypatch):
    monkeypatch.setattr(settings, "xai_api_key", "xai-test-key")
    monkeypatch.setattr(settings, "xai_eval_model", "grok-4.7")
    monkeypatch.setattr(settings, "xai_base_url", "https://api.x.ai/v1")
    seen = {}

    def post(url, headers, body):
        seen["url"] = url
        seen["model"] = body["model"]
        seen["auth"] = headers["Authorization"]
        assert "openai" not in url
        return {
            "choices": [
                {
                    "message": {
                        "content": '```json\n{"recovered": [0], "relevant": [0]}\n```',
                    }
                }
            ]
        }

    result = judge_retrieved(
        "is collision covered",
        [Hit("Accidental collision damage is covered during the insured period."), Hit("invoice")],
        expected_quotes=("Accidental collision damage is covered", "a quote that is absent"),
        post=post,
    )
    assert seen["url"] == "https://api.x.ai/v1/chat/completions"
    assert seen["model"] == "grok-4.7"
    assert seen["auth"] == "Bearer xai-test-key"
    assert result.recall == 0.5
    assert result.precision == 0.5
    assert result.model == "grok-4.7"


def test_judge_does_not_call_xai_without_a_key(monkeypatch):
    monkeypatch.setattr(settings, "xai_api_key", "")

    def post(url, headers, body):
        raise AssertionError("xAI was called")

    with pytest.raises(EvalJudgeError, match="XAI_API_KEY"):
        judge_retrieved("query", [Hit("text")], expected_quotes=("text",), post=post)
