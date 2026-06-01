"""Diff type classification for MergeFlow pipeline runs."""

from __future__ import annotations

import os
import re
from pathlib import PurePosixPath
from typing import Literal

from dotenv import load_dotenv
import google.generativeai as genai
from loguru import logger

load_dotenv()

DiffClassification = Literal["api", "frontend", "database", "infra", "mixed"]

VALID_CLASSIFICATIONS: set[DiffClassification] = {
    "api",
    "frontend",
    "database",
    "infra",
    "mixed",
}

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")
MAX_DIFF_CHARS = 12000

API_KEYWORDS = (
    "api",
    "apis",
    "route",
    "routes",
    "router",
    "controller",
    "controllers",
    "handler",
    "handlers",
    "endpoint",
    "endpoints",
    "swagger",
    "openapi",
)
FRONTEND_KEYWORDS = (
    "component",
    "components",
    "page",
    "pages",
    "view",
    "views",
    "screen",
    "screens",
    "frontend",
    "client",
    "ui",
)
DATABASE_KEYWORDS = (
    "migration",
    "migrations",
    "schema",
    "schemas",
    "model",
    "models",
    "orm",
    "prisma",
    "sequelize",
    "alembic",
)
INFRA_KEYWORDS = (
    ".github",
    "ci",
    "cd",
    "workflow",
    "workflows",
    "docker",
    "config",
    "configs",
    "k8s",
    "kubernetes",
    "terraform",
    "helm",
    "infra",
)

API_EXTENSIONS = {".yaml", ".yml"}
FRONTEND_EXTENSIONS = {".jsx", ".tsx", ".vue", ".html", ".css", ".scss", ".sass", ".less"}
DATABASE_EXTENSIONS = {".sql"}
INFRA_FILENAMES = {
    ".env",
    ".env.example",
    ".env.local",
    ".env.production",
    "dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
}
INFRA_EXTENSIONS = {".toml", ".ini", ".conf", ".cfg"}


def classify_diff(diff_text: str, changed_files: list[str]) -> DiffClassification:
    """Classify a PR diff into the MergeFlow output category it should trigger."""
    try:
        classification = _classify_with_gemini(diff_text, changed_files)
        logger.info(
            "Classified diff with Gemini classification={classification} changed_file_count={changed_file_count}",
            classification=classification,
            changed_file_count=len(changed_files),
        )
        return classification
    except Exception as error:
        logger.warning(
            "Gemini diff classification failed; falling back to file detection error={error}",
            error=str(error),
        )

    classification = _classify_from_files(changed_files)
    logger.info(
        "Classified diff with fallback classification={classification} changed_file_count={changed_file_count}",
        classification=classification,
        changed_file_count=len(changed_files),
    )
    return classification


def _classify_with_gemini(diff_text: str, changed_files: list[str]) -> DiffClassification:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        GEMINI_MODEL,
        system_instruction=(
            "You classify GitHub pull request diffs for MergeFlow AI. "
            "Return exactly one lowercase label from this set: api, frontend, database, infra, mixed. "
            "Use mixed when more than one category is represented."
        ),
    )
    files_text = "\n".join(f"- {file_path}" for file_path in changed_files) or "- No changed files provided"
    truncated_diff = diff_text[:MAX_DIFF_CHARS]

    response = model.generate_content(
        (
            "Classification signals:\n"
            "- api: route files, controllers, handlers, .yaml/.yml OpenAPI or Swagger specs\n"
            "- frontend: React/Vue/HTML/CSS components, pages, views, UI files\n"
            "- database: migrations, schema files, ORM models\n"
            "- infra: .env files, CI YAML, Dockerfile, config files\n"
            "- mixed: a combination of the above\n\n"
            f"Changed files:\n{files_text}\n\n"
            f"Diff:\n{truncated_diff}\n\n"
            "Return only the label."
        ),
        generation_config=genai.types.GenerationConfig(
            max_output_tokens=10,
            temperature=0,
        ),
    )

    classification = _extract_response_text(response).strip().lower()
    if classification not in VALID_CLASSIFICATIONS:
        raise ValueError(f"Gemini returned invalid classification: {classification}")

    return classification


def _extract_response_text(response: object) -> str:
    text = getattr(response, "text", "")
    if isinstance(text, str):
        return text

    return ""


def _classify_from_files(changed_files: list[str]) -> DiffClassification:
    detected_types: set[DiffClassification] = set()

    for file_path in changed_files:
        detected_type = _detect_file_type(file_path)
        if detected_type:
            detected_types.add(detected_type)

    if len(detected_types) > 1:
        return "mixed"
    if len(detected_types) == 1:
        return detected_types.pop()

    return "mixed"


def _detect_file_type(file_path: str) -> DiffClassification | None:
    normalized_path = file_path.replace("\\", "/").lower()
    path = PurePosixPath(normalized_path)
    filename = path.name
    suffix = path.suffix
    parts = set(path.parts)
    searchable_parts = parts | {path.stem}

    if _has_any_signal(searchable_parts, API_KEYWORDS) or _is_api_spec(filename, suffix):
        return "api"

    if _has_any_signal(searchable_parts, FRONTEND_KEYWORDS) or suffix in FRONTEND_EXTENSIONS:
        return "frontend"

    if _has_any_signal(searchable_parts, DATABASE_KEYWORDS) or suffix in DATABASE_EXTENSIONS:
        return "database"

    if (
        _has_any_signal(searchable_parts, INFRA_KEYWORDS)
        or filename in INFRA_FILENAMES
        or suffix in INFRA_EXTENSIONS
        or normalized_path.startswith(".github/workflows/")
    ):
        return "infra"

    return None


def _has_any_signal(parts: set[str], keywords: tuple[str, ...]) -> bool:
    tokens: set[str] = set()
    for part in parts:
        tokens.update(token for token in re.split(r"[^a-z0-9]+", part) if token)

    return any(keyword in tokens for keyword in keywords)


def _is_api_spec(filename: str, suffix: str) -> bool:
    return suffix in API_EXTENSIONS and (
        "openapi" in filename
        or "swagger" in filename
        or filename in {"api.yaml", "api.yml"}
    )
