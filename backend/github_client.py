from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from loguru import logger

GITHUB_API_BASE_URL = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"
DEFAULT_RUNS_ROOT = Path("/tmp/mergeflow-runs")

PERMISSION_DEBUG_HEADERS = (
    "x-oauth-scopes",
    "x-accepted-oauth-scopes",
    "github-authentication-token-type",
    "x-github-authentication-token-type",
    "x-accepted-github-permissions",
    "x-github-media-type",
)


@dataclass(frozen=True)
class RepositoryIdentity:
    full_name: str
    owner: str
    name: str


@dataclass(frozen=True)
class GitHubCommitResult:
    success: bool
    repository: str
    branch: str
    file_path: str
    destination: str
    error_message: str | None = None
    local_backup_path: str | None = None


@dataclass(frozen=True)
class GitHubDeleteResult:
    success: bool
    repository: str
    branch: str
    file_path: str
    deleted: bool
    error_message: str | None = None


async def fetch_pull_request_changed_files(repository: str, pr_number: int) -> list[str]:
    changed_files: list[str] = []
    page = 1

    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            response = await client.get(
                f"{GITHUB_API_BASE_URL}/repos/{repository}/pulls/{pr_number}/files",
                headers=github_json_headers(),
                params={"per_page": 100, "page": page},
            )
            response.raise_for_status()
            files_page = response.json()
            if not isinstance(files_page, list) or not files_page:
                break

            changed_files.extend(
                file_item["filename"]
                for file_item in files_page
                if isinstance(file_item, dict) and isinstance(file_item.get("filename"), str)
            )

            if len(files_page) < 100:
                break
            page += 1

    logger.info(
        "Fetched GitHub PR changed files repo={repo} pr_number={pr_number} changed_files={changed_files}",
        repo=repository,
        pr_number=pr_number,
        changed_files=changed_files,
    )
    return changed_files


async def fetch_pull_request_diff(repository: str, pr_number: int) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{GITHUB_API_BASE_URL}/repos/{repository}/pulls/{pr_number}",
            headers=github_diff_headers(),
        )
        response.raise_for_status()

    diff_text = response.text
    logger.info(
        "Fetched GitHub PR diff repo={repo} pr_number={pr_number} diff_char_count={diff_char_count}",
        repo=repository,
        pr_number=pr_number,
        diff_char_count=len(diff_text),
    )
    return diff_text


async def fetch_repository_file_text(repository: str, file_path: str, ref: str | None = None) -> str:
    params = {"ref": ref} if ref else None
    encoded_path = quote(file_path, safe="/")

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{GITHUB_API_BASE_URL}/repos/{repository}/contents/{encoded_path}",
            headers=github_json_headers(),
            params=params,
        )
        response.raise_for_status()

    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError(f"GitHub contents response was not an object for {file_path}")

    encoded_content = payload.get("content")
    encoding = payload.get("encoding")
    if not isinstance(encoded_content, str) or encoding != "base64":
        raise ValueError(f"GitHub contents response did not include base64 content for {file_path}")

    logger.info("Fetched GitHub file content repo={repo} file_path={file_path}", repo=repository, file_path=file_path)
    return base64.b64decode(encoded_content).decode("utf-8")


async def fetch_repository_default_branch(repository: str) -> str:
    repo_payload, _ = await _fetch_repository_payload(repository)
    default_branch = repo_payload.get("default_branch")
    if isinstance(default_branch, str) and default_branch:
        return default_branch

    raise ValueError(f"GitHub repository response did not include default_branch for {repository}")


async def branch_exists(repository: str, branch: str) -> bool:
    if not branch:
        return False

    encoded_branch = quote(branch, safe="")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{GITHUB_API_BASE_URL}/repos/{repository}/branches/{encoded_branch}",
            headers=github_json_headers(),
        )

    if response.status_code == 404:
        return False

    response.raise_for_status()
    return True


async def resolve_commit_branch(repository: str, branch_candidates: list[str]) -> str:
    seen_branches: set[str] = set()
    for branch in branch_candidates:
        if not branch or branch in seen_branches:
            continue
        seen_branches.add(branch)
        if await branch_exists(repository, branch):
            logger.info("Resolved target commit branch repo={repo} branch={branch}", repo=repository, branch=branch)
            return branch

    default_branch = await fetch_repository_default_branch(repository)
    if default_branch not in seen_branches and await branch_exists(repository, default_branch):
        logger.info(
            "Resolved target commit branch from repository default repo={repo} branch={branch}",
            repo=repository,
            branch=default_branch,
        )
        return default_branch

    raise ValueError(
        f"Could not resolve a valid target branch for {repository}. "
        f"Tried branches: {', '.join(sorted(seen_branches)) or 'none'}"
    )


async def commit_repository_file_text(
    repository: str,
    branch: str,
    file_path: str,
    content: str,
    commit_message: str,
    pr_number: int | None = None,
) -> GitHubCommitResult:
    repo_identity = parse_repository_identity(repository)
    if not branch:
        branch = await fetch_repository_default_branch(repository)

    await log_commit_preflight(
        repository=repository,
        branch=branch,
        file_path=file_path,
        pr_number=pr_number,
    )

    permission_error = await verify_contents_write_access(repository)
    if permission_error:
        backup_path = write_local_artifact_backup(repository, pr_number, file_path, content)
        logger.error(
            "Skipping GitHub commit because token lacks required access repo={repo} branch={branch} path={path} "
            "local_backup_path={local_backup_path} reason={reason}",
            repo=repository,
            branch=branch,
            path=file_path,
            local_backup_path=backup_path,
            reason=permission_error,
        )
        return GitHubCommitResult(
            success=False,
            repository=repository,
            branch=branch,
            file_path=file_path,
            destination=file_path,
            error_message=permission_error,
            local_backup_path=backup_path,
        )

    encoded_path = quote(file_path, safe="/")
    existing_sha = await _fetch_repository_file_sha(repository, file_path, branch)
    payload = {
        "message": commit_message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": branch,
    }
    if existing_sha:
        payload["sha"] = existing_sha

    request_url = f"{GITHUB_API_BASE_URL}/repos/{repository}/contents/{encoded_path}"
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.put(
            request_url,
            headers=github_json_headers(),
            json=payload,
        )

    if response.is_error:
        log_github_response_debug(
            response,
            context=(
                f"GitHub contents commit failed for {repo_identity.full_name} "
                f"(owner={repo_identity.owner}, name={repo_identity.name}) "
                f"branch={branch} path={file_path}"
            ),
            request_url=request_url,
            request_method="PUT",
        )
        error_message = build_commit_failure_message(
            repository=repository,
            branch=branch,
            file_path=file_path,
            status_code=response.status_code,
            response_body=response.text,
        )
        backup_path = write_local_artifact_backup(repository, pr_number, file_path, content)
        logger.error(
            "GitHub commit failed repo={repo} branch={branch} path={path} local_backup_path={local_backup_path} "
            "error={error}",
            repo=repository,
            branch=branch,
            path=file_path,
            local_backup_path=backup_path,
            error=error_message,
        )
        return GitHubCommitResult(
            success=False,
            repository=repository,
            branch=branch,
            file_path=file_path,
            destination=file_path,
            error_message=error_message,
            local_backup_path=backup_path,
        )

    response_payload = response.json()
    content_payload = response_payload.get("content") if isinstance(response_payload, dict) else None
    html_url = content_payload.get("html_url") if isinstance(content_payload, dict) else ""
    destination = str(html_url or file_path)
    logger.info(
        "Committed file to target GitHub repo repo={repo} owner={owner} name={name} branch={branch} path={path} "
        "destination={destination}",
        repo=repository,
        owner=repo_identity.owner,
        name=repo_identity.name,
        branch=branch,
        path=file_path,
        destination=destination,
    )
    return GitHubCommitResult(
        success=True,
        repository=repository,
        branch=branch,
        file_path=file_path,
        destination=destination,
    )


async def delete_repository_file(
    repository: str,
    branch: str,
    file_path: str,
    commit_message: str,
    pr_number: int | None = None,
) -> GitHubDeleteResult:
    if not branch:
        branch = await fetch_repository_default_branch(repository)

    await log_commit_preflight(
        repository=repository,
        branch=branch,
        file_path=file_path,
        pr_number=pr_number,
    )

    permission_error = await verify_contents_write_access(repository)
    if permission_error:
        logger.error(
            "Skipping GitHub delete because token lacks required access repo={repo} branch={branch} path={path} reason={reason}",
            repo=repository,
            branch=branch,
            path=file_path,
            reason=permission_error,
        )
        return GitHubDeleteResult(
            success=False,
            repository=repository,
            branch=branch,
            file_path=file_path,
            deleted=False,
            error_message=permission_error,
        )

    existing_sha = await _fetch_repository_file_sha(repository, file_path, branch)
    if not existing_sha:
        logger.info(
            "No GitHub file cleanup needed repo={repo} branch={branch} path={path}",
            repo=repository,
            branch=branch,
            path=file_path,
        )
        return GitHubDeleteResult(
            success=True,
            repository=repository,
            branch=branch,
            file_path=file_path,
            deleted=False,
        )

    encoded_path = quote(file_path, safe="/")
    request_url = f"{GITHUB_API_BASE_URL}/repos/{repository}/contents/{encoded_path}"
    payload = {
        "message": commit_message,
        "sha": existing_sha,
        "branch": branch,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.delete(
            request_url,
            headers=github_json_headers(),
            json=payload,
        )

    if response.is_error:
        log_github_response_debug(
            response,
            context=f"GitHub contents delete failed for {repository} branch={branch} path={file_path}",
            request_url=request_url,
            request_method="DELETE",
        )
        error_message = (
            f"GitHub delete from {repository} failed with status {response.status_code} "
            f"for branch {branch} and path {file_path}. Response body: {response.text}"
        )
        return GitHubDeleteResult(
            success=False,
            repository=repository,
            branch=branch,
            file_path=file_path,
            deleted=False,
            error_message=error_message,
        )

    logger.info(
        "Deleted temporary API analysis artifact repo={repo} branch={branch} path={path}",
        repo=repository,
        branch=branch,
        path=file_path,
    )
    return GitHubDeleteResult(
        success=True,
        repository=repository,
        branch=branch,
        file_path=file_path,
        deleted=True,
    )


async def log_commit_preflight(
    repository: str,
    branch: str,
    file_path: str,
    pr_number: int | None,
) -> None:
    repo_identity = parse_repository_identity(repository)
    token_present = bool(_github_token())

    logger.info(
        "GitHub commit preflight repo={repo} owner={owner} name={name} pr_number={pr_number} branch={branch} "
        "path={path} token_present={token_present}",
        repo=repository,
        owner=repo_identity.owner,
        name=repo_identity.name,
        pr_number=pr_number,
        branch=branch,
        path=file_path,
        token_present=token_present,
    )

    if not token_present:
        logger.error("GITHUB_TOKEN is not configured; cannot commit to target repository")
        return

    await _log_token_identity()
    await _log_repository_access(repository, branch)


async def verify_contents_write_access(repository: str) -> str | None:
    if not _github_token():
        return "GITHUB_TOKEN is not configured."

    try:
        repo_payload, repo_response = await _fetch_repository_payload(repository)
    except httpx.HTTPStatusError as error:
        log_github_response_debug(
            error.response,
            context=f"Repository access check failed for {repository}",
            request_url=str(error.request.url) if error.request else None,
            request_method=error.request.method if error.request else None,
        )
        if error.response.status_code == 404:
            return (
                f"Commit requires Contents: write access to {repository}. "
                "The configured token cannot read this repository. "
                "Authorize the token for this repo (fine-grained PAT) or grant the `repo` scope (classic PAT)."
            )
        return (
            f"Commit requires Contents: write access to {repository}. "
            f"GitHub repository access check failed with status {error.response.status_code}."
        )

    permissions = repo_payload.get("permissions", {})
    repo_permissions = permissions if isinstance(permissions, dict) else {}
    can_push = bool(repo_permissions.get("push"))
    can_admin = bool(repo_permissions.get("admin"))

    oauth_scopes = repo_response.headers.get("x-oauth-scopes", "")
    token_type = _token_type_from_headers(repo_response.headers)

    logger.info(
        "GitHub repository permissions repo={repo} token_type={token_type} oauth_scopes={oauth_scopes} "
        "permissions={permissions}",
        repo=repository,
        token_type=token_type,
        oauth_scopes=oauth_scopes or "none",
        permissions=repo_permissions,
    )

    if can_push or can_admin:
        return None

    if token_type == "fine-grained" or "fine-grained" in token_type.lower():
        return (
            f"Commit requires Contents: write access to {repository}. "
            "The configured fine-grained token does not have push/admin permission on this repository. "
            "Update the token repository permissions to include Contents: Read and write."
        )

    if oauth_scopes and not _classic_token_has_repo_scope(oauth_scopes):
        return (
            f"Commit requires Contents: write access to {repository}. "
            "The configured classic token is missing the `repo` scope required to commit files."
        )

    return (
        f"Commit requires Contents: write access to {repository}. "
        "GitHub did not report push/admin permission for this token on the target repository."
    )


def parse_repository_identity(repository: str) -> RepositoryIdentity:
    parts = repository.split("/", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"Invalid GitHub repository name: {repository}")

    return RepositoryIdentity(full_name=repository, owner=parts[0], name=parts[1])


def build_commit_failure_message(
    repository: str,
    branch: str,
    file_path: str,
    status_code: int,
    response_body: str,
) -> str:
    if status_code == 404:
        return (
            f"Commit requires Contents: write access to {repository} on branch {branch} "
            f"for path {file_path}. GitHub returned 404, which often means the token cannot write to this "
            f"repository or branch. Response body: {response_body}"
        )

    return (
        f"GitHub commit to {repository} failed with status {status_code} for branch {branch} "
        f"and path {file_path}. Response body: {response_body}"
    )


def write_local_artifact_backup(
    repository: str,
    pr_number: int | None,
    file_path: str,
    content: str,
) -> str:
    repo_parts = [part for part in repository.split("/") if part]
    pr_part = str(pr_number) if pr_number is not None else "unknown-pr"
    backup_path = get_runs_root().joinpath(*repo_parts, pr_part, file_path)
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path.write_text(content.rstrip() + "\n", encoding="utf-8")
    logger.info(
        "Saved local artifact backup because GitHub commit failed repo={repo} path={path} local_backup_path={local_backup_path}",
        repo=repository,
        path=file_path,
        local_backup_path=str(backup_path),
    )
    return str(backup_path)


def get_runs_root() -> Path:
    return Path(os.getenv("MERGEFLOW_RUNS_DIR", str(DEFAULT_RUNS_ROOT)))


async def _fetch_repository_payload(repository: str) -> tuple[dict[str, Any], httpx.Response]:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{GITHUB_API_BASE_URL}/repos/{repository}",
            headers=github_json_headers(),
        )
        response.raise_for_status()

    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError(f"GitHub repository response was not an object for {repository}")

    return payload, response


async def _log_token_identity() -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{GITHUB_API_BASE_URL}/user",
            headers=github_json_headers(),
        )

    if response.is_error:
        log_github_response_debug(
            response,
            context="GitHub token identity check failed",
            request_url=f"{GITHUB_API_BASE_URL}/user",
            request_method="GET",
        )
        return

    payload = response.json()
    login = payload.get("login") if isinstance(payload, dict) else "unknown"
    token_type = _token_type_from_headers(response.headers)
    oauth_scopes = response.headers.get("x-oauth-scopes", "")

    logger.info(
        "GitHub token identity login={login} token_type={token_type} oauth_scopes={oauth_scopes}",
        login=login,
        token_type=token_type,
        oauth_scopes=oauth_scopes or "none",
    )
    log_permission_headers(response, "GitHub token identity headers")


async def _log_repository_access(repository: str, branch: str) -> None:
    try:
        repo_payload, repo_response = await _fetch_repository_payload(repository)
    except httpx.HTTPStatusError as error:
        log_github_response_debug(
            error.response,
            context=f"GitHub repository metadata lookup failed for {repository}",
            request_url=str(error.request.url) if error.request else None,
            request_method=error.request.method if error.request else None,
        )
        return

    permissions = repo_payload.get("permissions", {})
    repo_permissions = permissions if isinstance(permissions, dict) else {}
    branch_exists_on_remote = await branch_exists(repository, branch)

    logger.info(
        "GitHub repository metadata repo={repo} default_branch={default_branch} private={private} "
        "permissions={permissions} target_branch={target_branch} target_branch_exists={target_branch_exists}",
        repo=repository,
        default_branch=repo_payload.get("default_branch"),
        private=repo_payload.get("private"),
        permissions=repo_permissions,
        target_branch=branch,
        target_branch_exists=branch_exists_on_remote,
    )
    log_permission_headers(repo_response, f"GitHub repository access headers for {repository}")


def log_github_response_debug(
    response: httpx.Response,
    context: str,
    request_url: str | None = None,
    request_method: str | None = None,
) -> None:
    formatted_body = _format_response_body(response.text)
    logger.error(
        "GitHub API error context={context} request_method={request_method} request_url={request_url} "
        "status={status} reason={reason} body={body}",
        context=context,
        request_method=request_method or "unknown",
        request_url=request_url or str(response.request.url) if response.request else "unknown",
        status=response.status_code,
        reason=response.reason_phrase,
        body=formatted_body,
    )
    log_permission_headers(response, f"{context} response headers")


def log_permission_headers(response: httpx.Response, context: str) -> None:
    selected_headers = {
        key: value
        for key, value in response.headers.items()
        if key.lower() in PERMISSION_DEBUG_HEADERS
        or "oauth" in key.lower()
        or "permission" in key.lower()
        or "token" in key.lower()
    }
    logger.info(
        "GitHub permission headers context={context} headers={headers}",
        context=context,
        headers=selected_headers or "none",
    )


def _format_response_body(response_body: str) -> str:
    if not response_body:
        return ""

    try:
        return json.dumps(json.loads(response_body), indent=2)
    except json.JSONDecodeError:
        return response_body


def _token_type_from_headers(headers: httpx.Headers) -> str:
    for header_name in (
        "github-authentication-token-type",
        "x-github-authentication-token-type",
    ):
        token_type = headers.get(header_name)
        if token_type:
            return token_type

    oauth_scopes = headers.get("x-oauth-scopes", "")
    if oauth_scopes:
        return "classic"

    return "unknown"


def _classic_token_has_repo_scope(oauth_scopes: str) -> bool:
    scopes = {scope.strip() for scope in oauth_scopes.split(",") if scope.strip()}
    return "repo" in scopes or "public_repo" in scopes


async def _fetch_repository_file_sha(repository: str, file_path: str, branch: str) -> str | None:
    encoded_path = quote(file_path, safe="/")
    params = {"ref": branch} if branch else None

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{GITHUB_API_BASE_URL}/repos/{repository}/contents/{encoded_path}",
            headers=github_json_headers(),
            params=params,
        )

    if response.status_code == 404:
        return None

    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict) and isinstance(payload.get("sha"), str):
        return payload["sha"]

    return None


def github_json_headers() -> dict[str, str]:
    return _github_headers("application/vnd.github+json")


def github_diff_headers() -> dict[str, str]:
    return _github_headers("application/vnd.github.v3.diff")


def _github_token() -> str | None:
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN")
    return token.strip() if token else None


def _github_headers(accept: str) -> dict[str, str]:
    headers = {
        "Accept": accept,
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }
    token = _github_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    return headers
