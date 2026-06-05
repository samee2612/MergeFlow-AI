from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import TYPE_CHECKING, Awaitable, Callable

from google import genai
from google.genai import types
from loguru import logger

from backend.classifier.diff_classifier import BackendDiffClassification, get_gemini_api_version
from backend.generators.prompts import API_SPEC_GENERATOR_SYSTEM_PROMPT, API_SPEC_GENERATOR_USER_PROMPT
from backend.github_client import (
    GitHubCommitResult,
    commit_repository_file_text,
    fetch_repository_file_text,
    resolve_commit_branch,
)

if TYPE_CHECKING:
    from backend.pipeline import PullRequestContext

DEFAULT_API_SPEC_MODEL = "gemini-2.5-flash-lite"
FALLBACK_API_SPEC_MODEL = "gemini-2.5-flash"
TARGET_REPO_ARTIFACT_PATH = "tests/api-spec-and-test-cases.md"
MAX_PATCH_CHARS_PER_FILE = 12000
MAX_CONTENT_CHARS_PER_FILE = 20000

ROUTE_FILE_MARKERS = (
    "api/",
    "apis/",
    "routes/",
    "routers/",
    "controllers/",
)
DIRECT_DEPENDENCY_MARKERS = (
    "services/",
    "schemas/",
    "models/",
    "validators/",
    "validation/",
    "auth/",
    "authentication/",
    "responses/",
    "response_builders/",
    "serializers/",
)

FileFetcher = Callable[[str, str], Awaitable[str]]
ArtifactCommitter = Callable[[str, str, str, str, str, int | None], Awaitable[GitHubCommitResult]]


@dataclass(frozen=True)
class RelatedFileContext:
    file_path: str
    patch: str
    content: str


async def generate_api_spec_and_test_cases(
    pr_context: PullRequestContext,
    classification: BackendDiffClassification,
    diff_text: str,
    file_fetcher: FileFetcher = fetch_repository_file_text,
    artifact_committer: ArtifactCommitter = commit_repository_file_text,
) -> str:
    related_files = select_directly_related_files(pr_context.changed_files)
    patches_by_file = extract_patches_by_file(diff_text)
    file_contexts = await fetch_related_file_contexts(
        pr_context.repository,
        related_files,
        patches_by_file,
        file_fetcher,
    )

    try:
        markdown = _generate_markdown_with_gemini(pr_context, classification, file_contexts)
    except Exception as error:
        logger.exception("API spec/test-case generation failed; writing fallback markdown error={error}", error=str(error))
        markdown = build_fallback_markdown(pr_context, classification, file_contexts, str(error))

    target_path = build_target_repo_artifact_path()
    target_branch = await resolve_target_branch(pr_context)
    commit_message = build_artifact_commit_message(pr_context)

    markdown_content = markdown.rstrip() + "\n"
    logger.info(
        "Generated API spec/test-case markdown locally repo={repo} pr_number={pr_number} char_count={char_count}",
        repo=pr_context.repository,
        pr_number=pr_context.pr_number,
        char_count=len(markdown_content),
    )

    try:
        commit_result = await artifact_committer(
            pr_context.repository,
            target_branch,
            target_path,
            markdown_content,
            commit_message,
            pr_context.pr_number,
        )
    except Exception as error:
        logger.exception(
            "Unexpected commit failure for API spec artifact repo={repo} branch={branch} path={path} error={error}",
            repo=pr_context.repository,
            branch=target_branch,
            path=target_path,
            error=str(error),
        )
        return target_path

    if not commit_result.success:
        logger.error(
            "API spec markdown generated but GitHub commit failed repo={repo} branch={branch} path={path} "
            "local_backup_path={local_backup_path} error={error}",
            repo=commit_result.repository,
            branch=commit_result.branch,
            path=commit_result.file_path,
            local_backup_path=commit_result.local_backup_path,
            error=commit_result.error_message,
        )
        return commit_result.file_path

    logger.info(
        "Generated API spec/test-case output in target repo repo={repo} branch={branch} path={path} destination={destination}",
        repo=pr_context.repository,
        branch=target_branch,
        path=target_path,
        destination=commit_result.destination,
    )
    return commit_result.destination


def build_target_repo_artifact_path() -> str:
    return TARGET_REPO_ARTIFACT_PATH


async def resolve_target_branch(pr_context: PullRequestContext) -> str:
    return await resolve_commit_branch(
        pr_context.repository,
        [
            pr_context.base_branch,
            pr_context.default_branch,
            pr_context.head_branch,
        ],
    )


def build_artifact_commit_message(pr_context: PullRequestContext) -> str:
    pr_number = f"#{pr_context.pr_number}" if pr_context.pr_number is not None else "merged PR"
    return f"Add MergeFlow API test cases for {pr_number}"


def select_directly_related_files(changed_files: list[str]) -> list[str]:
    normalized_files = [file_path for file_path in changed_files if _is_backend_file(file_path)]
    route_files = [file_path for file_path in normalized_files if _has_marker(file_path, ROUTE_FILE_MARKERS)]
    dependency_files = [file_path for file_path in normalized_files if _has_marker(file_path, DIRECT_DEPENDENCY_MARKERS)]

    selected_files = route_files + dependency_files
    if not selected_files:
        selected_files = normalized_files

    return _dedupe_preserving_order(selected_files)


def extract_patches_by_file(diff_text: str) -> dict[str, str]:
    patches_by_file: dict[str, str] = {}
    matches = list(re.finditer(r"^diff --git a/.+ b/(?P<file_path>.+)$", diff_text, re.MULTILINE))

    for index, match in enumerate(matches):
        file_path = match.group("file_path")
        patch_start = match.start()
        patch_end = matches[index + 1].start() if index + 1 < len(matches) else len(diff_text)
        patches_by_file[file_path] = diff_text[patch_start:patch_end].strip()

    return patches_by_file


async def fetch_related_file_contexts(
    repository: str,
    related_files: list[str],
    patches_by_file: dict[str, str],
    file_fetcher: FileFetcher,
) -> list[RelatedFileContext]:
    contexts: list[RelatedFileContext] = []
    for file_path in related_files:
        try:
            content = await file_fetcher(repository, file_path)
        except Exception as error:
            logger.warning("Could not fetch related file content file_path={file_path} error={error}", file_path=file_path, error=str(error))
            content = "File content unavailable."

        contexts.append(
            RelatedFileContext(
                file_path=file_path,
                patch=patches_by_file.get(file_path, "")[:MAX_PATCH_CHARS_PER_FILE],
                content=content[:MAX_CONTENT_CHARS_PER_FILE],
            )
        )

    logger.info("Collected direct API spec context related_files={related_files}", related_files=related_files)
    return contexts


def _generate_markdown_with_gemini(
    pr_context: PullRequestContext,
    classification: BackendDiffClassification,
    file_contexts: list[RelatedFileContext],
) -> str:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    api_version = get_gemini_api_version()
    models = get_api_spec_model_candidates()
    logger.info("Configuring Gemini API spec generator api_version={api_version} models={models}", api_version=api_version, models=models)

    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(api_version=api_version),
    )
    prompt = build_api_spec_prompt(pr_context, classification, file_contexts)
    config = types.GenerateContentConfig(
        system_instruction=API_SPEC_GENERATOR_SYSTEM_PROMPT,
        max_output_tokens=4000,
        temperature=0,
    )

    last_error: Exception | None = None
    for model_name in models:
        logger.info("Using Gemini API spec generator model model={model}", model=model_name)
        try:
            response = client.models.generate_content(model=model_name, contents=prompt, config=config)
            markdown = _extract_response_text(response)
            if not markdown:
                raise ValueError("Gemini API spec generator returned empty output")
            return markdown
        except Exception as error:
            last_error = error
            if _should_try_fallback_model(error, model_name, models):
                logger.warning("Gemini API spec model failed, trying fallback model={model} error={error}", model=model_name, error=str(error))
                continue
            raise

    if last_error:
        raise last_error
    raise RuntimeError("No Gemini API spec generator models were attempted")


def build_api_spec_prompt(
    pr_context: PullRequestContext,
    classification: BackendDiffClassification,
    file_contexts: list[RelatedFileContext],
) -> str:
    return API_SPEC_GENERATOR_USER_PROMPT.format(
        repository=pr_context.repository,
        pr_number=pr_context.pr_number,
        title=pr_context.title,
        classification=", ".join(classification.change_types),
        classification_summary=classification.summary,
        changed_files=_format_list(pr_context.changed_files),
        related_files=_format_list([context.file_path for context in file_contexts]),
        patches=_format_context_section(file_contexts, "patch"),
        file_contents=_format_context_section(file_contexts, "content"),
    )


def build_fallback_markdown(
    pr_context: PullRequestContext,
    classification: BackendDiffClassification,
    file_contexts: list[RelatedFileContext],
    error: str,
) -> str:
    related_files = [context.file_path for context in file_contexts]
    return f"""# API Spec and Test Cases

## 1. Change Summary
Gemini generation failed, so this fallback document was generated from available pipeline metadata.

- Repository: `{pr_context.repository}`
- PR number: `{pr_context.pr_number}`
- Title: {pr_context.title}
- Classification: {", ".join(classification.change_types)}
- Classification summary: {classification.summary}
- Generator error: `{error}`

## 2. Endpoint(s) Detected
Not detected from provided context.

## 3. Directly Related Files Considered
{_format_list(related_files)}

## 4. API Specification Snapshot
Not detected from provided context.

## 5. Test Cases
- Verify the changed backend flow still succeeds for its documented happy path.
- Verify required validation and authorization checks still apply.

## 6. Edge Cases
Not detected from provided context.

## 7. Regression Risks
- Gemini generation did not complete, so endpoint-level coverage needs manual review.

## 8. Swagger/OpenAPI-Ready Notes
- Re-run generation after resolving the Gemini error to populate method, path, parameters, schemas, and responses.
"""


def get_api_spec_model_candidates() -> list[str]:
    primary = os.getenv("GEMINI_API_SPEC_MODEL") or os.getenv("GEMINI_CLASSIFIER_MODEL") or DEFAULT_API_SPEC_MODEL
    fallback = os.getenv("GEMINI_API_SPEC_FALLBACK_MODEL") or os.getenv("GEMINI_CLASSIFIER_FALLBACK_MODEL") or FALLBACK_API_SPEC_MODEL
    candidates = [primary]
    if fallback not in candidates:
        candidates.append(fallback)
    return candidates


def _should_try_fallback_model(error: Exception, model_name: str, models: list[str]) -> bool:
    if model_name == models[-1]:
        return False

    error_text = str(error).lower()
    return any(
        marker in error_text
        for marker in (
            "not found",
            "not supported",
            "invalid model",
            "model is not",
            "404",
            "429",
            "quota",
            "resource_exhausted",
        )
    )


def _is_backend_file(file_path: str) -> bool:
    normalized_path = file_path.replace("\\", "/").lstrip("/").lower()
    return normalized_path.startswith("backend/") or _has_marker(normalized_path, ROUTE_FILE_MARKERS + DIRECT_DEPENDENCY_MARKERS)


def _has_marker(file_path: str, markers: tuple[str, ...]) -> bool:
    normalized_path = file_path.replace("\\", "/").lstrip("/").lower()
    return any(marker in normalized_path for marker in markers)


def _dedupe_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            deduped.append(value)
    return deduped


def _format_list(values: list[str]) -> str:
    return "\n".join(f"- {value}" for value in values) or "- None"


def _format_context_section(file_contexts: list[RelatedFileContext], attribute: str) -> str:
    sections: list[str] = []
    for context in file_contexts:
        value = getattr(context, attribute)
        sections.append(f"### {context.file_path}\n```text\n{value or 'Not available.'}\n```")
    return "\n\n".join(sections) or "No directly related file context available."


def _extract_response_text(response: object) -> str:
    text = getattr(response, "text", "")
    if isinstance(text, str):
        return text.strip()
    return ""
