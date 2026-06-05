import json

import httpx
import pytest

from backend import github_client


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: dict[str, object] | None = None,
        *,
        text: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text if text is not None else json.dumps(self._payload)
        self.headers = httpx.Headers(headers or {})
        self.reason_phrase = "Not Found" if status_code == 404 else "OK"
        self.request = httpx.Request("PUT", "https://api.github.com/test")

    @property
    def is_error(self) -> bool:
        return self.status_code >= 400

    def json(self) -> dict[str, object]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.is_error:
            raise httpx.HTTPStatusError(
                "error",
                request=self.request,
                response=self,
            )


class FakeAsyncClient:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = responses
        self._index = 0

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get(self, *args: object, **kwargs: object) -> FakeResponse:
        response = self._responses[self._index]
        self._index += 1
        return response

    async def put(self, *args: object, **kwargs: object) -> FakeResponse:
        response = self._responses[self._index]
        self._index += 1
        return response


@pytest.mark.asyncio
async def test_resolve_commit_branch_uses_first_existing_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_branch_exists(repository: str, branch: str) -> bool:
        return branch == "main"

    monkeypatch.setattr(github_client, "branch_exists", fake_branch_exists)

    branch = await github_client.resolve_commit_branch(
        "owner/repo",
        ["master", "main"],
    )

    assert branch == "main"


@pytest.mark.asyncio
async def test_resolve_commit_branch_falls_back_to_repository_default(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_branch_exists(repository: str, branch: str) -> bool:
        return branch == "develop"

    async def fake_default_branch(repository: str) -> str:
        return "develop"

    monkeypatch.setattr(github_client, "branch_exists", fake_branch_exists)
    monkeypatch.setattr(github_client, "fetch_repository_default_branch", fake_default_branch)

    branch = await github_client.resolve_commit_branch(
        "owner/repo",
        ["master"],
    )

    assert branch == "develop"


@pytest.mark.asyncio
async def test_verify_contents_write_access_detects_missing_push_permission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch_repository_payload(repository: str) -> tuple[dict[str, object], FakeResponse]:
        return (
            {"permissions": {"push": False, "admin": False}},
            FakeResponse(
                200,
                headers={
                    "github-authentication-token-type": "fine-grained",
                    "x-oauth-scopes": "",
                },
            ),
        )

    monkeypatch.setattr(github_client, "_github_token", lambda: "token")
    monkeypatch.setattr(github_client, "_fetch_repository_payload", fake_fetch_repository_payload)

    error_message = await github_client.verify_contents_write_access("owner/repo")

    assert error_message is not None
    assert "Contents: write access" in error_message


@pytest.mark.asyncio
async def test_commit_repository_file_text_returns_failure_without_raising(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pytest.TempPathFactory,
) -> None:
    async def fake_log_preflight(**kwargs: object) -> None:
        return None

    async def fake_verify(repository: str) -> str | None:
        return None

    async def fake_fetch_sha(repository: str, file_path: str, branch: str) -> str | None:
        return None

    monkeypatch.setattr(github_client, "log_commit_preflight", fake_log_preflight)
    monkeypatch.setattr(github_client, "verify_contents_write_access", fake_verify)
    monkeypatch.setattr(github_client, "_fetch_repository_file_sha", fake_fetch_sha)
    monkeypatch.setenv("MERGEFLOW_RUNS_DIR", str(tmp_path))
    monkeypatch.setattr(
        github_client.httpx,
        "AsyncClient",
        lambda *args, **kwargs: FakeAsyncClient(
            [
                FakeResponse(
                    404,
                    text='{"message":"Not Found","documentation_url":"https://docs.github.com/rest"}',
                    headers={"x-oauth-scopes": "repo"},
                )
            ]
        ),
    )

    result = await github_client.commit_repository_file_text(
        "owner/repo",
        "main",
        "tests/api-spec-and-test-cases.md",
        "# API Spec\n",
        "Add MergeFlow API test cases for #42",
        pr_number=42,
    )

    assert result.success is False
    assert "Contents: write access" in (result.error_message or "")
    assert result.local_backup_path is not None
