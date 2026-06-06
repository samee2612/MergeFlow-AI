from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from backend.github_client import get_runs_root
from backend.organization import service_by_id, service_context_for_repository, team_by_id


ARTIFACT_PATHS = {
    "apiTestCases": "tests/api-spec-and-test-cases.md",
    "openapi": "tests/openapi.yaml",
    "postman": "tests/postman_collection.json",
}

IN_PROGRESS_STATUSES = frozenset(
    {"RECEIVED", "RESOLVED_SERVICE", "CLASSIFIED", "GENERATING_ARTIFACTS"}
)


def list_dashboard_runs() -> list[dict[str, Any]]:
    runs = [_summary_from_metadata(path) for path in _metadata_paths()]
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
    metadata_path = _metadata_path_for_id(run_id)
    if metadata_path is None:
        return None

    metadata = _read_json_object(metadata_path)
    run_summary = _summary_from_metadata(metadata_path)
    if run_summary is None:
        return None

    owner, repo_name, pr_number = _run_parts_from_path(metadata_path)
    repository = f"{owner}/{repo_name}"
    notion = metadata.get("notion") if isinstance(metadata.get("notion"), dict) else {}
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
            notion.get("page_url") if isinstance(notion.get("page_url"), str) else None,
            run_summary.get("status") == "SUCCESS",
        ),
        "apiOverview": metadata.get("apiOverview") if isinstance(metadata.get("apiOverview"), list) else [],
        "testCases": metadata.get("testCases") if isinstance(metadata.get("testCases"), list) else [],
    }


def _metadata_paths() -> list[Path]:
    root = get_runs_root()
    if not root.exists():
        return []
    return sorted(root.glob("*/*/*/mergeflow_run_metadata.json"), key=lambda path: path.stat().st_mtime, reverse=True)


def _metadata_path_for_id(run_id: str) -> Path | None:
    parts = run_id.split("__")
    if len(parts) != 3:
        return None
    owner, repo_name, pr_number = parts
    path = get_runs_root() / owner / repo_name / pr_number / "mergeflow_run_metadata.json"
    return path if path.exists() else None


def _summary_from_metadata(path: Path) -> dict[str, Any] | None:
    metadata = _read_json_object(path)
    if not metadata:
        return None

    owner, repo_name, pr_number = _run_parts_from_path(path)
    repository = metadata.get("repository") or f"{owner}/{repo_name}"
    status = _resolve_status(metadata)
    timestamp = metadata.get("updatedAt") or metadata.get("createdAt")
    if not isinstance(timestamp, str):
        timestamp = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()

    pr_title = metadata.get("prTitle")
    if not isinstance(pr_title, str) or not pr_title:
        pr_title = f"Merged PR #{pr_number}"

    run = enrich_run_with_service_context(
        {
            "id": metadata.get("runId") or f"{owner}__{repo_name}__{pr_number}",
            "prNumber": metadata.get("prNumber") if metadata.get("prNumber") is not None else pr_number,
            "prTitle": pr_title,
            "repository": repository,
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


def _run_parts_from_path(path: Path) -> tuple[str, str, str]:
    relative = path.relative_to(get_runs_root())
    return relative.parts[0], relative.parts[1], relative.parts[2]


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


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


def _artifact_links(repository: str, notion_url: str | None, include_repo_artifacts: bool) -> dict[str, dict[str, str]]:
    base_url = f"https://github.com/{repository}/blob/master"
    empty = {"label": "", "url": ""}
    if not include_repo_artifacts:
        return {
            "apiTestCases": empty,
            "openapi": empty,
            "postman": empty,
            "notion": empty,
        }

    return {
        "apiTestCases": {
            "label": "API Test Cases",
            "url": f"{base_url}/{ARTIFACT_PATHS['apiTestCases']}",
        },
        "openapi": {
            "label": "OpenAPI YAML",
            "url": f"{base_url}/{ARTIFACT_PATHS['openapi']}",
        },
        "postman": {
            "label": "Postman Collection",
            "url": f"{base_url}/{ARTIFACT_PATHS['postman']}",
        },
        "notion": {
            "label": "Notion Page",
            "url": notion_url or "",
        },
    }
