"""Gemini-backed backend diff classification for MergeFlow."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any, Literal

from dotenv import load_dotenv
from google import genai
from google.genai import types
from loguru import logger

from backend.classifier.prompts import BACKEND_CLASSIFIER_SYSTEM_PROMPT, BACKEND_CLASSIFIER_USER_PROMPT

load_dotenv()

BackendChangeType = Literal[
    "API",
    "Service Logic",
    "Database",
    "Authentication",
    "Validation",
    "Configuration",
    "Bug Fix",
    "Refactor",
    "Unknown",
]

VALID_BACKEND_CHANGE_TYPES: set[BackendChangeType] = {
    "API",
    "Service Logic",
    "Database",
    "Authentication",
    "Validation",
    "Configuration",
    "Bug Fix",
    "Refactor",
    "Unknown",
}

DEFAULT_CLASSIFIER_MODEL = "gemini-2.5-flash-lite"
FALLBACK_CLASSIFIER_MODEL = "gemini-2.5-flash"
# v1beta matches the Gemini Developer API wire format (e.g. systemInstruction).
# The v1 endpoint rejects that field and returns 400 for classification requests.
DEFAULT_GEMINI_API_VERSION = "v1beta"
MAX_DIFF_CHARS = 30000


@dataclass(frozen=True)
class BackendDiffClassification:
    change_types: list[BackendChangeType]
    summary: str


UNKNOWN_CLASSIFICATION = BackendDiffClassification(
    change_types=["Unknown"],
    summary="Unable to classify backend change.",
)


def classify_backend_diff(diff_text: str, changed_files: list[str]) -> BackendDiffClassification:
    """Classify a merged backend PR diff with Gemini."""
    try:
        classification = _classify_with_gemini(diff_text, changed_files)
        logger.info(
            "Classified backend PR with Gemini change_types={change_types} summary={summary}",
            change_types=classification.change_types,
            summary=classification.summary,
        )
        return classification
    except Exception as error:
        logger.exception("Gemini backend classification failed error={error}", error=str(error))
        return UNKNOWN_CLASSIFICATION


def classify_diff(diff_text: str, changed_files: list[str]) -> BackendDiffClassification:
    """Backward-compatible wrapper for older callers."""
    return classify_backend_diff(diff_text, changed_files)


def get_classifier_model() -> str:
    """Primary classifier model from env or default."""
    return os.getenv("GEMINI_CLASSIFIER_MODEL") or DEFAULT_CLASSIFIER_MODEL


def get_classifier_fallback_model() -> str:
    return os.getenv("GEMINI_CLASSIFIER_FALLBACK_MODEL") or FALLBACK_CLASSIFIER_MODEL


def get_classifier_model_candidates() -> list[str]:
    candidates = [get_classifier_model()]
    fallback_model = get_classifier_fallback_model()
    if fallback_model not in candidates:
        candidates.append(fallback_model)
    return candidates


def get_gemini_api_version() -> str:
    return os.getenv("GEMINI_API_VERSION", DEFAULT_GEMINI_API_VERSION)


def _classify_with_gemini(diff_text: str, changed_files: list[str]) -> BackendDiffClassification:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    api_version = get_gemini_api_version()
    logger.info(
        "Configuring Gemini classifier api_version={api_version} models={models}",
        api_version=api_version,
        models=get_classifier_model_candidates(),
    )

    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(api_version=api_version),
    )
    prompt = BACKEND_CLASSIFIER_USER_PROMPT.format(
        changed_files=_format_changed_files(changed_files),
        diff_text=diff_text[:MAX_DIFF_CHARS],
    )
    config = _build_generate_content_config()

    last_error: Exception | None = None
    for model_name in get_classifier_model_candidates():
        logger.info("Using Gemini classifier model model={model}", model=model_name)
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config,
            )
            return _parse_classification_json(_extract_response_text(response))
        except Exception as error:
            last_error = error
            if _should_try_fallback_model(error, model_name):
                logger.warning(
                    "Gemini classifier model unavailable, trying fallback model={model} error={error}",
                    model=model_name,
                    error=str(error),
                )
                continue
            raise

    if last_error is not None:
        raise last_error
    raise RuntimeError("No Gemini classifier models were attempted")


def _build_generate_content_config() -> types.GenerateContentConfig:
    """Build SDK config with snake_case fields only (never a manual request dict)."""
    return types.GenerateContentConfig(
        system_instruction=BACKEND_CLASSIFIER_SYSTEM_PROMPT,
        max_output_tokens=500,
        temperature=0,
    )


def _should_try_fallback_model(error: Exception, model_name: str) -> bool:
    if model_name == get_classifier_model_candidates()[-1]:
        return False

    error_text = str(error).lower()
    model_error_markers = (
        "not found",
        "not supported",
        "invalid model",
        "model is not",
        "404",
        "429",
        "quota",
        "resource_exhausted",
    )
    return any(marker in error_text for marker in model_error_markers)


def _format_changed_files(changed_files: list[str]) -> str:
    return "\n".join(f"- {file_path}" for file_path in changed_files) or "- No changed files provided"


def _parse_classification_json(response_text: str) -> BackendDiffClassification:
    payload = json.loads(_strip_json_code_fence(response_text))
    if not isinstance(payload, dict):
        raise ValueError("Gemini classification response was not a JSON object")

    change_types = _validate_change_types(payload.get("change_types"))
    summary = str(payload.get("summary") or "").strip()
    if not summary:
        raise ValueError("Gemini classification response did not include a summary")

    return BackendDiffClassification(change_types=change_types, summary=summary)


def _validate_change_types(raw_change_types: Any) -> list[BackendChangeType]:
    if not isinstance(raw_change_types, list) or not raw_change_types:
        raise ValueError("Gemini classification response did not include change_types")

    change_types: list[BackendChangeType] = []
    for raw_change_type in raw_change_types:
        if raw_change_type not in VALID_BACKEND_CHANGE_TYPES or raw_change_type == "Unknown":
            raise ValueError(f"Invalid backend change type: {raw_change_type}")
        change_types.append(raw_change_type)

    return change_types


def _extract_response_text(response: object) -> str:
    text = getattr(response, "text", "")
    if isinstance(text, str):
        return text.strip()

    return ""


def _strip_json_code_fence(response_text: str) -> str:
    stripped_text = response_text.strip()
    if stripped_text.startswith("```json") and stripped_text.endswith("```"):
        return stripped_text.removeprefix("```json").removesuffix("```").strip()
    if stripped_text.startswith("```") and stripped_text.endswith("```"):
        return stripped_text.removeprefix("```").removesuffix("```").strip()

    return stripped_text
