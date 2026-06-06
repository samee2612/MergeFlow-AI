from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Literal

from dotenv import load_dotenv
from google import genai
from google.genai import types
from loguru import logger

from backend.classifier.prompts import SCOPE_CLASSIFIER_SYSTEM_PROMPT, SCOPE_CLASSIFIER_USER_PROMPT
from backend.gemini_config import (
    get_gemini_api_key,
    get_gemini_api_version,
    get_gemini_model_candidates,
)

load_dotenv()

ChangeScope = Literal["api", "frontend", "database", "infra", "mixed"]
ChangeAction = Literal["generate_api_artifacts", "track_only"]
ScopeConfidence = Literal["high", "medium", "low"]

VALID_SCOPES: set[ChangeScope] = {"api", "frontend", "database", "infra", "mixed"}
VALID_ACTIONS: set[ChangeAction] = {"generate_api_artifacts", "track_only"}
VALID_CONFIDENCE: set[ScopeConfidence] = {"high", "medium", "low"}

API_PATH_MARKERS = (
    "api/",
    "routes/",
    "controllers/",
    "services/",
    "models/",
    "schemas/",
    "backend/",
    "handlers/",
)

FRONTEND_PATH_MARKERS = (
    "frontend/",
    "src/components/",
    "src/pages/",
    "components/",
    "pages/",
    ".tsx",
    ".jsx",
    ".css",
    ".scss",
)

DATABASE_PATH_MARKERS = (
    "migrations/",
    "schema/",
    "db/",
    ".sql",
    "alembic/",
)

INFRA_PATH_MARKERS = (
    "dockerfile",
    "docker-compose",
    ".github/",
    "terraform/",
    "helm/",
    ".env",
    "ci/",
    "k8s/",
    "kubernetes/",
)


@dataclass(frozen=True)
class ChangeScopeClassification:
    scope: ChangeScope
    action: ChangeAction
    summary: str
    change_types: list[str]
    confidence: ScopeConfidence = "medium"
    source: Literal["gemini", "marker_fallback"] = "gemini"

    def as_dict(self) -> dict[str, object]:
        return {
            "scope": self.scope,
            "action": self.action,
            "summary": self.summary,
            "changeTypes": self.change_types,
            "confidence": self.confidence,
            "source": self.source,
        }


def classify_change_scope(
    changed_files: list[str],
    pr_title: str = "",
    repository: str = "",
) -> ChangeScopeClassification:
    """Classify PR change scope with Gemini, falling back to path markers."""
    try:
        classification = _classify_with_gemini(changed_files, pr_title, repository)
        logger.info(
            "Classified PR scope with Gemini scope={scope} action={action} confidence={confidence} summary={summary}",
            scope=classification.scope,
            action=classification.action,
            confidence=classification.confidence,
            summary=classification.summary,
        )
        return classification
    except Exception as error:
        logger.warning(
            "Gemini scope classification failed, using marker fallback error={error}",
            error=str(error),
        )
        return _classify_with_markers(changed_files, pr_title)


def _classify_with_gemini(
    changed_files: list[str],
    pr_title: str,
    repository: str,
) -> ChangeScopeClassification:
    api_key = get_gemini_api_key()
    api_version = get_gemini_api_version()
    models = get_gemini_model_candidates()
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(api_version=api_version),
    )
    prompt = SCOPE_CLASSIFIER_USER_PROMPT.format(
        repository=repository or "unknown",
        pr_title=pr_title or "Untitled PR",
        changed_files=_format_changed_files(changed_files),
    )
    config = types.GenerateContentConfig(
        system_instruction=SCOPE_CLASSIFIER_SYSTEM_PROMPT,
        max_output_tokens=300,
        temperature=0,
    )

    last_error: Exception | None = None
    for model_name in models:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config,
            )
            return _parse_scope_classification_json(_extract_response_text(response))
        except Exception as error:
            last_error = error
            if _should_try_fallback_model(error, model_name, models):
                logger.warning(
                    "Gemini scope classifier model unavailable, trying fallback model={model} error={error}",
                    model=model_name,
                    error=str(error),
                )
                continue
            raise

    if last_error is not None:
        raise last_error
    raise RuntimeError("No Gemini scope classifier models were attempted")


def _classify_with_markers(changed_files: list[str], pr_title: str = "") -> ChangeScopeClassification:
    """Deterministic fallback using file-path markers."""
    counts = {"api": 0, "frontend": 0, "database": 0, "infra": 0}

    for file_path in changed_files:
        normalized = file_path.replace("\\", "/").lstrip("/").lower()
        if _matches_any(normalized, API_PATH_MARKERS):
            counts["api"] += 1
        if _matches_any(normalized, FRONTEND_PATH_MARKERS):
            counts["frontend"] += 1
        if _matches_any(normalized, DATABASE_PATH_MARKERS):
            counts["database"] += 1
        if _matches_any(normalized, INFRA_PATH_MARKERS):
            counts["infra"] += 1

    active_scopes = [name for name, count in counts.items() if count > 0]
    scope = _resolve_scope(active_scopes)
    action: ChangeAction = "generate_api_artifacts" if counts["api"] > 0 else "track_only"
    change_types = _change_types_for_scope(scope, counts)
    summary = _build_summary(scope, action, changed_files, pr_title)

    return ChangeScopeClassification(
        scope=scope,
        action=action,
        summary=summary,
        change_types=change_types,
        confidence="medium",
        source="marker_fallback",
    )


def _parse_scope_classification_json(response_text: str) -> ChangeScopeClassification:
    payload = json.loads(_strip_json_code_fence(response_text))
    if not isinstance(payload, dict):
        raise ValueError("Gemini scope classification response was not a JSON object")

    scope = payload.get("scope")
    action = payload.get("action")
    if scope not in VALID_SCOPES:
        raise ValueError(f"Invalid scope: {scope}")
    if action not in VALID_ACTIONS:
        raise ValueError(f"Invalid action: {action}")

    change_types = _validate_change_types(payload.get("change_types"))
    summary = str(payload.get("summary") or "").strip()
    if not summary:
        raise ValueError("Gemini scope classification response did not include a summary")

    confidence = payload.get("confidence", "medium")
    if confidence not in VALID_CONFIDENCE:
        confidence = "medium"

    return ChangeScopeClassification(
        scope=scope,
        action=action,
        summary=summary,
        change_types=change_types,
        confidence=confidence,
        source="gemini",
    )


def _validate_change_types(raw_change_types: Any) -> list[str]:
    if not isinstance(raw_change_types, list) or not raw_change_types:
        raise ValueError("Gemini scope classification response did not include change_types")

    change_types: list[str] = []
    for raw_change_type in raw_change_types:
        label = str(raw_change_type).strip()
        if not label:
            raise ValueError("Gemini scope classification included an empty change type")
        change_types.append(label)

    return change_types


def _should_try_fallback_model(error: Exception, model_name: str, models: list[str]) -> bool:
    if model_name == models[-1]:
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


def _matches_any(normalized_path: str, markers: tuple[str, ...]) -> bool:
    return any(marker in normalized_path for marker in markers)


def _resolve_scope(active_scopes: list[str]) -> ChangeScope:
    if not active_scopes:
        return "mixed"
    if len(active_scopes) == 1:
        return active_scopes[0]  # type: ignore[return-value]
    if "api" in active_scopes:
        return "mixed"
    return active_scopes[0]  # type: ignore[return-value]


def _change_types_for_scope(scope: ChangeScope, counts: dict[str, int]) -> list[str]:
    labels: list[str] = []
    if counts["api"] > 0:
        labels.append("API")
    if counts["frontend"] > 0:
        labels.append("Frontend")
    if counts["database"] > 0:
        labels.append("Database")
    if counts["infra"] > 0:
        labels.append("Infra")
    if not labels:
        labels.append(scope.upper())
    return labels


def _build_summary(
    scope: ChangeScope,
    action: ChangeAction,
    changed_files: list[str],
    pr_title: str,
) -> str:
    file_count = len(changed_files)
    title_part = f' "{pr_title}"' if pr_title else ""
    if action == "generate_api_artifacts":
        return f"Backend/API {scope} change across {file_count} file(s){title_part}."
    return f"Tracked {scope} change across {file_count} file(s){title_part}. Full artifact generation is not enabled for this change type yet."
