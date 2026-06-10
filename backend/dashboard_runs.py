from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.organization import service_by_id, service_context_for_repository, team_by_id
from backend.run_store import list_run_metadata, read_run_metadata_by_id, run_id_for

IN_PROGRESS_STATUSES = frozenset(
    {"RECEIVED", "RESOLVED_SERVICE", "CLASSIFIED", "GENERATING_ARTIFACTS"}
)


def list_dashboard_runs() -> list[dict[str, Any]]:
    runs = [_summary_from_metadata(metadata) for metadata in list_run_metadata()]
    return sorted([run for run in runs if run is not None], key=_run_sort_key, reverse=True)


def list_dashboard_runs_for_service(service_id: str) -> list[dict[str, Any]]:
    service = service_by_id(service_id)
    if service is None:
        return []

    repository = service["repository"]
    return [run for run in list_dashboard_runs() if run.get("repository") == repository]


def list_dashboard_runs_for_team(team_id: str) -> list[dict[str, Any]]:
    team = team_by_id(team_id)
    if team is None:
        return []

    service_ids = {service["id"] for service in team["services"]}
    return [run for run in list_dashboard_runs() if run.get("serviceId") in service_ids]


def get_dashboard_run(run_id: str) -> dict[str, Any] | None:
    metadata = read_run_metadata_by_id(run_id)
    if not metadata:
        return None

    run_summary = _summary_from_metadata(metadata)
    if run_summary is None:
        return None

    repository = run_summary.get("repository")
    if not isinstance(repository, str):
        return None

    notion = metadata.get("notion") if isinstance(metadata.get("notion"), dict) else {}
    notion_documentation = (
        metadata.get("notionDocumentation") if isinstance(metadata.get("notionDocumentation"), dict) else {}
    )
    email = metadata.get("email") if isinstance(metadata.get("email"), dict) else {}
    classification = metadata.get("classification") if isinstance(metadata.get("classification"), dict) else {}
    pipeline_status = _pipeline_status_from_metadata(metadata, run_summary.get("status", ""))

    return {
        **run_summary,
        "repository": repository,
        "pipelineStatus": pipeline_status,
        "classification": {
            "changeTypes": classification.get("changeTypes") or [],
            "summary": classification.get("summary") or "",
        },
        "artifacts": _artifact_links(
            repository,
            run_summary.get("prNumber"),
            notion,
            notion_documentation,
            email,
            run_summary.get("status") in {"SUCCESS", "NEEDS_ATTENTION", "RUNNING"},
        ),
        "apiOverview": metadata.get("apiOverview") if isinstance(metadata.get("apiOverview"), list) else [],
        "testCases": metadata.get("testCases") if isinstance(metadata.get("testCases"), list) else [],
    }


def _summary_from_metadata(metadata: dict[str, Any]) -> dict[str, Any] | None:
    if not metadata:
        return None

    repository = metadata.get("repository")
    if not isinstance(repository, str) or not repository:
        return None

    run_id = metadata.get("runId")
    if not isinstance(run_id, str) or not run_id:
        run_id = run_id_for(repository, metadata.get("prNumber") if isinstance(metadata.get("prNumber"), int) else None)

    status = _resolve_status(metadata)
    timestamp = metadata.get("updatedAt") or metadata.get("createdAt")
    if not isinstance(timestamp, str):
        timestamp = datetime.now(timezone.utc).isoformat()

    pr_title = metadata.get("prTitle")
    if not isinstance(pr_title, str) or not pr_title:
        pr_number = metadata.get("prNumber")
        pr_title = f"Merged PR #{pr_number}" if pr_number is not None else "Merged PR"

    run = enrich_run_with_service_context(
        {
            "id": run_id,
            "prNumber": metadata.get("prNumber"),
            "prTitle": pr_title,
            "repository": repository,
            "author": metadata.get("author"),
            "headBranch": metadata.get("headBranch"),
            "baseBranch": metadata.get("baseBranch"),
            "status": status,
            "timestamp": timestamp,
            "changeScope": metadata.get("changeScope"),
            "action": metadata.get("action"),
        }
    )
    return run


def _resolve_status(metadata: dict[str, Any]) -> str:
    status = metadata.get("status")
    if isinstance(status, str) and status:
        if status in IN_PROGRESS_STATUSES:
            return "RUNNING"
        if status == "TRACKED_ONLY":
            return "TRACKED_ONLY"
        if status == "FAILED":
            return "FAILED"
        if status == "IGNORED":
            return "IGNORED"

        notion = metadata.get("notion") if isinstance(metadata.get("notion"), dict) else {}
        email = metadata.get("email") if isinstance(metadata.get("email"), dict) else {}
        if status == "SUCCESS":
            artifacts_ok = bool(notion.get("success")) and bool(email.get("success", notion.get("success")))
            return "SUCCESS" if artifacts_ok else "NEEDS_ATTENTION"
        return status

    notion = metadata.get("notion") if isinstance(metadata.get("notion"), dict) else {}
    email = metadata.get("email") if isinstance(metadata.get("email"), dict) else {}
    succeeded = bool(notion.get("success")) and bool(email.get("success", notion.get("success")))
    return "SUCCESS" if succeeded else "NEEDS_ATTENTION"


def _pipeline_status_from_metadata(metadata: dict[str, Any], display_status: str) -> dict[str, bool]:
    if display_status == "TRACKED_ONLY":
        return {
            "backendDetection": True,
            "classification": True,
            "testCaseGeneration": False,
            "openapiGeneration": False,
            "postmanGeneration": False,
            "notionUpdate": False,
            "emailSent": False,
        }

    notion = metadata.get("notion") if isinstance(metadata.get("notion"), dict) else {}
    email = metadata.get("email") if isinstance(metadata.get("email"), dict) else {}
    has_artifacts = display_status in {"SUCCESS", "NEEDS_ATTENTION", "RUNNING"}

    return {
        "backendDetection": has_artifacts or display_status == "FAILED",
        "classification": has_artifacts or display_status == "FAILED",
        "testCaseGeneration": has_artifacts,
        "openapiGeneration": has_artifacts,
        "postmanGeneration": has_artifacts,
        "notionUpdate": bool(notion.get("success")),
        "emailSent": bool(email.get("success", notion.get("success"))),
    }


def _run_sort_key(run: dict[str, Any]) -> tuple[int, str]:
    pr_number = run.get("prNumber")
    numeric_pr = pr_number if isinstance(pr_number, int) else 0
    return numeric_pr, str(run.get("timestamp", ""))


def enrich_run_with_service_context(run: dict[str, Any]) -> dict[str, Any]:
    service_context = run.get("serviceContext")
    if isinstance(service_context, dict):
        return {
            **run,
            "teamId": service_context.get("teamId", "unmapped"),
            "teamName": service_context.get("teamName", "Unmapped Repository"),
            "serviceId": service_context.get("serviceId", "unmapped"),
            "serviceName": service_context.get("serviceName", "Unknown Service"),
        }

    repository = run.get("repository")
    if not isinstance(repository, str):
        return run

    mapped = service_context_for_repository(repository)
    if mapped is None:
        return {
            **run,
            "teamId": "unmapped",
            "teamName": "Unmapped Repository",
            "serviceId": "unmapped",
            "serviceName": repository.split("/")[-1],
        }

    return {**run, **mapped}


def _artifact_links(
    repository: str,
    pr_number: Any,
    notion: dict[str, Any],
    notion_documentation: dict[str, Any],
    email: dict[str, Any],
    include_artifacts: bool,
) -> dict[str, dict[str, str]]:
    empty = {"label": "", "url": ""}
    if not include_artifacts:
        return {
            "notionServicePage": empty,
            "notionPrReview": empty,
            "githubPullRequest": empty,
            "emailSummary": empty,
        }

    service_page_url = _first_string(
        notion_documentation.get("servicePageUrl"),
        notion.get("service_page_url"),
    )
    pr_review_url = _first_string(
        notion_documentation.get("prReviewPageUrl"),
        notion.get("page_url"),
    )
    github_pr_url = ""
    if isinstance(pr_number, int):
        github_pr_url = f"https://github.com/{repository}/pull/{pr_number}"

    email_recipients = email.get("recipients")
    email_label = "Release Email Sent"
    if isinstance(email_recipients, list) and email_recipients:
        email_label = f"Release Email ({len(email_recipients)} recipient{'s' if len(email_recipients) != 1 else ''})"

    return {
        "notionServicePage": {
            "label": "Notion Service Page",
            "url": service_page_url or "",
        },
        "notionPrReview": {
            "label": "Notion PR Documentation",
            "url": pr_review_url or "",
        },
        "githubPullRequest": {
            "label": "GitHub Pull Request",
            "url": github_pr_url,
        },
        "emailSummary": {
            "label": email_label,
            "url": "",
        },
    }


def _first_string(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""
