from __future__ import annotations

import os
from typing import Any

from loguru import logger

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash-lite"
DEFAULT_GEMINI_FALLBACK_MODEL = "gemini-2.5-flash"
DEFAULT_GEMINI_API_VERSION = "v1beta"
DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-5-20250929"


def get_gemini_api_key() -> str:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    return api_key


def get_gemini_api_version() -> str:
    return os.getenv("GEMINI_API_VERSION", DEFAULT_GEMINI_API_VERSION)


def get_gemini_model() -> str:
    return os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)


def get_gemini_fallback_model() -> str:
    return os.getenv("GEMINI_FALLBACK_MODEL", DEFAULT_GEMINI_FALLBACK_MODEL)


def get_gemini_model_candidates() -> list[str]:
    candidates = [get_gemini_model()]
    fallback = get_gemini_fallback_model()
    if fallback not in candidates:
        candidates.append(fallback)
    return candidates


def get_anthropic_api_key() -> str | None:
    api_key = (os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY") or "").strip()
    if not api_key or api_key.startswith("your_") or api_key == "changeme":
        return None
    return api_key


def get_claude_model() -> str:
    return (os.getenv("ANTHROPIC_MODEL") or os.getenv("CLAUDE_MODEL") or DEFAULT_CLAUDE_MODEL).strip()


def try_generate_with_claude(
    prompt: str,
    system_instruction: str = "",
    max_output_tokens: int = 4000,
    temperature: float = 0.0,
    component: str = "mergeflow",
) -> str | None:
    """Attempt generation with Anthropic Claude if ANTHROPIC_API_KEY is set; return None to fall back to Gemini."""
    api_key = get_anthropic_api_key()
    if not api_key:
        return None

    model_name = get_claude_model()
    try:
        from anthropic import Anthropic

        logger.info(
            "Attempting Claude generation component={component} model={model}",
            component=component,
            model=model_name,
        )
        client = Anthropic(api_key=api_key)
        kwargs: dict[str, Any] = {
            "model": model_name,
            "max_tokens": max_output_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_instruction:
            kwargs["system"] = system_instruction

        response = client.messages.create(**kwargs)
        text_parts: list[str] = []
        for block in getattr(response, "content", []) or []:
            block_text = getattr(block, "text", None)
            if isinstance(block_text, str) and block_text.strip():
                text_parts.append(block_text.strip())

        combined = "\n".join(text_parts).strip()
        if combined:
            logger.info(
                "Claude generation succeeded component={component} model={model} char_count={char_count}",
                component=component,
                model=model_name,
                char_count=len(combined),
            )
            return combined

        logger.warning(
            "Claude returned empty output; falling back to Gemini component={component} model={model}",
            component=component,
            model=model_name,
        )
        return None
    except Exception as error:
        logger.warning(
            "Claude generation unavailable or failed; falling back to Gemini component={component} model={model} error={error}",
            component=component,
            model=model_name,
            error=str(error),
        )
        return None
