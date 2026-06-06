import pytest

from backend import pipeline
from backend.classifier.diff_classifier import BackendDiffClassification
from backend.classifier.scope_classifier import ChangeScopeClassification
from backend.generators.api_spec_generator import ApiSpecGenerationResult
from backend.generators.notion_draft_generator import NotionDocumentationResult
from backend.generators.openapi_generator import OpenApiGenerationResult
from backend.generators.postman_generator import PostmanGenerationResult
from backend.github_client import GitHubCommitResult


@pytest.mark.asyncio
async def test_backend_pr_fetches_diff_and_classifies(monkeypatch: pytest.MonkeyPatch) -> None:
    diff_calls: list[tuple[str, int]] = []
    classifier_calls: list[tuple[str, list[str]]] = []
    generator_calls: list[tuple[pipeline.PullRequestContext, BackendDiffClassification, str]] = []
    openapi_calls: list[tuple[pipeline.PullRequestContext, BackendDiffClassification, str, str]] = []
    postman_calls: list[tuple[pipeline.PullRequestContext, str, str]] = []
    notion_calls: list[tuple[object, ...]] = []

    async def fake_fetch_diff(repository: str, pr_number: int) -> str:
        diff_calls.append((repository, pr_number))
        return "diff --git a/backend/services/foo.py b/backend/services/foo.py"

    def fake_classify(diff_text: str, changed_files: list[str]) -> BackendDiffClassification:
        classifier_calls.append((diff_text, changed_files))
        return BackendDiffClassification(
            change_types=["Service Logic"],
            summary="Updated backend service logic.",
        )

    async def fake_generate(
        pr_context: pipeline.PullRequestContext,
        classification: BackendDiffClassification,
        diff_text: str,
    ) -> ApiSpecGenerationResult:
        generator_calls.append((pr_context, classification, diff_text))
        return ApiSpecGenerationResult(
            markdown="# API Spec\n\n## 4. API Specification Snapshot\n- method: GET\n- path: /foo\n",
            destination="tests/api-spec-and-test-cases.md",
            target_path="tests/api-spec-and-test-cases.md",
            target_branch="master",
            commit_result=GitHubCommitResult(
                success=True,
                repository=pr_context.repository,
                branch="master",
                file_path="tests/api-spec-and-test-cases.md",
                destination="tests/api-spec-and-test-cases.md",
            ),
        )

    async def fake_generate_openapi(
        pr_context: pipeline.PullRequestContext,
        classification: BackendDiffClassification,
        api_analysis_markdown: str,
        target_branch: str,
    ) -> OpenApiGenerationResult:
        openapi_calls.append((pr_context, classification, api_analysis_markdown, target_branch))
        return OpenApiGenerationResult(
            yaml_content="openapi: 3.0.3\ninfo:\n  title: Test API\n  version: 0.1.0\npaths: {}\n",
            destination="tests/openapi.yaml",
            target_path="tests/openapi.yaml",
            target_branch=target_branch,
            commit_result=GitHubCommitResult(
                success=True,
                repository=pr_context.repository,
                branch=target_branch,
                file_path="tests/openapi.yaml",
                destination="tests/openapi.yaml",
            ),
        )

    async def fake_generate_postman(
        pr_context: pipeline.PullRequestContext,
        openapi_yaml: str,
        target_branch: str,
    ) -> PostmanGenerationResult:
        postman_calls.append((pr_context, openapi_yaml, target_branch))
        return PostmanGenerationResult(
            collection_json='{"info":{"name":"Test","schema":"https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},"item":[]}',
            destination="tests/postman_collection.json",
            target_path="tests/postman_collection.json",
            target_branch=target_branch,
            commit_result=GitHubCommitResult(
                success=True,
                repository=pr_context.repository,
                branch=target_branch,
                file_path="tests/postman_collection.json",
                destination="tests/postman_collection.json",
            ),
        )

    async def fake_update_notion(
        pr_context: pipeline.PullRequestContext,
        service: pipeline.ServiceResolution,
        classification: BackendDiffClassification,
        api_spec_result: ApiSpecGenerationResult,
        openapi_result: OpenApiGenerationResult,
        postman_result: PostmanGenerationResult,
    ) -> NotionDocumentationResult:
        notion_calls.append((pr_context, service, classification, api_spec_result, openapi_result, postman_result))
        return NotionDocumentationResult(
            success=True,
            action="service_updated_pr_created",
            pr_review_page_id="pr-page-1",
            pr_review_page_url="https://notion.so/pr-page-1",
            service_page_id="service-page-1",
            service_page_url="https://notion.so/service-page-1",
        )

    monkeypatch.setattr(pipeline, "fetch_pull_request_diff", fake_fetch_diff)
    monkeypatch.setattr(pipeline, "classify_backend_diff", fake_classify)
    monkeypatch.setattr(
        pipeline,
        "classify_change_scope",
        lambda changed_files, pr_title="", repository="": ChangeScopeClassification(
            scope="api",
            action="generate_api_artifacts",
            summary="Backend/API api change across 1 file(s) \"Update service\".",
            change_types=["API"],
        ),
    )
    monkeypatch.setattr(pipeline, "generate_api_spec_and_test_cases", fake_generate)
    monkeypatch.setattr(pipeline, "generate_openapi_yaml", fake_generate_openapi)
    monkeypatch.setattr(pipeline, "generate_postman_collection", fake_generate_postman)
    monkeypatch.setattr(pipeline, "update_notion_documentation", fake_update_notion)

    accepted = await pipeline.run_post_merge_pipeline(
        pipeline.PullRequestContext(
            repository="owner/repo",
            pr_number=42,
            title="Update service",
            merged_at="2026-06-03T17:00:00Z",
            author="octocat",
            changed_files=["backend/services/foo.py"],
        )
    )

    assert accepted is True
    assert diff_calls == [("owner/repo", 42)]
    assert classifier_calls == [
        (
            "diff --git a/backend/services/foo.py b/backend/services/foo.py",
            ["backend/services/foo.py"],
        )
    ]
    assert len(generator_calls) == 1
    assert generator_calls[0][1].change_types == ["Service Logic"]
    assert generator_calls[0][2] == "diff --git a/backend/services/foo.py b/backend/services/foo.py"
    assert len(openapi_calls) == 1
    assert openapi_calls[0][2] == "# API Spec\n\n## 4. API Specification Snapshot\n- method: GET\n- path: /foo\n"
    assert openapi_calls[0][3] == "master"
    assert postman_calls == [
        (
            generator_calls[0][0],
            "openapi: 3.0.3\ninfo:\n  title: Test API\n  version: 0.1.0\npaths: {}\n",
            "master",
        )
    ]
    assert len(notion_calls) == 1
    assert notion_calls[0][3].markdown == "# API Spec\n\n## 4. API Specification Snapshot\n- method: GET\n- path: /foo\n"
    assert notion_calls[0][4].yaml_content == "openapi: 3.0.3\ninfo:\n  title: Test API\n  version: 0.1.0\npaths: {}\n"
    assert notion_calls[0][5].collection_json.startswith('{"info"')


@pytest.mark.asyncio
async def test_non_backend_pr_does_not_fetch_diff(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch_diff(repository: str, pr_number: int) -> str:
        raise AssertionError("Diff should not be fetched for non-backend PRs")

    monkeypatch.setattr(pipeline, "fetch_pull_request_diff", fake_fetch_diff)
    monkeypatch.setattr(
        pipeline,
        "classify_change_scope",
        lambda changed_files, pr_title="", repository="": ChangeScopeClassification(
            scope="frontend",
            action="track_only",
            summary="Tracked frontend change across 1 file(s) \"Update UI\".",
            change_types=["Frontend"],
        ),
    )

    accepted = await pipeline.run_post_merge_pipeline(
        pipeline.PullRequestContext(
            repository="owner/repo",
            pr_number=42,
            title="Update UI",
            merged_at="2026-06-03T17:00:00Z",
            author="octocat",
            changed_files=["frontend/components/Button.tsx"],
        )
    )

    assert accepted is True
