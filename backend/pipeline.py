from __future__ import annotations

from dataclasses import dataclass

from loguru import logger

from backend.classifier.diff_classifier import BackendDiffClassification, classify_backend_diff
from backend.classifier.scope_classifier import classify_change_scope
from backend.generators.api_spec_generator import generate_api_spec_and_test_cases
from backend.generators.email_generator import generate_and_send_release_email
from backend.generators.notion_draft_generator import NotionDocumentationResult, update_notion_documentation
from backend.generators.openapi_generator import generate_openapi_yaml
from backend.generators.postman_generator import generate_postman_collection
from backend.github_client import fetch_pull_request_diff
from backend.run_store import create_run, update_run
from backend.service_resolver import ServiceResolution, resolve_service


@dataclass(frozen=True)
class PullRequestContext:
    repository: str
    pr_number: int | None
    title: str
    merged_at: str | None
    author: str
    changed_files: list[str]
    base_branch: str = ""
    head_branch: str = ""
    default_branch: str = ""


async def run_post_merge_pipeline(pr_context: PullRequestContext) -> bool:
    """Process a merged PR: resolve service, classify scope, automate or track."""
    logger.info(
        "Post-merge pipeline received repo={repo} pr_number={pr_number} title={title} "
        "merged_at={merged_at} author={author} changed_files={changed_files}",
        repo=pr_context.repository,
        pr_number=pr_context.pr_number,
        title=pr_context.title,
        merged_at=pr_context.merged_at,
        author=pr_context.author,
        changed_files=pr_context.changed_files,
    )

    create_run(pr_context)

    try:
        service = resolve_service(
            pr_context.repository,
            pr_title=pr_context.title,
            changed_files=pr_context.changed_files,
        )
        update_run(
            pr_context,
            status="RESOLVED_SERVICE",
            serviceContext=service.as_dict(),
            **service.as_dict(),
        )

        scope = classify_change_scope(
            pr_context.changed_files,
            pr_context.title,
            pr_context.repository,
        )
        update_run(
            pr_context,
            status="CLASSIFIED",
            changeScope=scope.scope,
            action=scope.action,
            classification={
                "changeTypes": scope.change_types,
                "summary": scope.summary,
            },
        )

        if scope.action == "track_only":
            logger.info(
                "PR tracked without full automation repo={repo} pr_number={pr_number} scope={scope}",
                repo=pr_context.repository,
                pr_number=pr_context.pr_number,
                scope=scope.scope,
            )
            update_run(pr_context, status="TRACKED_ONLY")
            return True

        update_run(pr_context, status="GENERATING_ARTIFACTS")
        classification = await classify_accepted_backend_pr(pr_context, service)
        update_run(
            pr_context,
            status="SUCCESS",
            classification={
                "changeTypes": classification.change_types,
                "summary": classification.summary,
            },
        )
        return True
    except Exception as error:
        logger.exception(
            "Post-merge pipeline failed repo={repo} pr_number={pr_number} error={error}",
            repo=pr_context.repository,
            pr_number=pr_context.pr_number,
            error=str(error),
        )
        update_run(pr_context, status="FAILED", errorMessage=str(error))
        return False


async def classify_accepted_backend_pr(
    pr_context: PullRequestContext,
    service: ServiceResolution,
) -> BackendDiffClassification:
    if pr_context.pr_number is None:
        logger.warning("Skipping PR classification because PR number is missing")
        return BackendDiffClassification(
            change_types=["Unknown"],
            summary="Unable to classify backend change.",
        )

    diff_text = await fetch_pull_request_diff(pr_context.repository, pr_context.pr_number)
    classification = classify_backend_diff(diff_text, pr_context.changed_files)
    log_pr_classification(classification)
    api_spec_result = await generate_api_spec_and_test_cases(pr_context, classification, diff_text)
    openapi_result = await generate_openapi_yaml(
        pr_context,
        classification,
        api_spec_result.markdown,
        api_spec_result.target_branch,
    )
    postman_result = await generate_postman_collection(
        pr_context,
        openapi_result.yaml_content,
        openapi_result.target_branch,
    )
    notion_result = await update_notion_documentation(
        pr_context,
        service,
        classification,
        api_spec_result,
        openapi_result,
        postman_result,
    )
    await generate_and_send_release_email(
        pr_context,
        classification,
        api_spec_result,
        openapi_result,
        postman_result,
        notion_result,
    )
    return classification


def log_pr_classification(classification: BackendDiffClassification) -> None:
    change_types = "\n".join(f"* {change_type}" for change_type in classification.change_types)
    logger.info(
        "PR Classification:\n\n{change_types}\n\nSummary:\n{summary}",
        change_types=change_types,
        summary=classification.summary,
    )


def is_backend_relevant_pr(changed_files: list[str]) -> bool:
    scope = classify_change_scope(changed_files)
    return scope.action == "generate_api_artifacts"
