"""Passage and query embeddings.

``openai`` calls the OpenAI embeddings API and is traced by MLflow autolog.
``xai`` calls xAI ``POST /v1/embeddings`` with model ``v1``.
``auto`` uses OpenAI when ``OPENAI_API_KEY`` is set, otherwise xAI, otherwise a
deterministic local hashing embedding so lexical search and the ledger still run.
Lexical search still carries exact policy numbers, dates, and clause ids.
"""
import hashlib
import logging
import math

import httpx

from app.core.config import settings
from app.core.logutil import event

logger = logging.getLogger("app.embeddings")
from app.services.tracing import observation, set_outputs


class EmbeddingError(RuntimeError):
    pass


def active_provider() -> str:
    choice = (settings.embedding_provider or "auto").lower()
    if choice == "auto":
        if settings.openai_api_key:
            return "openai"
        return "xai" if settings.xai_api_key else "local"
    if choice == "openai":
        if not settings.openai_api_key:
            raise EmbeddingError("OPENAI_API_KEY is not set.")
        return "openai"
    if choice not in {"xai", "local"}:
        raise EmbeddingError(f"Unknown embedding provider: {settings.embedding_provider}")
    return choice


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def local_embed(text: str) -> list[float]:
    dim = int(settings.embedding_dimensions)
    vector = [0.0] * dim
    tokens = text.lower().split()
    if not tokens:
        tokens = ["empty"]
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "little") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    return _normalize(vector)


def _xai_embed(texts: list[str], kind: str) -> list[list[float]]:
    if not settings.xai_api_key:
        raise EmbeddingError("XAI_API_KEY is not set.")
    prefixed = [f"{kind}: {text}" for text in texts]
    response = httpx.post(
        f"{settings.xai_base_url.rstrip('/')}/embeddings",
        headers={"Authorization": f"Bearer {settings.xai_api_key}"},
        json={
            "input": prefixed,
            "model": settings.embedding_model,
            "encoding_format": "float",
            "dimensions": int(settings.embedding_dimensions),
        },
        timeout=60,
    )
    if response.status_code >= 400:
        raise EmbeddingError(f"xAI embeddings failed ({response.status_code}): {response.text[:400]}")
    payload = response.json()
    rows = sorted(payload.get("data") or [], key=lambda row: row.get("index", 0))
    vectors: list[list[float]] = []
    expected = int(settings.embedding_dimensions)
    for row in rows:
        vector = row.get("embedding")
        if not isinstance(vector, list) or len(vector) != expected:
            raise EmbeddingError(
                f"xAI returned dimension {len(vector) if isinstance(vector, list) else 'unknown'}, expected {expected}."
            )
        vectors.append([float(value) for value in vector])
    if len(vectors) != len(texts):
        raise EmbeddingError("xAI returned a different number of embeddings than inputs.")
    return vectors


def _openai_embed(texts: list[str], kind: str) -> list[list[float]]:
    if not settings.openai_api_key:
        raise EmbeddingError("OPENAI_API_KEY is not set.")
    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
    prefixed = [f"{kind}: {text}" for text in texts]
    response = client.embeddings.create(
        input=prefixed,
        model=settings.openai_embedding_model,
        dimensions=int(settings.embedding_dimensions),
        encoding_format="float",
    )
    rows = sorted(response.data, key=lambda row: row.index)
    expected = int(settings.embedding_dimensions)
    vectors: list[list[float]] = []
    for row in rows:
        vector = list(row.embedding)
        if len(vector) != expected:
            raise EmbeddingError(f"OpenAI returned dimension {len(vector)}, expected {expected}.")
        vectors.append([float(value) for value in vector])
    if len(vectors) != len(texts):
        raise EmbeddingError("OpenAI returned a different number of embeddings than inputs.")
    return vectors


def embed_texts(texts: list[str], kind: str) -> tuple[str, list[list[float]]]:
    provider = active_provider()
    event(logger, "embed texts", provider=provider, kind=kind, texts=texts)
    if not texts:
        return provider, []
    with observation("embed_texts", {"provider": provider, "kind": kind, "count": len(texts)}) as span:
        if provider == "local":
            vectors = [local_embed(text) for text in texts]
        elif provider == "openai":
            vectors = []
            batch_size = 16
            for start in range(0, len(texts), batch_size):
                vectors.extend(_openai_embed(texts[start : start + batch_size], kind))
        else:
            vectors = []
            batch_size = 16
            for start in range(0, len(texts), batch_size):
                vectors.extend(_xai_embed(texts[start : start + batch_size], kind))
        set_outputs(span, {"provider": provider, "vectors": len(vectors), "dimensions": len(vectors[0]) if vectors else 0})
        return provider, vectors


def embed_query(text: str) -> tuple[str, list[float]]:
    provider, vectors = embed_texts([text], "query")
    return provider, vectors[0]
