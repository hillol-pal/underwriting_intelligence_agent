"""MLflow tracing for the investigation flow and OpenAI embedding calls."""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Iterator

from app.core.config import _under_pytest, reload_settings, settings

logger = logging.getLogger(__name__)

_configured = False
_disabled_reason: str | None = None
_retry_after = 0.0
_RETRY_SECONDS = 30.0


def tracing_enabled() -> bool:
    return bool(settings.mlflow_tracing_enabled)


def configure_tracing() -> bool:
    """Point MLflow at the tracking server and turn on OpenAI autolog.

    Returns False when tracing is off or the server cannot be reached. A
    failed attempt is retried after 30 seconds. The investigation still runs.
    """
    global _configured, _disabled_reason, _retry_after
    if _under_pytest():
        return False
    reload_settings()
    if not settings.mlflow_tracing_enabled:
        return False
    if _configured:
        return True
    if time.monotonic() < _retry_after:
        return False

    import mlflow

    uri = settings.mlflow_tracking_uri
    try:
        mlflow.set_tracking_uri(uri)
        mlflow.set_experiment(settings.mlflow_experiment)
        mlflow.openai.autolog()
    except Exception as exc:
        _disabled_reason = str(exc)
        _retry_after = time.monotonic() + _RETRY_SECONDS
        logger.warning("MLflow tracing is off because %s could not be reached: %s", uri, exc)
        return False
    _configured = True
    _disabled_reason = None
    logger.info(
        "MLflow tracing on at %s experiment=%s embedding_provider=%s llm_provider=%s openai_key_set=%s",
        uri,
        settings.mlflow_experiment,
        settings.embedding_provider,
        settings.llm_provider,
        bool(settings.openai_api_key),
    )
    return True


@contextmanager
def observation(name: str, inputs: dict | None = None) -> Iterator[object | None]:
    """Open a span when tracing is configured. Yield None when it is not."""
    if not tracing_enabled():
        yield None
        return
    if not _configured and not configure_tracing():
        yield None
        return
    import mlflow

    with mlflow.start_span(name=name) as span:
        if inputs:
            span.set_inputs(inputs)
        yield span


def set_outputs(span: object | None, outputs: dict) -> None:
    if span is not None:
        span.set_outputs(outputs)
