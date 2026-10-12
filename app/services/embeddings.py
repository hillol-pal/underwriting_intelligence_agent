"""Passage and query embeddings.

xAI's embeddings endpoint is OpenAI-compatible: POST /v1/embeddings with model ``v1``.
Without ``XAI_API_KEY``, a deterministic local hashing embedding keeps hybrid search
runnable. Lexical search still carries exact policy numbers, dates, and clause ids.
"""
import hashlib
import math

import httpx

from app.core.config import settings


class EmbeddingError(RuntimeError):
    pass


def active_provider() -> str:
    choice = (settings.embedding_provider or "auto").lower()
    if choice == "auto":
        return "xai" if settings.xai_api_key else "local"
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


def embed_texts(texts: list[str], kind: str) -> tuple[str, list[list[float]]]:
    provider = active_provider()
    if not texts:
        return provider, []
    if provider == "local":
        return provider, [local_embed(text) for text in texts]
    vectors: list[list[float]] = []
    batch_size = 16
    for start in range(0, len(texts), batch_size):
        vectors.extend(_xai_embed(texts[start : start + batch_size], kind))
    return provider, vectors


def embed_query(text: str) -> tuple[str, list[float]]:
    provider, vectors = embed_texts([text], "query")
    return provider, vectors[0]
