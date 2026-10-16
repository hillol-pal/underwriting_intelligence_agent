"""OpenAI chat models for the supervisor and the specialists.

Embeddings are not constructed here. gpt-5.6-sol defaults to reasoning effort
medium. gpt-5.4-mini defaults to none. Do not pass reasoning_effort unless
this client requires the parameter.
"""
import logging

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from app.core.config import settings

logger = logging.getLogger("app.agents")


class AgentConfigError(RuntimeError):
    pass


def validate_agent_config() -> None:
    """Reject a non-OpenAI provider, a missing key, or a refused model id.

    This runs before any HTTP call and before a running row is inserted.
    """
    provider = (settings.llm_provider or "").lower()
    if provider != "openai":
        raise AgentConfigError(
            f"Agent completions require llm_provider='openai', got {settings.llm_provider!r}. "
            "Embeddings are a separate setting and must stay as they are."
        )
    if not settings.openai_api_key:
        raise AgentConfigError("OPENAI_API_KEY is not set.")
    for model_id in (settings.llm_model, settings.llm_specialist_model):
        _reject_model_id(model_id)


def _reject_model_id(model_id: str) -> None:
    lowered = (model_id or "").lower()
    if "codex" in lowered or lowered.startswith("grok"):
        raise AgentConfigError(f"Refusing agent model id {model_id!r}.")


def build_chat_model(model_id: str) -> BaseChatModel:
    """OpenAI chat model for the supervisor or a specialist.

    Retention is the create_deep_agent docstring triple: use_responses_api,
    store=False, and include=["reasoning.encrypted_content"]. Pass all three.
    Do not drop include to make the first tool round succeed. Embeddings are
    not constructed here. timeout bounds one HTTP call at 60 seconds.
    gpt-5.6-sol defaults to reasoning effort medium. gpt-5.4-mini defaults
    to none. Do not pass reasoning_effort unless this client requires it.
    The installed ChatOpenAI has no required reasoning_effort field, so this
    function does not pass one. init_chat_model maps timeout onto
    request_timeout.
    """
    provider = (settings.llm_provider or "").lower()
    if provider != "openai":
        raise AgentConfigError(
            f"Agent completions require llm_provider='openai', got {settings.llm_provider!r}. "
            "Embeddings are a separate setting and must stay as they are."
        )
    if not settings.openai_api_key:
        raise AgentConfigError("OPENAI_API_KEY is not set.")
    _reject_model_id(model_id)
    logger.debug("Building OpenAI chat model id=%s", model_id)
    return init_chat_model(
        f"openai:{model_id}",
        api_key=settings.openai_api_key,
        use_responses_api=True,
        store=False,
        include=["reasoning.encrypted_content"],
        timeout=60,
    )
