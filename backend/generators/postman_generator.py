from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from google import genai
from google.genai import types
from loguru import logger
import yaml

from backend.gemini_config import get_gemini_api_key, get_gemini_api_version, get_gemini_model_candidates
from backend.generators.prompts import POSTMAN_GENERATOR_SYSTEM_PROMPT, POSTMAN_GENERATOR_USER_PROMPT
from backend.github_client import (
    GitHubCommitResult,
    commit_repository_file_text,
    write_local_artifact_backup,
)

if TYPE_CHECKING:
    from backend.pipeline import PullRequestContext

DEFAULT_POSTMAN_MODEL = "gemini-2.5-flash-lite"
FALLBACK_POSTMAN_MODEL = "gemini-2.5-flash"
TARGET_REPO_POSTMAN_PATH = "tests/postman_collection.json"
MAX_OPENAPI_CHARS = 30000
POSTMAN_SCHEMA_URL = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}

ArtifactCommitter = Callable[[str, str, str, str, str, int | None], Awaitable[GitHubCommitResult]]


@dataclass(frozen=True)
class PostmanGenerationResult:
    collection_json: str
    destination: str
    target_path: str
    target_branch: str
    commit_result: GitHubCommitResult | None


async def generate_postman_collection(
    pr_context: PullRequestContext,
    openapi_yaml: str,
    target_branch: str,
    artifact_committer: ArtifactCommitter = commit_repository_file_text,
) -> PostmanGenerationResult:
    target_path = build_target_repo_postman_path()
    logger.info(
        "Postman generation started repo={repo} pr_number={pr_number} branch={branch} path={path}",
        repo=pr_context.repository,
        pr_number=pr_context.pr_number,
        branch=target_branch,
        path=target_path,
    )

    openapi_operation_count = count_openapi_operations(openapi_yaml)
    logger.info("OpenAPI operations available for Postman generation: {count}", count=openapi_operation_count)
    try:
        collection_json = _generate_postman_collection_with_gemini(pr_context, openapi_yaml)
    except Exception as error:
        logger.exception("Postman generation failed; using OpenAPI fallback collection error={error}", error=str(error))
        collection_json = build_fallback_postman_collection_json(pr_context, openapi_yaml, str(error))

    validated_json = validate_postman_collection_json(collection_json).rstrip() + "\n"
    request_count = count_postman_requests(validated_json)
    if request_count == 0 and openapi_operation_count > 0:
        logger.warning(
            "Postman output had no requests despite OpenAPI operations; rebuilding collection from OpenAPI operation_count={count}",
            count=openapi_operation_count,
        )
        validated_json = validate_postman_collection_json(
            build_fallback_postman_collection_json(pr_context, openapi_yaml, "Generated collection had no requests.")
        ).rstrip() + "\n"
        request_count = count_postman_requests(validated_json)

    log_postman_requests(validated_json)
    logger.info(
        "Postman generation completed repo={repo} pr_number={pr_number} final_file_path={path} "
        "char_count={char_count} request_count={request_count}",
        repo=pr_context.repository,
        pr_number=pr_context.pr_number,
        path=target_path,
        char_count=len(validated_json),
        request_count=request_count,
    )

    commit_message = build_postman_commit_message(pr_context)
    try:
        commit_result = await artifact_committer(
            pr_context.repository,
            target_branch,
            target_path,
            validated_json,
            commit_message,
            pr_context.pr_number,
        )
    except Exception as error:
        backup_path = write_local_artifact_backup(pr_context.repository, pr_context.pr_number, target_path, validated_json)
        logger.exception(
            "Unexpected commit failure for Postman artifact repo={repo} branch={branch} final_file_path={path} "
            "local_backup_path={local_backup_path} error={error}",
            repo=pr_context.repository,
            branch=target_branch,
            path=target_path,
            local_backup_path=backup_path,
            error=str(error),
        )
        return PostmanGenerationResult(
            collection_json=validated_json,
            destination=target_path,
            target_path=target_path,
            target_branch=target_branch,
            commit_result=None,
        )

    if not commit_result.success:
        logger.error(
            "Postman commit failed repo={repo} branch={branch} final_file_path={path} local_backup_path={local_backup_path} "
            "error={error}",
            repo=commit_result.repository,
            branch=commit_result.branch,
            path=commit_result.file_path,
            local_backup_path=commit_result.local_backup_path,
            error=commit_result.error_message,
        )
        return PostmanGenerationResult(
            collection_json=validated_json,
            destination=commit_result.file_path,
            target_path=target_path,
            target_branch=target_branch,
            commit_result=commit_result,
        )

    logger.info(
        "Postman commit succeeded repo={repo} branch={branch} final_file_path={path} destination={destination}",
        repo=pr_context.repository,
        branch=target_branch,
        path=target_path,
        destination=commit_result.destination,
    )
    return PostmanGenerationResult(
        collection_json=validated_json,
        destination=commit_result.destination,
        target_path=target_path,
        target_branch=target_branch,
        commit_result=commit_result,
    )


def build_target_repo_postman_path() -> str:
    return TARGET_REPO_POSTMAN_PATH


def build_postman_commit_message(pr_context: PullRequestContext) -> str:
    pr_number = f"#{pr_context.pr_number}" if pr_context.pr_number is not None else "merged PR"
    return f"Add MergeFlow Postman collection for {pr_number}"


def validate_postman_collection_json(collection_json: str) -> str:
    cleaned_json = strip_markdown_fences(collection_json).strip()
    if not cleaned_json:
        raise ValueError("Postman collection JSON is empty")

    try:
        parsed = json.loads(cleaned_json)
    except json.JSONDecodeError as error:
        raise ValueError(f"Postman collection JSON is not well-formed: {error}") from error

    if not isinstance(parsed, dict):
        raise ValueError("Postman collection root must be an object")

    info = parsed.get("info")
    if not isinstance(info, dict) or not info.get("name") or info.get("schema") != POSTMAN_SCHEMA_URL:
        raise ValueError("Postman collection must include info.name and the v2.1 schema URL")

    items = parsed.get("item")
    if not isinstance(items, list):
        raise ValueError("Postman collection must include an item array")

    return json.dumps(parsed, indent=2)


def strip_markdown_fences(text: str) -> str:
    stripped = text.strip()
    fence_match = re.fullmatch(r"```(?:json)?\s*(?P<body>.*?)\s*```", stripped, flags=re.DOTALL | re.IGNORECASE)
    if fence_match:
        return fence_match.group("body").strip()
    return stripped


def build_fallback_postman_collection_json(
    pr_context: PullRequestContext,
    openapi_yaml: str,
    error: str,
) -> str:
    try:
        openapi_document = yaml.safe_load(openapi_yaml) or {}
    except yaml.YAMLError:
        openapi_document = {}

    collection = {
        "info": {
            "name": f"MergeFlow Postman Collection for {pr_context.repository} PR #{pr_context.pr_number}",
            "description": (
                "Generated from the Step 4 OpenAPI YAML. "
                f"Fallback was used because Gemini Postman generation failed: {error}"
            ),
            "schema": POSTMAN_SCHEMA_URL,
        },
        "item": build_postman_items_from_openapi(openapi_document),
        "variable": [
            {
                "key": "base_url",
                "value": first_server_url(openapi_document),
                "type": "string",
            }
        ],
    }
    return json.dumps(collection, indent=2)


def build_postman_items_from_openapi(openapi_document: Any) -> list[dict[str, Any]]:
    if not isinstance(openapi_document, dict):
        return []

    paths = openapi_document.get("paths")
    if not isinstance(paths, dict):
        return []

    items: list[dict[str, Any]] = []
    global_security = openapi_document.get("security")
    for path, path_item in paths.items():
        if not isinstance(path, str) or not isinstance(path_item, dict):
            continue

        path_parameters = _parameters_by_location(path_item.get("parameters"))
        for method, operation in path_item.items():
            if method.lower() not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            operation_for_request = dict(operation)
            if "security" not in operation_for_request and isinstance(global_security, list):
                operation_for_request["security"] = global_security

            operation_parameters = _parameters_by_location(operation_for_request.get("parameters"))
            header_parameters = path_parameters["header"] + operation_parameters["header"]
            query_parameters = path_parameters["query"] + operation_parameters["query"]
            path_parameters_for_request = path_parameters["path"] + operation_parameters["path"]
            response_codes = _response_codes(operation_for_request)

            request: dict[str, Any] = {
                "method": method.upper(),
                "header": _build_headers(operation_for_request, header_parameters),
                "url": _build_url(path, query_parameters, path_parameters_for_request),
            }
            body = _build_body(operation_for_request)
            if body:
                request["body"] = body

            auth = _build_auth(operation_for_request)
            if auth:
                request["auth"] = auth

            items.append(
                {
                    "name": _request_name(path, method, operation_for_request),
                    "request": request,
                    "event": [_build_response_code_test_event(response_codes)],
                    "response": [],
                }
            )

    return items


def count_openapi_operations(openapi_yaml: str) -> int:
    try:
        openapi_document = yaml.safe_load(openapi_yaml) or {}
    except yaml.YAMLError:
        return 0
    if not isinstance(openapi_document, dict):
        return 0

    paths = openapi_document.get("paths")
    if not isinstance(paths, dict):
        return 0
    return sum(
        1
        for path_item in paths.values()
        if isinstance(path_item, dict)
        for method in path_item
        if method.lower() in HTTP_METHODS
    )


def count_postman_requests(collection_json: str) -> int:
    try:
        collection = json.loads(collection_json)
    except json.JSONDecodeError:
        return 0
    items = collection.get("item") if isinstance(collection, dict) else None
    return len(items) if isinstance(items, list) else 0


def log_postman_requests(collection_json: str) -> None:
    try:
        collection = json.loads(collection_json)
    except json.JSONDecodeError:
        logger.warning("Generated Postman requests could not be logged because JSON parsing failed")
        return

    items = collection.get("item") if isinstance(collection, dict) else None
    if not isinstance(items, list):
        logger.info("Generated Postman requests: 0")
        return

    logger.info("Generated Postman requests: {count}", count=len(items))
    for item in items:
        if not isinstance(item, dict):
            continue
        request = item.get("request")
        if not isinstance(request, dict):
            continue
        url = request.get("url")
        raw_url = url.get("raw") if isinstance(url, dict) else ""
        logger.info(
            "Generated Postman request: {method} {url}",
            method=request.get("method", "UNKNOWN"),
            url=raw_url,
        )


def first_server_url(openapi_document: Any) -> str:
    if isinstance(openapi_document, dict):
        servers = openapi_document.get("servers")
        if isinstance(servers, list) and servers:
            server = servers[0]
            if isinstance(server, dict) and isinstance(server.get("url"), str):
                return server["url"]
    return "http://localhost:8000"


def build_postman_prompt(pr_context: PullRequestContext, openapi_yaml: str) -> str:
    return POSTMAN_GENERATOR_USER_PROMPT.format(
        repository=pr_context.repository,
        pr_number=pr_context.pr_number,
        title=pr_context.title,
        openapi_yaml=openapi_yaml[:MAX_OPENAPI_CHARS],
    )


def _generate_postman_collection_with_gemini(pr_context: PullRequestContext, openapi_yaml: str) -> str:
    api_key = get_gemini_api_key()
    api_version = get_gemini_api_version()
    models = get_gemini_model_candidates()
    logger.info(
        "Configuring Gemini Postman generator api_version={api_version} models={models}",
        api_version=api_version,
        models=models,
    )

    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(api_version=api_version),
    )
    prompt = build_postman_prompt(pr_context, openapi_yaml)
    config = types.GenerateContentConfig(
        system_instruction=POSTMAN_GENERATOR_SYSTEM_PROMPT,
        max_output_tokens=8000,
        temperature=0,
    )

    last_error: Exception | None = None
    for model_name in models:
        logger.info("Using Gemini Postman generator model model={model}", model=model_name)
        try:
            response = client.models.generate_content(model=model_name, contents=prompt, config=config)
            collection_json = _extract_response_text(response)
            return validate_postman_collection_json(collection_json)
        except Exception as error:
            last_error = error
            if _should_try_fallback_model(error, model_name, models):
                logger.warning(
                    "Gemini Postman model failed, trying fallback model={model} error={error}",
                    model=model_name,
                    error=str(error),
                )
                continue
            raise

    if last_error:
        raise last_error
    raise RuntimeError("No Gemini Postman generator models were attempted")


def _parameters_by_location(parameters: Any) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {"query": [], "path": [], "header": []}
    if not isinstance(parameters, list):
        return grouped

    for parameter in parameters:
        if not isinstance(parameter, dict):
            continue
        location = parameter.get("in")
        if location in grouped:
            grouped[location].append(parameter)
    return grouped


def _build_headers(operation: dict[str, Any], header_parameters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    headers = [
        {
            "key": str(parameter.get("name", "")),
            "value": str(_example_value(parameter) or ""),
            "description": str(parameter.get("description", "")),
        }
        for parameter in header_parameters
        if parameter.get("name")
    ]

    if _request_body_json_content(operation) is not None and not any(header["key"].lower() == "content-type" for header in headers):
        headers.append({"key": "Content-Type", "value": "application/json"})

    if _operation_has_security(operation) and not any(header["key"].lower() == "authorization" for header in headers):
        headers.append({"key": "Authorization", "value": "Bearer {{auth_token}}"})

    return headers


def _build_url(
    path: str,
    query_parameters: list[dict[str, Any]],
    path_parameters: list[dict[str, Any]],
) -> dict[str, Any]:
    postman_path = _openapi_path_to_postman_path(path)
    url: dict[str, Any] = {
        "raw": "{{base_url}}" + postman_path,
        "host": ["{{base_url}}"],
        "path": [segment for segment in postman_path.lstrip("/").split("/") if segment],
    }

    query = [
        {
            "key": str(parameter.get("name", "")),
            "value": str(_example_value(parameter) or ""),
            "description": str(parameter.get("description", "")),
        }
        for parameter in query_parameters
        if parameter.get("name")
    ]
    if query:
        url["query"] = query

    variables = [
        {
            "key": str(parameter.get("name", "")),
            "value": str(_example_value(parameter) or ""),
            "description": str(parameter.get("description", "")),
        }
        for parameter in path_parameters
        if parameter.get("name")
    ]
    if variables:
        url["variable"] = variables

    return url


def _build_body(operation: dict[str, Any]) -> dict[str, Any] | None:
    json_content = _request_body_json_content(operation)
    if not isinstance(json_content, dict):
        return None

    example = json_content.get("example")
    if example is None:
        examples = json_content.get("examples")
        if isinstance(examples, dict) and examples:
            first_example = next(iter(examples.values()))
            if isinstance(first_example, dict):
                example = first_example.get("value")

    if example is None:
        example = _example_from_schema(json_content.get("schema"))

    return {
        "mode": "raw",
        "raw": json.dumps(example if example is not None else {}, indent=2),
        "options": {"raw": {"language": "json"}},
    }


def _build_auth(operation: dict[str, Any]) -> dict[str, Any] | None:
    if not _operation_has_security(operation):
        return None

    return {
        "type": "bearer",
        "bearer": [
            {
                "key": "token",
                "value": "{{auth_token}}",
                "type": "string",
            }
        ],
    }


def _build_response_code_test_event(response_codes: list[int]) -> dict[str, Any]:
    expected_codes = response_codes or [200]
    return {
        "listen": "test",
        "script": {
            "type": "text/javascript",
            "exec": [
                f"const expectedStatusCodes = {json.dumps(expected_codes)};",
                'pm.test("response code is documented", function () {',
                "  pm.expect(expectedStatusCodes).to.include(pm.response.code);",
                "});",
            ],
        },
    }


def _request_name(path: str, method: str, operation: dict[str, Any]) -> str:
    for key in ("operationId", "summary"):
        value = operation.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return f"{method.upper()} {path}"


def _response_codes(operation: dict[str, Any]) -> list[int]:
    responses = operation.get("responses")
    if not isinstance(responses, dict):
        return [200]

    codes: list[int] = []
    for code in responses:
        try:
            codes.append(int(str(code)))
        except ValueError:
            continue
    return codes or [200]


def _request_body_json_content(operation: dict[str, Any]) -> Any:
    request_body = operation.get("requestBody")
    if not isinstance(request_body, dict):
        return None

    content = request_body.get("content")
    if not isinstance(content, dict):
        return None

    return content.get("application/json")


def _operation_has_security(operation: dict[str, Any]) -> bool:
    security = operation.get("security")
    return isinstance(security, list) and bool(security)


def _openapi_path_to_postman_path(path: str) -> str:
    return re.sub(r"\{([^}/]+)\}", r":\1", path)


def _example_value(parameter: dict[str, Any]) -> Any:
    if "example" in parameter:
        return parameter["example"]

    schema = parameter.get("schema")
    if isinstance(schema, dict):
        if "example" in schema:
            return schema["example"]
        return _example_from_schema(schema)

    return ""


def _example_from_schema(schema: Any) -> Any:
    if not isinstance(schema, dict):
        return {}

    if "example" in schema:
        return schema["example"]

    schema_type = schema.get("type")
    if schema_type == "object":
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            return {}
        return {key: _example_from_schema(value) for key, value in properties.items()}
    if schema_type == "array":
        return [_example_from_schema(schema.get("items"))]
    if schema_type == "integer":
        return 1
    if schema_type == "number":
        return 1.0
    if schema_type == "boolean":
        return True
    if schema_type == "string":
        fmt = schema.get("format")
        if fmt == "email":
            return "user@example.com"
        if fmt == "date-time":
            return "2026-06-05T00:00:00Z"
        return "string"

    return {}


def _should_try_fallback_model(error: Exception, model_name: str, models: list[str]) -> bool:
    if model_name == models[-1]:
        return False

    error_text = str(error).lower()
    return any(
        marker in error_text
        for marker in (
            "not found",
            "not supported",
            "invalid model",
            "model is not",
            "404",
            "429",
            "quota",
            "resource_exhausted",
        )
    )


def _extract_response_text(response: object) -> str:
    text = getattr(response, "text", "")
    if isinstance(text, str):
        return text.strip()
    return ""
