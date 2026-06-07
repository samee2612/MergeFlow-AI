from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Protocol

from loguru import logger

from backend.github_client import get_runs_root

try:
    import redis
except ImportError:  # pragma: no cover - optional at import time
    redis = None  # type: ignore[assignment]


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

REDIS_RUN_KEY_PREFIX = "mergeflow:run:"
REDIS_RUN_INDEX_KEY = "mergeflow:run:index"


def run_id_for(repository: str, pr_number: int | None) -> str:
    owner, repo_name = _repository_parts(repository)
    pr_part = str(pr_number) if pr_number is not None else "unknown-pr"
    return f"{owner}__{repo_name}__{pr_part}"


def build_run_metadata_path(pr_context: RunContext) -> Path:
    repo_parts = [part for part in pr_context.repository.split("/") if part]
    pr_part = str(pr_context.pr_number) if pr_context.pr_number is not None else "unknown-pr"
    return get_runs_root().joinpath(*repo_parts, pr_part, "mergeflow_run_metadata.json")


def create_run(pr_context: RunContext) -> str:
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
    _write_run_payload(run_id, payload)
    logger.info(
        "Created MergeFlow run run_id={run_id} repo={repo} pr_number={pr_number} backend={backend}",
        run_id=run_id,
        repo=pr_context.repository,
        pr_number=pr_context.pr_number,
        backend=_runs_backend_name(),
    )
    return run_id


def update_run(pr_context: RunContext, **fields: Any) -> None:
    run_id = run_id_for(pr_context.repository, pr_context.pr_number)
    payload = read_run_metadata_by_id(run_id)
    if not payload:
        payload = {
            "runId": run_id,
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
    _write_run_payload(run_id, payload)


def patch_run_metadata(pr_context: RunContext, patch: dict[str, Any]) -> None:
    update_run(pr_context, **patch)


def read_run_metadata(repository: str, pr_number: int) -> dict[str, Any]:
    return read_run_metadata_by_id(run_id_for(repository, pr_number))


def read_run_metadata_by_id(run_id: str) -> dict[str, Any]:
    backend = _get_runs_backend()
    payload = backend.read(run_id)
    if payload:
        return payload

    if isinstance(backend, RedisRunsBackend):
        filesystem_payload = FileSystemRunsBackend().read(run_id)
        if filesystem_payload:
            return filesystem_payload

    return {}


def list_run_metadata() -> list[dict[str, Any]]:
    backend = _get_runs_backend()
    payloads = backend.list_all()
    if payloads:
        return payloads

    if isinstance(backend, RedisRunsBackend):
        return FileSystemRunsBackend().list_all()

    return payloads


def _write_run_payload(run_id: str, payload: dict[str, Any]) -> None:
    backend = _get_runs_backend()
    backend.write(run_id, payload)
    if isinstance(backend, RedisRunsBackend):
        FileSystemRunsBackend().write(run_id, payload)


def _runs_backend_name() -> str:
    return "redis" if _use_redis_runs_backend() else "filesystem"


def _use_redis_runs_backend() -> bool:
    backend = os.getenv("MERGEFLOW_RUNS_BACKEND", "filesystem").strip().lower()
    if backend == "redis":
        return bool(_redis_url())
    return False


def _redis_url() -> str:
    return (
        os.getenv("REDIS_URL", "").strip()
        or os.getenv("CELERY_BROKER_URL", "").strip()
    )


class RunsBackend(Protocol):
    def read(self, run_id: str) -> dict[str, Any]:
        ...

    def write(self, run_id: str, payload: dict[str, Any]) -> None:
        ...

    def list_all(self) -> list[dict[str, Any]]:
        ...


class FileSystemRunsBackend:
    def read(self, run_id: str) -> dict[str, Any]:
        path = _metadata_path_for_id(run_id)
        if path is None:
            return {}
        return _read_json_object(path)

    def write(self, run_id: str, payload: dict[str, Any]) -> None:
        path = _metadata_path_for_id(run_id)
        if path is None:
            owner, repo_name, pr_number = run_id.split("__", 2)
            path = get_runs_root() / owner / repo_name / pr_number / "mergeflow_run_metadata.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_metadata(path, payload)

    def list_all(self) -> list[dict[str, Any]]:
        root = get_runs_root()
        if not root.exists():
            return []

        payloads: list[dict[str, Any]] = []
        for path in sorted(
            root.glob("*/*/*/mergeflow_run_metadata.json"),
            key=lambda metadata_path: metadata_path.stat().st_mtime,
            reverse=True,
        ):
            payload = _read_json_object(path)
            if payload:
                payloads.append(payload)
        return payloads


class RedisRunsBackend:
    def __init__(self, redis_url: str) -> None:
        if redis is None:
            raise RuntimeError("redis package is required for MERGEFLOW_RUNS_BACKEND=redis")
        self._client = redis.Redis.from_url(redis_url, decode_responses=True)

    def read(self, run_id: str) -> dict[str, Any]:
        raw = self._client.get(f"{REDIS_RUN_KEY_PREFIX}{run_id}")
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def write(self, run_id: str, payload: dict[str, Any]) -> None:
        serialized = json.dumps(payload, indent=2, sort_keys=True)
        self._client.set(f"{REDIS_RUN_KEY_PREFIX}{run_id}", serialized)
        timestamp = _timestamp_score(payload.get("updatedAt") or payload.get("createdAt"))
        self._client.zadd(REDIS_RUN_INDEX_KEY, {run_id: timestamp})

    def list_all(self) -> list[dict[str, Any]]:
        run_ids = self._client.zrevrange(REDIS_RUN_INDEX_KEY, 0, -1)
        payloads: list[dict[str, Any]] = []
        for run_id in run_ids:
            payload = self.read(run_id)
            if payload:
                payloads.append(payload)
        return payloads


def _get_runs_backend() -> RunsBackend:
    if _use_redis_runs_backend():
        return RedisRunsBackend(_redis_url())
    return FileSystemRunsBackend()


def _metadata_path_for_id(run_id: str) -> Path | None:
    parts = run_id.split("__")
    if len(parts) != 3:
        return None
    owner, repo_name, pr_number = parts
    return get_runs_root() / owner / repo_name / pr_number / "mergeflow_run_metadata.json"


def _repository_parts(repository: str) -> tuple[str, str]:
    parts = repository.split("/", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid repository name: {repository}")
    return parts[0], parts[1]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _timestamp_score(timestamp: Any) -> float:
    if isinstance(timestamp, str):
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            return parsed.timestamp()
        except ValueError:
            pass
    return datetime.now(timezone.utc).timestamp()


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
