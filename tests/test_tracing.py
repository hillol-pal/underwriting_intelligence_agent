"""Provider selection and tracing stay local when MLflow is disabled."""
from app.core.config import settings
from app.services.embeddings import active_provider
from app.services.tracing import observation


def test_explicit_openai_provider(monkeypatch):
    monkeypatch.setattr(settings, "embedding_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    assert active_provider() == "openai"


def test_auto_prefers_openai_over_xai(monkeypatch):
    monkeypatch.setattr(settings, "embedding_provider", "auto")
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(settings, "xai_api_key", "xai-key")
    assert active_provider() == "openai"


def test_openai_provider_requires_a_key(monkeypatch):
    monkeypatch.setattr(settings, "embedding_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "")
    try:
        active_provider()
    except Exception as exc:
        assert "OPENAI_API_KEY" in str(exc)
    else:
        raise AssertionError("expected a missing-key error")


def test_observation_is_a_noop_under_pytest():
    with observation("should-not-send", {"claim_id": "CLM-TEST"}) as span:
        assert span is None
