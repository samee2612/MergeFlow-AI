from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Protocol

from loguru import logger

from backend.github_client import get_runs_root


class RunContext(Protocol):
    repository: str
    pr_number: int | None
    title: str
    author: str
    merged_at: str | None


RUN_STATUSES = frozenset(
    {
        "RECEIVED",
        "RESOLVED_SERVICE",
        "CLASSIFIED",
        "GENERATING_ARTIFACTS",
        "SUCCESS",
        "TRACKED_ONLY",
        "IGNORED",
        "FAILED",
        "NEEDS_ATTENTION",
    }
)


def run_id_for(repository: str, pr_number: int | None) -> str:
    owner, repo_name = _repository_parts(repository)
    pr_part = str(pr_number) if pr_number is not None else "unknown-pr"
    return f"{owner}__{repo_name}__{pr_part}"


def build_run_metadata_path(pr_context: RunContext) -> Path:
    repo_parts = [part for part in pr_context.repository.split("/") if part]
    pr_part = str(pr_context.pr_number) if pr_context.pr_number is not None else "unknown-pr"
    return get_runs_root().joinpath(*repo_parts, pr_part, "mergeflow_run_metadata.json")


def create_run(pr_context: RunContext) -> str:
    metadata_path = build_run_metadata_path(pr_context)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    now = _utc_now()
    run_id = run_id_for(pr_context.repository, pr_context.pr_number)

    payload = {
        "runId": run_id,
        "repository": pr_context.repository,
        "prNumber": pr_context.pr_number,
        "prTitle": pr_context.title,
        "author": pr_context.author,
        "mergedAt": pr_context.merged_at,
        "status": "RECEIVED",
        "createdAt": now,
        "updatedAt": now,
    }
    _write_metadata(metadata_path, payload)
    logger.info(
        "Created MergeFlow run run_id={run_id} repo={repo} pr_number={pr_number}",
        run_id=run_id,
        repo=pr_context.repository,
        pr_number=pr_context.pr_number,
    )
    return run_id


def update_run(pr_context: RunContext, **fields: Any) -> None:
    metadata_path = build_run_metadata_path(pr_context)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    payload = _read_json_object(metadata_path)
    if not payload:
        payload = {
            "runId": run_id_for(pr_context.repository, pr_context.pr_number),
            "repository": pr_context.repository,
            "prNumber": pr_context.pr_number,
            "prTitle": pr_context.title,
            "author": pr_context.author,
            "mergedAt": pr_context.merged_at,
            "createdAt": _utc_now(),
        }

    status = fields.get("status")
    if status is not None and status not in RUN_STATUSES:
        raise ValueError(f"Invalid run status: {status}")

    payload.update(fields)
    payload["updatedAt"] = _utc_now()
    _write_metadata(metadata_path, payload)


def read_run_metadata(repository: str, pr_number: int) -> dict[str, Any]:
    owner, repo_name = _repository_parts(repository)
    metadata_path = get_runs_root() / owner / repo_name / str(pr_number) / "mergeflow_run_metadata.json"
    return _read_json_object(metadata_path)


def _repository_parts(repository: str) -> tuple[str, str]:
    parts = repository.split("/", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid repository name: {repository}")
    return parts[0], parts[1]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_metadata(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
