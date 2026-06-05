import pytest

from backend import pipeline
from backend.classifier.diff_classifier import BackendDiffClassification


@pytest.mark.asyncio
async def test_backend_pr_fetches_diff_and_classifies(monkeypatch: pytest.MonkeyPatch) -> None:
    diff_calls: list[tuple[str, int]] = []
    classifier_calls: list[tuple[str, list[str]]] = []
    generator_calls: list[tuple[pipeline.PullRequestContext, BackendDiffClassification, str]] = []

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
    ) -> None:
        generator_calls.append((pr_context, classification, diff_text))

    monkeypatch.setattr(pipeline, "fetch_pull_request_diff", fake_fetch_diff)
    monkeypatch.setattr(pipeline, "classify_backend_diff", fake_classify)
    monkeypatch.setattr(pipeline, "generate_api_spec_and_test_cases", fake_generate)

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


@pytest.mark.asyncio
async def test_non_backend_pr_does_not_fetch_diff(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch_diff(repository: str, pr_number: int) -> str:
        raise AssertionError("Diff should not be fetched for non-backend PRs")

    monkeypatch.setattr(pipeline, "fetch_pull_request_diff", fake_fetch_diff)

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

    assert accepted is False
