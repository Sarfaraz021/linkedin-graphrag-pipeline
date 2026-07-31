"""LLM construction with OpenAI primary and Anthropic fallback."""

from __future__ import annotations

import logging
from typing import Any

from neo4j_graphrag.llm import AnthropicLLM, OpenAILLM

from backend.pipeline.config import Settings

logger = logging.getLogger(__name__)


def _openai_llm(settings: Settings, *, json_mode: bool = False) -> OpenAILLM:
    params: dict[str, Any] = {"temperature": 0}
    if json_mode:
        params["response_format"] = {"type": "json_object"}
    return OpenAILLM(
        model_name=settings.llm_model,
        api_key=settings.openai_api_key,
        model_params=params,
    )


def _anthropic_llm(settings: Settings) -> AnthropicLLM:
    if not settings.anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY is required when using Anthropic LLM")
    return AnthropicLLM(
        model_name=settings.anthropic_model,
        api_key=settings.anthropic_api_key,
        model_params={"temperature": 0},
    )


def build_llm(settings: Settings, *, json_mode: bool = False) -> OpenAILLM | AnthropicLLM:
    """Return an LLM client. Prefers configured provider; falls back on failure."""
    provider = settings.llm_provider.lower()

    if provider == "anthropic":
        return _anthropic_llm(settings)

    if provider == "openai":
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
        return _openai_llm(settings, json_mode=json_mode)

    # auto: try OpenAI first, then Anthropic
    if settings.openai_api_key:
        try:
            return _openai_llm(settings, json_mode=json_mode)
        except Exception as exc:
            logger.warning("OpenAI LLM init failed (%s); trying Anthropic", exc)

    if settings.anthropic_api_key:
        logger.info("Using Anthropic LLM (%s)", settings.anthropic_model)
        return _anthropic_llm(settings)

    raise ValueError("Set OPENAI_API_KEY and/or ANTHROPIC_API_KEY for LLM calls")


def invoke_llm(llm: Any, prompt: str) -> str:
    """Invoke LLM with OpenAI-then-Anthropic retry on API errors."""
    try:
        response = llm.invoke(prompt)
        return response.content if hasattr(response, "content") else str(response)
    except Exception as first_exc:
        if isinstance(llm, AnthropicLLM):
            raise
        logger.warning("LLM invoke failed (%s); retrying with Anthropic", first_exc)
        from backend.pipeline.config import get_settings

        settings = get_settings()
        fallback = _anthropic_llm(settings)
        response = fallback.invoke(prompt)
        return response.content if hasattr(response, "content") else str(response)
