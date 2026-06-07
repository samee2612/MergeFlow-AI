import pytest

from backend.classifier.diff_classifier import BackendDiffClassification
from backend.generators import api_spec_generator
from backend.pipeline import PullRequestContext


def _pr_context() -> PullRequestContext:
    return PullRequestContext(
        repository="owner/repo",
        pr_number=42,
        title="Add login endpoint",
        merged_at="2026-06-03T17:00:00Z",
        author="octocat",
        changed_files=[
            "backend/routes/auth.py",
            "backend/services/auth_service.py",
            "backend/schemas/auth.py",
            "frontend/components/Login.tsx",
        ],
        base_branch="master",
        head_branch="feat/login",
        default_branch="main",
    )


def _classification() -> BackendDiffClassification:
    return BackendDiffClassification(
        change_types=["API", "Authentication"],
        summary="Added login endpoint returning JWT token.",
    )


def test_select_directly_related_files_uses_route_files_and_direct_dependencies() -> None:
    selected_files = api_spec_generator.select_directly_related_files(_pr_context().changed_files)

    assert selected_files == [
        "backend/routes/auth.py",
        "backend/services/auth_service.py",
        "backend/schemas/auth.py",
    ]


def test_extract_patches_by_file() -> None:
    diff_text = """diff --git a/backend/routes/auth.py b/backend/routes/auth.py
+@router.post("/login")
diff --git a/backend/services/auth_service.py b/backend/services/auth_service.py
+def login():
"""

    assert api_spec_generator.extract_patches_by_file(diff_text) == {
        "backend/routes/auth.py": 'diff --git a/backend/routes/auth.py b/backend/routes/auth.py\n+@router.post("/login")',
        "backend/services/auth_service.py": "diff --git a/backend/services/auth_service.py b/backend/services/auth_service.py\n+def login():",
    }


@pytest.mark.asyncio
async def test_generate_api_spec_keeps_markdown_as_internal_intermediate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetched_files: list[tuple[str, str]] = []

    async def fake_fetch_file(repository: str, file_path: str) -> str:
        fetched_files.append((repository, file_path))
        return f"# content for {file_path}"

    def fake_generate(
        pr_context: PullRequestContext,
        classification: BackendDiffClassification,
        file_contexts: list[api_spec_generator.RelatedFileContext],
    ) -> str:
        return "# API Spec\n\n## 1. Change Summary\nAdded login endpoint."

    async def fake_resolve_branch(pr_context: PullRequestContext) -> str:
        return "master"

    monkeypatch.setattr(api_spec_generator, "_generate_markdown_with_gemini", fake_generate)
    monkeypatch.setattr(api_spec_generator, "resolve_target_branch", fake_resolve_branch)

    result = await api_spec_generator.generate_api_spec_and_test_cases(
        _pr_context(),
        _classification(),
        'diff --git a/backend/routes/auth.py b/backend/routes/auth.py\n+@router.post("/login")',
        file_fetcher=fake_fetch_file,
    )

    assert result.destination == "Internal intermediate only; not committed to repository."
    assert result.target_branch == "master"
    assert result.target_path == "tests/api-spec-and-test-cases.md"
    assert result.markdown == "# API Spec\n\n## 1. Change Summary\nAdded login endpoint.\n"
    assert result.commit_result is None
    assert fetched_files == [
        ("owner/repo", "backend/routes/auth.py"),
        ("owner/repo", "backend/services/auth_service.py"),
        ("owner/repo", "backend/schemas/auth.py"),
    ]


def test_target_repo_artifact_path_is_root_tests_folder() -> None:
    assert api_spec_generator.build_target_repo_artifact_path() == "tests/api-spec-and-test-cases.md"


@pytest.mark.asyncio
async def test_generate_api_spec_writes_fallback_markdown_when_gemini_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch_file(repository: str, file_path: str) -> str:
        return f"# content for {file_path}"

    def fake_generate(
        pr_context: PullRequestContext,
        classification: BackendDiffClassification,
        file_contexts: list[api_spec_generator.RelatedFileContext],
    ) -> str:
        raise RuntimeError("Gemini unavailable")

    async def fake_resolve_branch(pr_context: PullRequestContext) -> str:
        return "master"

    monkeypatch.setattr(api_spec_generator, "_generate_markdown_with_gemini", fake_generate)
    monkeypatch.setattr(api_spec_generator, "resolve_target_branch", fake_resolve_branch)

    result = await api_spec_generator.generate_api_spec_and_test_cases(
        _pr_context(),
        _classification(),
        "diff --git a/backend/routes/auth.py b/backend/routes/auth.py",
        file_fetcher=fake_fetch_file,
    )

    markdown = result.markdown
    assert "Gemini generation failed" in markdown
    assert "backend/routes/auth.py" in markdown
    assert "Gemini unavailable" in markdown
    assert result.commit_result is None


@pytest.mark.asyncio
async def test_generate_api_spec_ignores_artifact_committer(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch_file(repository: str, file_path: str) -> str:
        return "# content"

    async def fake_resolve_branch(pr_context: PullRequestContext) -> str:
        return "master"

    async def fake_commit(
        *args: object,
        **kwargs: object,
    ) -> object:
        raise AssertionError("API analysis markdown should not be committed")

    def fake_generate(
        pr_context: PullRequestContext,
        classification: BackendDiffClassification,
        file_contexts: list[api_spec_generator.RelatedFileContext],
    ) -> str:
        return "# API Spec\n"

    monkeypatch.setattr(api_spec_generator, "_generate_markdown_with_gemini", fake_generate)
    monkeypatch.setattr(api_spec_generator, "resolve_target_branch", fake_resolve_branch)

    result = await api_spec_generator.generate_api_spec_and_test_cases(
        _pr_context(),
        _classification(),
        "diff --git a/backend/routes/auth.py b/backend/routes/auth.py",
        file_fetcher=fake_fetch_file,
        artifact_committer=fake_commit,
    )

    assert result.destination == "Internal intermediate only; not committed to repository."
    assert result.commit_result is None
