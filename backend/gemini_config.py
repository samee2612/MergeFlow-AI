from __future__ import annotations

import os

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash-lite"
DEFAULT_GEMINI_FALLBACK_MODEL = "gemini-2.5-flash"
DEFAULT_GEMINI_API_VERSION = "v1beta"


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
