import json

import pytest

from backend.classifier.diff_classifier import BackendDiffClassification
from backend.generators.api_spec_generator import ApiSpecGenerationResult
from backend.generators.notion_draft_generator import (
    build_feature_folder_slug,
    build_pr_review_page_blocks,
    update_notion_documentation,
    _merge_section_blocks,
)
from backend.generators.notion_generator import NotionPageRef
from backend.generators.openapi_generator import OpenApiGenerationResult
from backend.generators.postman_generator import PostmanGenerationResult
from backend.github_client import GitHubCommitResult
from backend.pipeline import PullRequestContext
from backend.service_resolver import ServiceResolution


def _service() -> ServiceResolution:
    return ServiceResolution(
        team_id="platform-engineering",
        team_name="Platform Engineering",
        service_id="identity-service",
        service_name="Identity Service",
        method="repository_mapping",
        confidence="high",
    )


def _pr_context() -> PullRequestContext:
    return PullRequestContext(
        repository="owner/identity-service",
        pr_number=42,
        title="Add login endpoint",
        merged_at="2026-06-03T17:00:00Z",
        author="octocat",
        changed_files=["backend/routes/auth.py"],
    )


class FakeNotionHierarchyClient:
    def __init__(self) -> None:
        self.service_page = NotionPageRef(page_id="service-page", page_url="https://notion.so/service-page")
        self.created: list[tuple[str, str, list[dict]]] = []
        self.updated: list[tuple[str, list[dict]]] = []
        self.merged: list[tuple[str, dict[str, list[dict]]]] = []
        self.child_pages: dict[tuple[str, str], NotionPageRef] = {
            ("database-1", "Identity Service"): self.service_page,
        }

    async def find_page_by_title(self, database_id: str, title_property: str, title: str) -> NotionPageRef | None:
        return self.child_pages.get((database_id, title))

    async def find_child_page_by_title(self, parent_page_id: str, title: str) -> NotionPageRef | None:
        return self.child_pages.get((parent_page_id, title))

    async def create_child_page(self, parent_page_id: str, title: str, blocks: list[dict]) -> NotionPageRef:
        self.created.append((parent_page_id, title, blocks))
        page_ref = NotionPageRef(page_id=f"{parent_page_id}-{title}", page_url=f"https://notion.so/{parent_page_id}-{title}")
        self.child_pages[(parent_page_id, title)] = page_ref
        return page_ref

    async def update_child_page(self, page_id: str, blocks: list[dict]) -> NotionPageRef:
        self.updated.append((page_id, blocks))
        return NotionPageRef(page_id=page_id, page_url=f"https://notion.so/{page_id}")

    async def merge_service_page_sections(self, page_id: str, section_blocks: dict[str, list[dict]]) -> NotionPageRef:
        self.merged.append((page_id, section_blocks))
        return NotionPageRef(page_id=page_id, page_url=f"https://notion.so/{page_id}")


def test_build_feature_folder_slug() -> None:
    assert build_feature_folder_slug(_pr_context()) == "feature-42-add-login-endpoint"


def test_build_pr_review_page_blocks_include_draft_markers() -> None:
    from backend.generators.mermaid_generator import generate_mermaid_diagrams

    blocks = build_pr_review_page_blocks(
        _pr_context(),
        _service(),
        BackendDiffClassification(change_types=["API"], summary="Added login endpoint."),
        _api_spec_result(),
        _openapi_result(),
        _postman_result(),
        generate_mermaid_diagrams("Identity Service", _openapi_result().yaml_content),
    )
    block_text = json.dumps(blocks)

    assert "DRAFT" in block_text
    assert "Awaiting Review" in block_text
    assert "POST /login" in block_text
    assert "sequenceDiagram" in block_text


def test_merge_section_blocks_appends_release_history() -> None:
    existing = [
        {"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "Release History"}}]}},
        {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "PR #41"}}]}},
    ]
    updates = {
        "Release History": [
            {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "PR #42"}}]}},
        ]
    }

    merged = _merge_section_blocks(existing, updates)
    merged_text = json.dumps(merged)

    assert "PR #41" in merged_text
    assert "PR #42" in merged_text


@pytest.mark.asyncio
async def test_update_notion_documentation_creates_review_hierarchy(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("NOTION_API_KEY", "secret")
    monkeypatch.setenv("NOTION_DATABASE_ID", "database-1")
    monkeypatch.setenv("MERGEFLOW_RUNS_DIR", str(tmp_path))
    client = FakeNotionHierarchyClient()

    result = await update_notion_documentation(
        _pr_context(),
        _service(),
        BackendDiffClassification(change_types=["API", "Authentication"], summary="Added login endpoint."),
        _api_spec_result(),
        _openapi_result(),
        _postman_result(),
        notion_client=client,
    )

    assert result.success is True
    assert result.pr_review_page_url is not None
    assert result.service_page_url == "https://notion.so/service-page"
    assert any(title == "MergeFlow PR Reviews" for _, title, _ in client.created)
    assert any(title.startswith("feature-42") for _, title, _ in client.created)
    assert client.merged[0][0] == "service-page"


def _api_spec_result() -> ApiSpecGenerationResult:
    return ApiSpecGenerationResult(
        markdown="""## Change Summary
Adds a POST /login endpoint for user authentication.

## Test Cases
- Successful login returns 200 and a token.
""",
        destination="tests/api-spec-and-test-cases.md",
        target_path="tests/api-spec-and-test-cases.md",
        target_branch="main",
        commit_result=_commit_result("tests/api-spec-and-test-cases.md"),
    )


def _openapi_result() -> OpenApiGenerationResult:
    return OpenApiGenerationResult(
        yaml_content="""openapi: 3.0.3
info:
  title: Auth API
  version: 0.1.0
paths:
  /login:
    post:
      summary: Login user
      responses:
        '200':
          description: Successful response
""",
        destination="tests/openapi.yaml",
        target_path="tests/openapi.yaml",
        target_branch="main",
        commit_result=_commit_result("tests/openapi.yaml"),
    )


def _postman_result() -> PostmanGenerationResult:
    return PostmanGenerationResult(
        collection_json='{"info":{"name":"Auth","schema":"https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},"item":[{"name":"Login","request":{"method":"POST","url":{"raw":"{{base_url}}/login"}}}]}',
        destination="tests/postman_collection.json",
        target_path="tests/postman_collection.json",
        target_branch="main",
        commit_result=_commit_result("tests/postman_collection.json"),
    )


def _commit_result(path: str) -> GitHubCommitResult:
    return GitHubCommitResult(
        success=True,
        repository="owner/identity-service",
        branch="main",
        file_path=path,
        destination=path,
    )
