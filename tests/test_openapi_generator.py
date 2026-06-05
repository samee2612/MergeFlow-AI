import pytest
import yaml

from backend.classifier.diff_classifier import BackendDiffClassification
from backend.generators import openapi_generator
from backend.github_client import GitHubCommitResult
from backend.pipeline import PullRequestContext


def _pr_context() -> PullRequestContext:
    return PullRequestContext(
        repository="owner/repo",
        pr_number=42,
        title="Add login endpoint",
        merged_at="2026-06-03T17:00:00Z",
        author="octocat",
        changed_files=["backend/routes/auth.py"],
        base_branch="master",
        head_branch="feat/login",
        default_branch="main",
    )


def _classification() -> BackendDiffClassification:
    return BackendDiffClassification(
        change_types=["API", "Authentication"],
        summary="Added login endpoint returning JWT token.",
    )


def _openapi_yaml() -> str:
    return """openapi: 3.0.3
info:
  title: Auth API
  version: 0.1.0
  description: Login endpoint from Step 3 analysis.
paths:
  /login:
    post:
      summary: Login user
      tags:
        - Auth
      security:
        - bearerAuth: []
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required:
                - email
                - password
              properties:
                email:
                  type: string
                password:
                  type: string
            example:
              email: user@example.com
              password: secret
      responses:
        "200":
          description: Login succeeded
          content:
            application/json:
              schema:
                type: object
                properties:
                  token:
                    type: string
              example:
                token: jwt-token
        "401":
          description: Invalid credentials
components:
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
x-mergeflow-env-vars:
  - JWT_SECRET
"""


def _step3_source_context() -> str:
    return '''# API Spec and Test Cases

## 9. Source Context For Downstream Generators

### backend/routes/auth.py
```python
@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Log in with email and password",
    responses={
        200: {"description": "Login succeeded and returned a bearer token."},
        400: {"model": ErrorResponse, "description": "The request body is missing required fields."},
        401: {"model": ErrorResponse, "description": "Invalid credentials."},
    },
)
def login(
    payload: dict[str, Any] | None = Body(
        default=None,
        example={
            "email": "admin@example.com",
            "password": "correct-horse-battery-staple",
            "remember_me": True,
        },
    ),
    x_request_id: str | None = Header(
        default=None,
        alias="X-Request-ID",
        description="Optional client-generated request ID.",
        example="login-request-123",
    ),
) -> LoginResponse:
    request = LoginRequest(**payload)
    auth_token = authenticate_user(request.email, request.password, request.remember_me)
    return LoginResponse(token=auth_token.token, token_type=auth_token.token_type, expires_in=auth_token.expires_in)
```

### backend/schemas/auth.py
```python
class LoginRequest(BaseModel):
    email: EmailStr = Field(..., description="Email address.", example="admin@example.com")
    password: str = Field(..., min_length=8, description="Plain text password.", example="correct-horse-battery-staple")
    remember_me: bool = Field(default=False, description="Issue a longer-lived token.", example=True)

class LoginResponse(BaseModel):
    token: str = Field(..., description="Bearer token.", example="demo-token-for-admin-user")
    token_type: str = Field(default="bearer", description="Token type.", example="bearer")
    expires_in: int = Field(..., description="Token lifetime in seconds.", example=86400)

class ErrorResponse(BaseModel):
    detail: str = Field(..., description="Error message.", example="Invalid email or password.")
```
'''


def test_validate_openapi_yaml_accepts_fenced_yaml() -> None:
    cleaned = openapi_generator.validate_openapi_yaml(f"```yaml\n{_openapi_yaml()}\n```")

    parsed = yaml.safe_load(cleaned)
    assert parsed["openapi"] == "3.0.3"
    assert parsed["paths"]["/login"]["post"]["summary"] == "Login user"


def test_validate_openapi_yaml_rejects_malformed_yaml() -> None:
    with pytest.raises(ValueError, match="well-formed"):
        openapi_generator.validate_openapi_yaml("openapi: 3.0.3\ninfo: [")


def test_fallback_openapi_extracts_login_endpoint_from_step3_source_context() -> None:
    fallback_yaml = openapi_generator.build_fallback_openapi_yaml(
        _pr_context(),
        _classification(),
        "Gemini unavailable",
        _step3_source_context(),
    )

    parsed = yaml.safe_load(fallback_yaml)
    operation = parsed["paths"]["/login"]["post"]
    request_schema = parsed["components"]["schemas"]["LoginRequest"]
    response_schema = parsed["components"]["schemas"]["LoginResponse"]

    assert operation["summary"] == "Log in with email and password"
    assert operation["parameters"][0]["name"] == "X-Request-ID"
    assert operation["requestBody"]["content"]["application/json"]["example"] == {
        "email": "admin@example.com",
        "password": "correct-horse-battery-staple",
        "remember_me": True,
    }
    assert sorted(operation["responses"].keys()) == ["200", "400", "401"]
    assert request_schema["properties"]["email"]["format"] == "email"
    assert set(request_schema["properties"]) == {"email", "password", "remember_me"}
    assert set(response_schema["properties"]) == {"token", "token_type", "expires_in"}


@pytest.mark.asyncio
async def test_generate_openapi_replaces_empty_paths_when_endpoints_are_detected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commits: list[tuple[str, str, str, str, str, int | None]] = []

    def fake_generate(
        pr_context: PullRequestContext,
        classification: BackendDiffClassification,
        api_analysis_markdown: str,
    ) -> str:
        return """openapi: 3.0.3
info:
  title: Empty API
  version: 0.1.0
paths: {}
"""

    async def fake_commit(
        repository: str,
        branch: str,
        file_path: str,
        content: str,
        commit_message: str,
        pr_number: int | None,
    ) -> GitHubCommitResult:
        commits.append((repository, branch, file_path, content, commit_message, pr_number))
        return GitHubCommitResult(
            success=True,
            repository=repository,
            branch=branch,
            file_path=file_path,
            destination=file_path,
        )

    monkeypatch.setattr(openapi_generator, "_generate_openapi_yaml_with_gemini", fake_generate)

    result = await openapi_generator.generate_openapi_yaml(
        _pr_context(),
        _classification(),
        _step3_source_context(),
        "master",
        artifact_committer=fake_commit,
    )

    parsed = yaml.safe_load(result.yaml_content)
    assert "/login" in parsed["paths"]
    assert "post" in parsed["paths"]["/login"]
    assert openapi_generator.count_openapi_paths(result.yaml_content) == 1


@pytest.mark.asyncio
async def test_generate_openapi_yaml_commits_to_target_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    commits: list[tuple[str, str, str, str, str, int | None]] = []

    def fake_generate(
        pr_context: PullRequestContext,
        classification: BackendDiffClassification,
        api_analysis_markdown: str,
    ) -> str:
        assert "## 4. API Specification Snapshot" in api_analysis_markdown
        return _openapi_yaml()

    async def fake_commit(
        repository: str,
        branch: str,
        file_path: str,
        content: str,
        commit_message: str,
        pr_number: int | None,
    ) -> GitHubCommitResult:
        commits.append((repository, branch, file_path, content, commit_message, pr_number))
        return GitHubCommitResult(
            success=True,
            repository=repository,
            branch=branch,
            file_path=file_path,
            destination=f"https://github.com/{repository}/blob/{branch}/{file_path}",
        )

    monkeypatch.setattr(openapi_generator, "_generate_openapi_yaml_with_gemini", fake_generate)

    result = await openapi_generator.generate_openapi_yaml(
        _pr_context(),
        _classification(),
        "## 4. API Specification Snapshot\n- method: POST\n- path: /login",
        "master",
        artifact_committer=fake_commit,
    )

    assert result.destination == "https://github.com/owner/repo/blob/master/tests/openapi.yaml"
    assert result.target_path == "tests/openapi.yaml"
    assert commits == [
        (
            "owner/repo",
            "master",
            "tests/openapi.yaml",
            _openapi_yaml(),
            "Add MergeFlow OpenAPI spec for #42",
            42,
        )
    ]


@pytest.mark.asyncio
async def test_generate_openapi_yaml_uses_valid_fallback_when_gemini_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commits: list[tuple[str, str, str, str, str, int | None]] = []

    def fake_generate(
        pr_context: PullRequestContext,
        classification: BackendDiffClassification,
        api_analysis_markdown: str,
    ) -> str:
        raise RuntimeError("Gemini unavailable")

    async def fake_commit(
        repository: str,
        branch: str,
        file_path: str,
        content: str,
        commit_message: str,
        pr_number: int | None,
    ) -> GitHubCommitResult:
        commits.append((repository, branch, file_path, content, commit_message, pr_number))
        return GitHubCommitResult(
            success=True,
            repository=repository,
            branch=branch,
            file_path=file_path,
            destination=file_path,
        )

    monkeypatch.setattr(openapi_generator, "_generate_openapi_yaml_with_gemini", fake_generate)

    result = await openapi_generator.generate_openapi_yaml(
        _pr_context(),
        _classification(),
        "Step 3 markdown",
        "master",
        artifact_committer=fake_commit,
    )

    parsed = yaml.safe_load(result.yaml_content)
    assert parsed["openapi"] == "3.0.3"
    assert parsed["paths"] == {}
    assert parsed["x-mergeflow"]["generator_error"] == "Gemini unavailable"
    assert commits[0][2] == "tests/openapi.yaml"


@pytest.mark.asyncio
async def test_generate_openapi_yaml_does_not_crash_when_commit_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_commit(
        repository: str,
        branch: str,
        file_path: str,
        content: str,
        commit_message: str,
        pr_number: int | None,
    ) -> GitHubCommitResult:
        return GitHubCommitResult(
            success=False,
            repository=repository,
            branch=branch,
            file_path=file_path,
            destination=file_path,
            error_message="Commit requires Contents: write access to owner/repo.",
            local_backup_path="/tmp/mergeflow-runs/owner/repo/42/tests/openapi.yaml",
        )

    monkeypatch.setattr(openapi_generator, "_generate_openapi_yaml_with_gemini", lambda *args: _openapi_yaml())

    result = await openapi_generator.generate_openapi_yaml(
        _pr_context(),
        _classification(),
        "Step 3 markdown",
        "master",
        artifact_committer=fake_commit,
    )

    assert result.destination == "tests/openapi.yaml"
    assert result.commit_result is not None
    assert result.commit_result.local_backup_path == "/tmp/mergeflow-runs/owner/repo/42/tests/openapi.yaml"
