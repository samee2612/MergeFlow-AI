from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from backend.github_client import get_runs_root


ARTIFACT_PATHS = {
    "apiTestCases": "tests/api-spec-and-test-cases.md",
    "openapi": "tests/openapi.yaml",
    "postman": "tests/postman_collection.json",
}


def list_dashboard_runs() -> list[dict[str, Any]]:
    runs = [_summary_from_metadata(path) for path in _metadata_paths()]
    runs = [run for run in runs if run is not None]
    if not runs:
        return [SAMPLE_RUN_SUMMARY]
    return sorted(runs, key=_run_sort_key, reverse=True)


def get_dashboard_run(run_id: str) -> dict[str, Any] | None:
    metadata_path = _metadata_path_for_id(run_id)
    if metadata_path is None:
        return SAMPLE_RUN_DETAIL if run_id == SAMPLE_RUN_DETAIL["id"] else None

    metadata = _read_json_object(metadata_path)
    owner, repo_name, pr_number = _run_parts_from_path(metadata_path)
    repository = f"{owner}/{repo_name}"
    run_summary = _summary_from_metadata(metadata_path)
    if run_summary is None:
        return None

    sample = _sample_detail_for_pr(str(pr_number))
    notion = metadata.get("notion") if isinstance(metadata.get("notion"), dict) else {}
    email = metadata.get("email") if isinstance(metadata.get("email"), dict) else {}

    return {
        **sample,
        **run_summary,
        "repository": repository,
        "pipelineStatus": {
            "backendDetection": True,
            "classification": True,
            "testCaseGeneration": True,
            "openapiGeneration": True,
            "postmanGeneration": True,
            "notionUpdate": bool(notion.get("success")),
            "emailSent": bool(email.get("success", notion.get("success"))),
        },
        "artifacts": _artifact_links(repository, notion.get("page_url") if isinstance(notion.get("page_url"), str) else None),
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
    owner, repo_name, pr_number = _run_parts_from_path(path)
    metadata = _read_json_object(path)
    notion = metadata.get("notion") if isinstance(metadata.get("notion"), dict) else {}
    email = metadata.get("email") if isinstance(metadata.get("email"), dict) else {}
    succeeded = bool(notion.get("success")) and bool(email.get("success", notion.get("success")))
    timestamp = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()

    return {
        "id": f"{owner}__{repo_name}__{pr_number}",
        "prNumber": int(pr_number) if pr_number.isdigit() else pr_number,
        "prTitle": _title_for_pr(str(pr_number)),
        "repository": f"{owner}/{repo_name}",
        "status": "SUCCESS" if succeeded else "NEEDS_ATTENTION",
        "timestamp": timestamp,
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


def _artifact_links(repository: str, notion_url: str | None) -> dict[str, dict[str, str]]:
    base_url = f"https://github.com/{repository}/blob/master"
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


def _title_for_pr(pr_number: str) -> str:
    return {
        "48": "Test MergeFlow Step 7 release email (logout endpoint)",
        "47": "Test MergeFlow Step 7 release summary email",
        "46": "Test MergeFlow Notion sync (retest 2)",
    }.get(pr_number, f"Merged backend PR #{pr_number}")


def _sample_detail_for_pr(pr_number: str) -> dict[str, Any]:
    if pr_number == "48":
        return LOGOUT_RUN_DETAIL
    if pr_number == "47":
        return LOGIN_RUN_DETAIL
    return SAMPLE_RUN_DETAIL


SAMPLE_RUN_SUMMARY = {
    "id": "sample-run-42",
    "prNumber": 42,
    "prTitle": "Add Login API",
    "repository": "samee2612/mergeflow-test-repo",
    "status": "SUCCESS",
    "timestamp": "2026-06-05T23:22:00+00:00",
}


SAMPLE_RUN_DETAIL = {
    **SAMPLE_RUN_SUMMARY,
    "pipelineStatus": {
        "backendDetection": True,
        "classification": True,
        "testCaseGeneration": True,
        "openapiGeneration": True,
        "postmanGeneration": True,
        "notionUpdate": True,
        "emailSent": True,
    },
    "classification": {
        "changeTypes": ["API", "Authentication"],
        "summary": "Added login endpoint with remember_me support.",
    },
    "artifacts": _artifact_links("samee2612/mergeflow-test-repo", ""),
    "apiOverview": [
        {
            "method": "POST",
            "path": "/login",
            "requestFields": ["email", "password", "remember_me"],
            "responseCodes": [200, 400, 401],
        }
    ],
    "testCases": [
        {"name": "Valid Login", "expected": "200"},
        {"name": "Invalid Password", "expected": "401"},
        {"name": "Missing Email", "expected": "400"},
    ],
}


LOGIN_RUN_DETAIL = {
    **SAMPLE_RUN_DETAIL,
    "classification": {
        "changeTypes": ["API", "Service Logic"],
        "summary": "Added a remember_me option to the login API and service to generate longer-lived tokens.",
    },
}


LOGOUT_RUN_DETAIL = {
    **SAMPLE_RUN_DETAIL,
    "classification": {
        "changeTypes": ["API", "Authentication"],
        "summary": "Added a logout endpoint that accepts a bearer token and revokes the current demo session.",
    },
    "apiOverview": [
        {
            "method": "POST",
            "path": "/logout",
            "requestFields": ["token"],
            "responseCodes": [200, 400],
        }
    ],
    "testCases": [
        {"name": "Valid Logout", "expected": "200"},
        {"name": "Missing Token", "expected": "400"},
        {"name": "Invalid Token Body", "expected": "400"},
    ],
}
