"""xAI judge for retrieved claim excerpts.

This client is only the retrieval eval. Investigation chat stays on OpenAI
and still refuses a Grok model id.
"""
import json
import logging
from dataclasses import dataclass

import httpx

from app.core.config import settings
from app.core.logutil import event

logger = logging.getLogger("app.agents")


class EvalJudgeError(RuntimeError):
    pass


@dataclass(frozen=True)
class JudgeResult:
    """``recall`` is the headline. ``precision`` is how many returned excerpts the judge kept."""

    recall: float
    precision: float | None
    recovered: list[int]
    relevant: list[int]
    model: str


def judge_retrieved(
    query: str,
    hits: list,
    expected_quotes: tuple[str, ...] | list[str] = (),
    expected_section_kinds: tuple[str, ...] | list[str] = (),
    post=None,
) -> JudgeResult:
    """Ask the xAI eval model which expected quotes the retrieved excerpts support.

    ``post`` is a test double. It receives ``(url, headers, body)`` and returns
    the chat-completions JSON. The default posts to ``settings.xai_base_url``.
    """
    if not settings.xai_api_key:
        raise EvalJudgeError("XAI_API_KEY is not set. The retrieval judge did not call xAI.")
    quotes = list(expected_quotes)
    kinds = list(expected_section_kinds)
    excerpts = [_excerpt(index, hit) for index, hit in enumerate(hits)]
    body = {
        "model": settings.xai_eval_model,
        "stream": False,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": _user_prompt(query, quotes, kinds, excerpts)},
        ],
    }
    event(logger, "retrieval judge request", model=settings.xai_eval_model, query=query, quotes=quotes, excerpts=excerpts)
    url = f"{settings.xai_base_url.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {settings.xai_api_key}"}
    payload = (post or _post)(url, headers, body)
    content = _message_content(payload)
    event(logger, "retrieval judge response", model=settings.xai_eval_model, content=content)
    parsed = _parse_json(content)
    recovered = _indexes(parsed.get("recovered"), len(quotes))
    relevant = _indexes(parsed.get("relevant"), len(hits))
    recall = 1.0 if not quotes else len(recovered) / len(quotes)
    precision = None if not hits else len(relevant) / len(hits)
    logger.info(
        "retrieval judge model=%s quotes=%s hits=%s recall=%.3f",
        settings.xai_eval_model,
        len(quotes),
        len(hits),
        recall,
    )
    return JudgeResult(
        recall=recall,
        precision=precision,
        recovered=recovered,
        relevant=relevant,
        model=settings.xai_eval_model,
    )


_SYSTEM = (
    "You grade retrieved excerpts from one insurance claim file. "
    "You do not grant or deny coverage, determine fraud, or authorise payment. "
    "Recover an expected quote only when an excerpt states that evidence. "
    "Mark an excerpt relevant only when it helps answer the query. "
    "Prefer finding the expected evidence over rejecting a close excerpt. "
    "Return JSON only, with keys recovered and relevant. Each value is a list of integer indexes."
)


def _excerpt(index: int, hit) -> str:
    text = f"{getattr(hit, 'text', '')}\n{getattr(hit, 'surrounding_clause', '')}"
    return (
        f"[{index}] {getattr(hit, 'filename', '')} page {getattr(hit, 'page_number', '')} "
        f"{getattr(hit, 'section_kind', '')}: {text[:2000]}"
    )


def _user_prompt(query: str, quotes: list[str], kinds: list[str], excerpts: list[str]) -> str:
    quote_lines = "\n".join(f"[{index}] {quote}" for index, quote in enumerate(quotes)) or "(none)"
    kind_lines = ", ".join(kinds) or "(none)"
    excerpt_lines = "\n".join(excerpts) or "(none)"
    return (
        f"Query:\n{query}\n\n"
        f"Expected quotes:\n{quote_lines}\n\n"
        f"Expected section kinds, for context only:\n{kind_lines}\n\n"
        f"Retrieved excerpts:\n{excerpt_lines}\n"
    )


def _post(url: str, headers: dict, body: dict) -> dict:
    try:
        response = httpx.post(url, headers=headers, json=body, timeout=60)
    except httpx.HTTPError as exc:
        raise EvalJudgeError("xAI retrieval judge request failed.") from exc
    if response.status_code >= 400:
        detail = _redact(response.text[:400])
        raise EvalJudgeError(f"xAI retrieval judge failed ({response.status_code}): {detail}")
    try:
        return response.json()
    except ValueError as exc:
        raise EvalJudgeError("xAI retrieval judge returned a body that is not JSON.") from exc


def _message_content(payload: dict) -> str:
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise EvalJudgeError("xAI retrieval judge returned no message content.") from exc
    if not isinstance(content, str) or not content.strip():
        raise EvalJudgeError("xAI retrieval judge returned an empty message.")
    return content


def _parse_json(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise EvalJudgeError("xAI retrieval judge did not return JSON.") from exc
    if not isinstance(parsed, dict):
        raise EvalJudgeError("xAI retrieval judge JSON must be an object.")
    return parsed


def _indexes(value, size: int) -> list[int]:
    if not isinstance(value, list):
        return []
    chosen: list[int] = []
    for item in value:
        if isinstance(item, int) and 0 <= item < size and item not in chosen:
            chosen.append(item)
    return chosen


def _redact(text: str) -> str:
    key = settings.xai_api_key or ""
    if key and key in text:
        return text.replace(key, "[redacted]")
    return text
