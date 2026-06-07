import json

import pytest

from backend.generators import postman_generator
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


def _openapi_yaml() -> str:
    return """openapi: 3.0.3
info:
  title: Auth API
  version: 0.1.0
servers:
  - url: https://api.example.test
paths:
  /login:
    post:
      operationId: loginUser
      summary: Login user
      tags:
        - Auth
      security:
        - bearerAuth: []
      parameters:
        - name: X-Request-ID
          in: header
          schema:
            type: string
          example: request-123
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
                  format: email
                password:
                  type: string
            example:
              email: admin@example.com
              password: correct-horse-battery-staple
      responses:
        "200":
          description: Login succeeded
        "400":
          description: Missing or invalid request body
        "401":
          description: Invalid credentials
components:
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
"""


def _postman_json() -> str:
    return json.dumps(
        {
            "info": {
                "name": "Auth API",
                "schema": postman_generator.POSTMAN_SCHEMA_URL,
            },
            "item": [
                {
                    "name": "Login user",
                    "request": {
                        "method": "POST",
                        "header": [{"key": "Content-Type", "value": "application/json"}],
                        "url": {
                            "raw": "{{base_url}}/login",
                            "host": ["{{base_url}}"],
                            "path": ["login"],
                        },
                    },
                    "event": [],
                }
            ],
        }
    )


def test_validate_postman_collection_json_accepts_fenced_json() -> None:
    cleaned = postman_generator.validate_postman_collection_json(f"```json\n{_postman_json()}\n```")

    parsed = json.loads(cleaned)
    assert parsed["info"]["schema"] == postman_generator.POSTMAN_SCHEMA_URL
    assert parsed["item"][0]["request"]["method"] == "POST"


def test_validate_postman_collection_json_rejects_malformed_json() -> None:
    with pytest.raises(ValueError, match="well-formed"):
        postman_generator.validate_postman_collection_json('{"info": ')


def test_fallback_collection_converts_openapi_endpoint_to_postman_request() -> None:
    collection_json = postman_generator.build_fallback_postman_collection_json(
        _pr_context(),
        _openapi_yaml(),
        "Gemini unavailable",
    )

    collection = json.loads(collection_json)
    request_item = collection["item"][0]
    request = request_item["request"]
    tests = request_item["event"][0]["script"]["exec"]

    assert collection["variable"] == [
        {
            "key": "base_url",
            "value": "https://api.example.test",
            "type": "string",
        }
    ]
    assert request_item["name"] == "loginUser"
    assert request["method"] == "POST"
    assert request["url"]["raw"] == "{{base_url}}/login"
    assert {"key": "Authorization", "value": "Bearer {{auth_token}}"} in request["header"]
    assert {"key": "Content-Type", "value": "application/json"} in request["header"]
    assert json.loads(request["body"]["raw"]) == {
        "email": "admin@example.com",
        "password": "correct-horse-battery-staple",
    }
    assert "const expectedStatusCodes = [200, 400, 401];" in tests


@pytest.mark.asyncio
async def test_generate_postman_collection_returns_internal_notion_embedded_artifact(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_generate(pr_context: PullRequestContext, openapi_yaml: str) -> str:
        assert "openapi: 3.0.3" in openapi_yaml
        return _postman_json()

    async def fake_commit(
        *args: object,
        **kwargs: object,
    ) -> object:
        raise AssertionError("Postman collection should not be committed")

    monkeypatch.setattr(postman_generator, "_generate_postman_collection_with_gemini", fake_generate)

    result = await postman_generator.generate_postman_collection(
        _pr_context(),
        _openapi_yaml(),
        "master",
        artifact_committer=fake_commit,
    )

    assert result.destination == "Embedded in Notion; not committed to repository."
    assert result.target_path == "tests/postman_collection.json"
    assert result.commit_result is None


@pytest.mark.asyncio
async def test_generate_postman_collection_uses_fallback_when_gemini_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_generate(pr_context: PullRequestContext, openapi_yaml: str) -> str:
        raise RuntimeError("Gemini unavailable")

    async def fake_commit(
        *args: object,
        **kwargs: object,
    ) -> object:
        raise AssertionError("Postman fallback collection should not be committed")

    monkeypatch.setattr(postman_generator, "_generate_postman_collection_with_gemini", fake_generate)

    result = await postman_generator.generate_postman_collection(
        _pr_context(),
        _openapi_yaml(),
        "master",
        artifact_committer=fake_commit,
    )

    parsed = json.loads(result.collection_json)
    assert parsed["item"][0]["request"]["method"] == "POST"
    assert "Gemini unavailable" in parsed["info"]["description"]
    assert result.commit_result is None


@pytest.mark.asyncio
async def test_generate_postman_collection_replaces_empty_items_when_openapi_has_operations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_generate(pr_context: PullRequestContext, openapi_yaml: str) -> str:
        return json.dumps(
            {
                "info": {
                    "name": "Empty Collection",
                    "schema": postman_generator.POSTMAN_SCHEMA_URL,
                },
                "item": [],
            }
        )

    async def fake_commit(
        *args: object,
        **kwargs: object,
    ) -> object:
        raise AssertionError("Postman repaired collection should not be committed")

    monkeypatch.setattr(postman_generator, "_generate_postman_collection_with_gemini", fake_generate)

    result = await postman_generator.generate_postman_collection(
        _pr_context(),
        _openapi_yaml(),
        "master",
        artifact_committer=fake_commit,
    )

    parsed = json.loads(result.collection_json)
    assert len(parsed["item"]) == 1
    assert parsed["item"][0]["request"]["method"] == "POST"
    assert postman_generator.count_postman_requests(result.collection_json) == 1


@pytest.mark.asyncio
async def test_generate_postman_collection_ignores_artifact_committer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_commit(
        *args: object,
        **kwargs: object,
    ) -> object:
        raise AssertionError("Postman collection should not be committed")

    monkeypatch.setattr(postman_generator, "_generate_postman_collection_with_gemini", lambda *args: _postman_json())

    result = await postman_generator.generate_postman_collection(
        _pr_context(),
        _openapi_yaml(),
        "master",
        artifact_committer=fake_commit,
    )

    assert result.destination == "Embedded in Notion; not committed to repository."
    assert result.commit_result is None
