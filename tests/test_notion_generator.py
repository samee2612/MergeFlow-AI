import json

import pytest

from backend.classifier.diff_classifier import BackendDiffClassification
from backend.generators.api_spec_generator import ApiSpecGenerationResult
from backend.generators.notion_generator import (
    NotionPageRef,
    build_notion_page_blocks,
    build_notion_page_title,
    sync_notion_page,
)
from backend.generators.openapi_generator import OpenApiGenerationResult
from backend.generators.postman_generator import POSTMAN_SCHEMA_URL, PostmanGenerationResult
from backend.github_client import GitHubCommitResult
from backend.pipeline import PullRequestContext


def _pr_context() -> PullRequestContext:
    return PullRequestContext(
        repository="owner/mergeflow-target",
        pr_number=42,
        title="Add login endpoint",
        merged_at="2026-06-03T17:00:00Z",
        author="octocat",
        changed_files=["backend/routes/auth.py"],
        base_branch="main",
        head_branch="feature/login",
        default_branch="main",
    )


def _classification() -> BackendDiffClassification:
    return BackendDiffClassification(
        change_types=["API", "Authentication"],
        summary="Added a login endpoint returning JWT tokens.",
    )


def _api_spec_result() -> ApiSpecGenerationResult:
    return ApiSpecGenerationResult(
        markdown="""# API Spec and Test Cases

## 1. Change Summary
Adds a POST /login endpoint for user authentication.

## 2. Endpoint(s) Detected
- POST /login creates a user session token.

## 5. Test Cases
- Successful login returns 200 and a token.
- Missing password returns 422.
""",
        destination="https://github.com/owner/mergeflow-target/blob/main/tests/api-spec-and-test-cases.md",
        target_path="tests/api-spec-and-test-cases.md",
        target_branch="main",
        commit_result=_commit_result("tests/api-spec-and-test-cases.md"),
    )


def _openapi_result() -> OpenApiGenerationResult:
    return OpenApiGenerationResult(
        yaml_content="""openapi: 3.0.3
info:
  title: Test API
  version: 0.1.0
paths:
  /login:
    post:
      summary: Login user
      responses:
        '200':
          description: Successful response
""",
        destination="https://github.com/owner/mergeflow-target/blob/main/tests/openapi.yaml",
        target_path="tests/openapi.yaml",
        target_branch="main",
        commit_result=_commit_result("tests/openapi.yaml"),
    )


def _postman_result() -> PostmanGenerationResult:
    collection_json = json.dumps(
        {
            "info": {
                "name": "MergeFlow Postman Collection",
                "schema": POSTMAN_SCHEMA_URL,
            },
            "item": [
                {
                    "name": "Login user",
                    "request": {
                        "method": "POST",
                        "url": {"raw": "{{base_url}}/login"},
                    },
                }
            ],
        }
    )
    return PostmanGenerationResult(
        collection_json=collection_json,
        destination="https://github.com/owner/mergeflow-target/blob/main/tests/postman_collection.json",
        target_path="tests/postman_collection.json",
        target_branch="main",
        commit_result=_commit_result("tests/postman_collection.json"),
    )


def _commit_result(file_path: str) -> GitHubCommitResult:
    return GitHubCommitResult(
        success=True,
        repository="owner/mergeflow-target",
        branch="main",
        file_path=file_path,
        destination=f"https://github.com/owner/mergeflow-target/blob/main/{file_path}",
    )


class FakeNotionClient:
    def __init__(self, existing_page: NotionPageRef | None = None, fail: bool = False) -> None:
        self.existing_page = existing_page
        self.fail = fail
        self.created: list[tuple[str, str, str, list[dict]]] = []
        self.updated: list[tuple[str, str, str, list[dict]]] = []

    async def find_page_by_title(self, database_id: str, title_property: str, title: str) -> NotionPageRef | None:
        if self.fail:
            raise RuntimeError("Notion unavailable")
        return self.existing_page

    async def create_page(
        self,
        database_id: str,
        title_property: str,
        title: str,
        blocks: list[dict],
    ) -> NotionPageRef:
        self.created.append((database_id, title_property, title, blocks))
        return NotionPageRef(page_id="new-page", page_url="https://notion.so/new-page")

    async def update_page(
        self,
        page_id: str,
        title_property: str,
        title: str,
        blocks: list[dict],
    ) -> NotionPageRef:
        self.updated.append((page_id, title_property, title, blocks))
        return NotionPageRef(page_id=page_id, page_url=f"https://notion.so/{page_id}")


def test_build_notion_page_title_uses_repo_and_pr_number() -> None:
    assert build_notion_page_title(_pr_context()) == "MergeFlow - mergeflow-target - PR #42"


def test_build_notion_page_blocks_include_step_outputs() -> None:
    blocks = build_notion_page_blocks(_pr_context(), _classification(), _api_spec_result(), _openapi_result(), _postman_result())
    block_text = json.dumps(blocks)

    assert "Added a login endpoint returning JWT tokens." in block_text
    assert "Adds a POST /login endpoint for user authentication." in block_text
    assert "POST /login - Login user" in block_text
    assert "Successful login returns 200 and a token." in block_text
    assert "POST {{base_url}}/login" in block_text
    assert "tests/openapi.yaml" in block_text
    assert "tests/postman_collection.json" in block_text


@pytest.mark.asyncio
async def test_sync_notion_page_creates_page_and_writes_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("NOTION_API_KEY", "secret")
    monkeypatch.setenv("NOTION_DATABASE_ID", "database-1")
    monkeypatch.setenv("NOTION_TITLE_PROPERTY", "Name")
    monkeypatch.setenv("MERGEFLOW_RUNS_DIR", str(tmp_path))
    client = FakeNotionClient()

    result = await sync_notion_page(
        _pr_context(),
        _classification(),
        _api_spec_result(),
        _openapi_result(),
        _postman_result(),
        notion_client=client,
    )

    assert result.success is True
    assert result.action == "created"
    assert result.page_id == "new-page"
    assert result.page_url == "https://notion.so/new-page"
    assert client.created[0][0] == "database-1"
    assert client.created[0][1] == "Name"
    assert client.created[0][2] == "MergeFlow - mergeflow-target - PR #42"
    metadata = json.loads((tmp_path / "owner" / "mergeflow-target" / "42" / "mergeflow_run_metadata.json").read_text())
    assert metadata["notion"]["page_url"] == "https://notion.so/new-page"


@pytest.mark.asyncio
async def test_sync_notion_page_updates_existing_page(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("NOTION_API_KEY", "secret")
    monkeypatch.setenv("NOTION_DATABASE_ID", "database-1")
    monkeypatch.setenv("MERGEFLOW_RUNS_DIR", str(tmp_path))
    client = FakeNotionClient(existing_page=NotionPageRef(page_id="existing-page", page_url="https://notion.so/existing-page"))

    result = await sync_notion_page(
        _pr_context(),
        _classification(),
        _api_spec_result(),
        _openapi_result(),
        _postman_result(),
        notion_client=client,
    )

    assert result.success is True
    assert result.action == "updated"
    assert client.created == []
    assert client.updated[0][0] == "existing-page"


@pytest.mark.asyncio
async def test_sync_notion_page_logs_failure_without_crashing(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("NOTION_API_KEY", "secret")
    monkeypatch.setenv("NOTION_DATABASE_ID", "database-1")
    monkeypatch.setenv("MERGEFLOW_RUNS_DIR", str(tmp_path))

    result = await sync_notion_page(
        _pr_context(),
        _classification(),
        _api_spec_result(),
        _openapi_result(),
        _postman_result(),
        notion_client=FakeNotionClient(fail=True),
    )

    assert result.success is False
    assert result.action == "failed"
    assert "Notion unavailable" in result.error_message
    metadata = json.loads((tmp_path / "owner" / "mergeflow-target" / "42" / "mergeflow_run_metadata.json").read_text())
    assert metadata["notion"]["success"] is False
