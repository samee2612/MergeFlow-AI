from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from backend.classifier.diff_classifier import BackendDiffClassification
from backend.generators.api_spec_generator import ApiSpecGenerationResult
from backend.generators.email_generator import (
    build_release_email,
    generate_and_send_release_email,
    parse_recipient_list,
)
from backend.generators.notion_generator import NotionSyncResult
from backend.generators.openapi_generator import OpenApiGenerationResult
from backend.generators.postman_generator import PostmanGenerationResult
from backend.github_client import GitHubCommitResult
from backend.pipeline import PullRequestContext


class FailingEmailClient:
    async def send_email(self, settings, email):
        raise RuntimeError("SendGrid unavailable")


def test_build_release_email_contains_summary_artifacts_and_fallback_formats() -> None:
    email = build_release_email(
        pr_context=_pr_context(),
        classification=BackendDiffClassification(
            change_types=["API", "Authentication"],
            summary="Added login endpoint with remember_me support.",
        ),
        api_spec_result=_api_spec_result(),
        openapi_result=_openapi_result(),
        postman_result=_postman_result(),
        notion_result=NotionSyncResult(success=True, action="created", page_id="page-1", page_url="https://notion.so/page-1"),
        recipients=["dev@example.com"],
        generated_at=datetime(2026, 6, 5, 23, 22, tzinfo=timezone.utc),
    )

    assert email.subject == "[MergeFlow] PR #42 Processed - Add login endpoint"
    assert "POST /login - Login user" in email.plain_text
    assert "[ok] Notion Documentation: https://notion.so/page-1" in email.plain_text
    assert "verify invalid credential handling" in email.plain_text
    assert "<h1>MergeFlow Release Report</h1>" in email.html
    assert "POST /login - Login user" in email.html


def test_parse_recipient_list_supports_multiple_delimiters_and_dedupes() -> None:
    recipients = parse_recipient_list("dev@example.com, qa@example.com;dev@example.com ops@example.com")

    assert recipients == ["dev@example.com", "qa@example.com", "ops@example.com"]


def test_generate_and_send_release_email_returns_failure_without_raising(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SENDGRID_API_KEY", "SG.test")
    monkeypatch.setenv("SENDGRID_FROM_EMAIL", "mergeflow@example.com")
    monkeypatch.setenv("SENDGRID_RECIPIENT_EMAILS", "dev@example.com")
    monkeypatch.setenv("MERGEFLOW_RUNS_DIR", str(tmp_path))

    result = asyncio.run(
        generate_and_send_release_email(
            _pr_context(),
            BackendDiffClassification(change_types=["API"], summary="Added login endpoint."),
            _api_spec_result(),
            _openapi_result(),
            _postman_result(),
            NotionSyncResult(success=True, action="created", page_id="page-1", page_url="https://notion.so/page-1"),
            email_client=FailingEmailClient(),
        )
    )

    assert result.success is False
    assert result.error_message == "SendGrid unavailable"


def _pr_context() -> PullRequestContext:
    return PullRequestContext(
        repository="samee2612/mergeflow-test-repo",
        pr_number=42,
        title="Add login endpoint",
        merged_at="2026-06-05T23:00:00Z",
        author="samee2612",
        changed_files=["backend/routes/auth.py"],
        base_branch="main",
        head_branch="feature/login",
        default_branch="main",
    )


def _api_spec_result() -> ApiSpecGenerationResult:
    return ApiSpecGenerationResult(
        markdown="""## Change Summary
Added login endpoint with remember_me support.

## Test Cases
- verify token expiry
- verify invalid credential handling

## Regression Risks
- token expiry could drift from existing auth expectations
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
  title: Login API
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
        collection_json="""{
  "info": {
    "name": "Login API",
    "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
  },
  "item": [
    {
      "name": "Login user",
      "request": {
        "method": "POST",
        "url": {
          "raw": "{{base_url}}/login"
        }
      }
    }
  ]
}
""",
        destination="tests/postman_collection.json",
        target_path="tests/postman_collection.json",
        target_branch="main",
        commit_result=_commit_result("tests/postman_collection.json"),
    )


def _commit_result(path: str) -> GitHubCommitResult:
    return GitHubCommitResult(
        success=True,
        repository="samee2612/mergeflow-test-repo",
        branch="main",
        file_path=path,
        destination=path,
    )
