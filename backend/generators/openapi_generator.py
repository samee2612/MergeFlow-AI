from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from google import genai
from google.genai import types
from loguru import logger
import yaml

from backend.classifier.diff_classifier import BackendDiffClassification
from backend.gemini_config import get_gemini_api_key, get_gemini_api_version, get_gemini_model_candidates
from backend.generators.prompts import OPENAPI_GENERATOR_SYSTEM_PROMPT, OPENAPI_GENERATOR_USER_PROMPT
from backend.github_client import (
    GitHubCommitResult,
    commit_repository_file_text,
)

if TYPE_CHECKING:
    from backend.pipeline import PullRequestContext

DEFAULT_OPENAPI_MODEL = "gemini-2.5-flash-lite"
FALLBACK_OPENAPI_MODEL = "gemini-2.5-flash"
TARGET_REPO_OPENAPI_PATH = "tests/openapi.yaml"
MAX_API_ANALYSIS_CHARS = 30000

ArtifactCommitter = Callable[[str, str, str, str, str, int | None], Awaitable[GitHubCommitResult]]


@dataclass(frozen=True)
class OpenApiGenerationResult:
    yaml_content: str
    destination: str
    target_path: str
    target_branch: str
    commit_result: GitHubCommitResult | None


@dataclass(frozen=True)
class DetectedEndpoint:
    method: str
    path: str
    operation_name: str
    summary: str
    request_schema: str | None
    response_schema: str | None
    response_codes: list[int]
    headers: list[dict[str, Any]]


async def generate_openapi_yaml(
    pr_context: PullRequestContext,
    classification: BackendDiffClassification,
    api_analysis_markdown: str,
    target_branch: str,
    artifact_committer: ArtifactCommitter = commit_repository_file_text,
) -> OpenApiGenerationResult:
    del artifact_committer  # OpenAPI is embedded into Notion, not committed as a repo artifact.

    target_path = build_target_repo_openapi_path()
    logger.info(
        "OpenAPI generation started repo={repo} pr_number={pr_number} branch={branch} path={path}",
        repo=pr_context.repository,
        pr_number=pr_context.pr_number,
        branch=target_branch,
        path=target_path,
    )

    detected_endpoints = detect_endpoints(api_analysis_markdown)
    detected_schemas = detect_schema_names(api_analysis_markdown)
    log_detected_endpoints(detected_endpoints, detected_schemas)

    try:
        openapi_yaml = _generate_openapi_yaml_with_gemini(pr_context, classification, api_analysis_markdown)
    except Exception as error:
        logger.exception("OpenAPI generation failed; using deterministic fallback YAML error={error}", error=str(error))
        openapi_yaml = build_fallback_openapi_yaml(pr_context, classification, str(error), api_analysis_markdown)

    validated_yaml = validate_openapi_yaml(openapi_yaml).rstrip() + "\n"
    generated_path_count = count_openapi_paths(validated_yaml)
    if generated_path_count == 0 and detected_endpoints:
        logger.warning(
            "OpenAPI output had no paths despite detected endpoints; rebuilding from source context detected_endpoints={count}",
            count=len(detected_endpoints),
        )
        validated_yaml = validate_openapi_yaml(
            build_openapi_yaml_from_detected_endpoints(pr_context, classification, detected_endpoints, api_analysis_markdown)
        ).rstrip() + "\n"
        generated_path_count = count_openapi_paths(validated_yaml)

    log_generated_openapi_paths(validated_yaml)
    logger.info(
        "OpenAPI generation completed repo={repo} pr_number={pr_number} final_file_path={path} "
        "char_count={char_count} generated_path_count={generated_path_count}",
        repo=pr_context.repository,
        pr_number=pr_context.pr_number,
        path=target_path,
        char_count=len(validated_yaml),
        generated_path_count=generated_path_count,
    )

    logger.info(
        "OpenAPI generated as internal Notion-embedded artifact repo={repo} branch={branch} final_file_path={path}",
        repo=pr_context.repository,
        branch=target_branch,
        path=target_path,
    )
    return OpenApiGenerationResult(
        yaml_content=validated_yaml,
        destination="Embedded in Notion; not committed to repository.",
        target_path=target_path,
        target_branch=target_branch,
        commit_result=None,
    )


def build_target_repo_openapi_path() -> str:
    return TARGET_REPO_OPENAPI_PATH


def build_openapi_commit_message(pr_context: PullRequestContext) -> str:
    pr_number = f"#{pr_context.pr_number}" if pr_context.pr_number is not None else "merged PR"
    return f"Add MergeFlow OpenAPI spec for {pr_number}"


def validate_openapi_yaml(openapi_yaml: str) -> str:
    cleaned_yaml = strip_markdown_fences(openapi_yaml).strip()
    if not cleaned_yaml:
        raise ValueError("OpenAPI YAML is empty")

    try:
        parsed = yaml.safe_load(cleaned_yaml)
    except yaml.YAMLError as error:
        raise ValueError(f"OpenAPI YAML is not well-formed: {error}") from error

    if not isinstance(parsed, dict):
        raise ValueError("OpenAPI YAML root must be an object")

    openapi_version = parsed.get("openapi")
    if not isinstance(openapi_version, str) or not openapi_version.startswith("3.0"):
        raise ValueError("OpenAPI YAML must declare an OpenAPI 3.0 version")

    info = parsed.get("info")
    if not isinstance(info, dict) or not info.get("title") or not info.get("version"):
        raise ValueError("OpenAPI YAML must include info.title and info.version")

    paths = parsed.get("paths")
    if not isinstance(paths, dict):
        raise ValueError("OpenAPI YAML must include a paths object")

    return cleaned_yaml


def strip_markdown_fences(text: str) -> str:
    stripped = text.strip()
    fence_match = re.fullmatch(r"```(?:yaml|yml)?\s*(?P<body>.*?)\s*```", stripped, flags=re.DOTALL | re.IGNORECASE)
    if fence_match:
        return fence_match.group("body").strip()
    return stripped


def build_fallback_openapi_yaml(
    pr_context: PullRequestContext,
    classification: BackendDiffClassification,
    error: str,
    api_analysis_markdown: str = "",
) -> str:
    detected_endpoints = detect_endpoints(api_analysis_markdown)
    if detected_endpoints:
        return build_openapi_yaml_from_detected_endpoints(
            pr_context,
            classification,
            detected_endpoints,
            api_analysis_markdown,
            generator_error=error,
        )

    payload: dict[str, Any] = {
        "openapi": "3.0.3",
        "info": {
            "title": f"MergeFlow API Spec for {pr_context.repository} PR #{pr_context.pr_number}",
            "version": "0.1.0",
            "description": (
                "Minimal valid OpenAPI fallback generated because Gemini OpenAPI generation failed. "
                "Endpoint-level details were not detected from Step 3 analysis."
            ),
        },
        "paths": {},
        "x-mergeflow": {
            "repository": pr_context.repository,
            "pr_number": pr_context.pr_number,
            "title": pr_context.title,
            "classification": list(classification.change_types),
            "classification_summary": classification.summary,
            "generator_error": error,
        },
    }
    return yaml.safe_dump(payload, sort_keys=False)


def detect_endpoints(source_text: str) -> list[DetectedEndpoint]:
    endpoints: list[DetectedEndpoint] = []
    lines = source_text.splitlines()
    for index, line in enumerate(lines):
        route_match = re.search(r"@(?:router|app)\.(get|post|put|patch|delete)\(", line)
        if not route_match:
            continue

        decorator_block = [line]
        function_line = ""
        for next_line in lines[index + 1 :]:
            stripped = next_line.strip()
            if stripped.startswith("def "):
                function_line = stripped
                break
            decorator_block.append(next_line)

        block_text = "\n".join(decorator_block)
        path = _first_regex_group(block_text, r"[\"']([^\"']*/[^\"']*)[\"']")
        if not path:
            continue
        function_match = re.search(r"def\s+(?P<name>\w+)\((?P<params>.*?)\)\s*(?:->\s*(?P<return_type>\w+))?", function_line)
        operation_name = function_match.group("name") if function_match else f"{route_match.group(1)}_{path.strip('/').replace('/', '_') or 'root'}"
        response_schema = _first_regex_group(block_text, r"response_model\s*=\s*(\w+)") or (
            function_match.group("return_type") if function_match and function_match.group("return_type") else None
        )
        request_schema = _first_regex_group(function_line, r"request\s*=\s*(\w+)\(") or _first_regex_group(source_text, r"request\s*=\s*(\w+)\(")
        response_codes = sorted({int(code) for code in re.findall(r"(?<![\w'\"])(\d{3})\s*:", block_text)})
        if 200 not in response_codes:
            response_codes.insert(0, 200)

        endpoints.append(
            DetectedEndpoint(
                method=route_match.group(1).upper(),
                path=path,
                operation_name=operation_name,
                summary=_first_regex_group(block_text, r"summary\s*=\s*[\"']([^\"']+)[\"']") or operation_name.replace("_", " ").title(),
                request_schema=request_schema,
                response_schema=response_schema,
                response_codes=response_codes,
                headers=_detect_header_parameters(source_text),
            )
        )

    return _dedupe_endpoints(endpoints)


def detect_schema_names(source_text: str) -> list[str]:
    return _dedupe_preserving_order(re.findall(r"^class\s+(\w+)\(BaseModel\):", source_text, flags=re.MULTILINE))


def build_openapi_yaml_from_detected_endpoints(
    pr_context: PullRequestContext,
    classification: BackendDiffClassification,
    endpoints: list[DetectedEndpoint],
    source_text: str,
    generator_error: str | None = None,
) -> str:
    schema_definitions = detect_pydantic_schemas(source_text)
    paths: dict[str, Any] = {}

    for endpoint in endpoints:
        operation: dict[str, Any] = {
            "summary": endpoint.summary,
            "operationId": endpoint.operation_name,
            "tags": [_tag_from_path(endpoint.path)],
            "parameters": endpoint.headers,
            "responses": build_openapi_responses(endpoint, schema_definitions),
        }

        request_schema = schema_definitions.get(endpoint.request_schema or "")
        if request_schema:
            operation["requestBody"] = {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"$ref": f"#/components/schemas/{endpoint.request_schema}"},
                        "example": build_example_from_schema(request_schema),
                    }
                },
            }

        if _looks_auth_related(endpoint, classification):
            operation["security"] = [{"bearerAuth": []}]

        paths.setdefault(endpoint.path, {})[endpoint.method.lower()] = operation

    payload: dict[str, Any] = {
        "openapi": "3.0.3",
        "info": {
            "title": f"MergeFlow API Spec for {pr_context.repository} PR #{pr_context.pr_number}",
            "version": "0.1.0",
            "description": "Generated from MergeFlow Step 3 source context and backend diff evidence.",
        },
        "servers": [{"url": "{{base_url}}"}],
        "paths": paths,
        "components": {
            "schemas": schema_definitions,
            "securitySchemes": {
                "bearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "JWT",
                }
            },
        },
        "x-mergeflow": {
            "repository": pr_context.repository,
            "pr_number": pr_context.pr_number,
            "title": pr_context.title,
            "classification": list(classification.change_types),
            "classification_summary": classification.summary,
        },
    }
    env_vars = sorted(set(re.findall(r"os\.getenv\([\"']([A-Z0-9_]+)[\"']", source_text)))
    if env_vars:
        payload["x-mergeflow-env-vars"] = env_vars
    if generator_error:
        payload["x-mergeflow"]["generator_error"] = generator_error

    return yaml.safe_dump(payload, sort_keys=False)


def detect_pydantic_schemas(source_text: str) -> dict[str, dict[str, Any]]:
    schemas: dict[str, dict[str, Any]] = {}
    matches = list(re.finditer(r"^class\s+(?P<name>\w+)\(BaseModel\):", source_text, flags=re.MULTILINE))
    for index, match in enumerate(matches):
        schema_name = match.group("name")
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(source_text)
        class_body = source_text[start:end]
        properties: dict[str, Any] = {}
        required: list[str] = []

        for field_match in re.finditer(r"^\s{4}(?P<name>\w+):\s*(?P<type>[\w\[\] |]+)(?:\s*=\s*Field\((?P<field_args>.*?)\))?", class_body, flags=re.MULTILINE | re.DOTALL):
            field_name = field_match.group("name")
            field_type = field_match.group("type").strip()
            field_args = field_match.group("field_args") or ""
            property_schema = _schema_for_python_type(field_type)
            description = _first_regex_group(field_args, r"description\s*=\s*[\"']([^\"']+)[\"']")
            if description:
                property_schema["description"] = description
            example = _extract_field_example(field_args)
            if example is not None:
                property_schema["example"] = example
            properties[field_name] = property_schema
            if field_args.strip().startswith("...") or not field_args:
                required.append(field_name)

        schemas[schema_name] = {
            "type": "object",
            "properties": properties,
        }
        if required:
            schemas[schema_name]["required"] = required

    return schemas


def build_openapi_responses(endpoint: DetectedEndpoint, schemas: dict[str, dict[str, Any]]) -> dict[str, Any]:
    responses: dict[str, Any] = {}
    for code in endpoint.response_codes:
        is_success = 200 <= code < 300
        schema_name = endpoint.response_schema if is_success else "ErrorResponse"
        response: dict[str, Any] = {"description": _response_description(code)}
        if schema_name in schemas:
            response["content"] = {
                "application/json": {
                    "schema": {"$ref": f"#/components/schemas/{schema_name}"},
                    "example": build_example_from_schema(schemas[schema_name]),
                }
            }
        responses[str(code)] = response
    return responses


def build_example_from_schema(schema: dict[str, Any]) -> dict[str, Any]:
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return {}

    return {field_name: _example_for_property(property_schema) for field_name, property_schema in properties.items()}


def count_openapi_paths(openapi_yaml: str) -> int:
    try:
        parsed = yaml.safe_load(openapi_yaml) or {}
    except yaml.YAMLError:
        return 0
    paths = parsed.get("paths") if isinstance(parsed, dict) else None
    if not isinstance(paths, dict):
        return 0
    return sum(
        1
        for path_item in paths.values()
        if isinstance(path_item, dict)
        for method in path_item
        if method.lower() in {"get", "post", "put", "patch", "delete"}
    )


def log_detected_endpoints(endpoints: list[DetectedEndpoint], schema_names: list[str]) -> None:
    logger.info("Detected endpoints: {count}", count=len(endpoints))
    for endpoint in endpoints:
        logger.info("Detected path: {method} {path}", method=endpoint.method, path=endpoint.path)
    logger.info("Schemas detected: {schemas}", schemas=schema_names or "none")


def log_generated_openapi_paths(openapi_yaml: str) -> None:
    try:
        parsed = yaml.safe_load(openapi_yaml) or {}
    except yaml.YAMLError:
        logger.warning("Generated OpenAPI paths could not be logged because YAML parsing failed")
        return
    paths = parsed.get("paths") if isinstance(parsed, dict) else None
    if not isinstance(paths, dict):
        logger.info("Generated OpenAPI paths: 0")
        return

    generated = [
        (method.upper(), path)
        for path, path_item in paths.items()
        if isinstance(path_item, dict)
        for method in path_item
        if method.lower() in {"get", "post", "put", "patch", "delete"}
    ]
    logger.info("Generated OpenAPI paths: {count}", count=len(generated))
    for method, path in generated:
        logger.info("Generated OpenAPI path: {method} {path}", method=method, path=path)


def _detect_header_parameters(source_text: str) -> list[dict[str, Any]]:
    headers: list[dict[str, Any]] = []
    for header_match in re.finditer(r"(?P<var>\w+):.*?Header\((?P<args>.*?)\)", source_text, flags=re.DOTALL):
        header_args = header_match.group("args")
        header_name = _first_regex_group(header_args, r"alias\s*=\s*[\"']([^\"']+)[\"']") or header_match.group("var").replace("_", "-")
        headers.append(
            {
                "name": header_name,
                "in": "header",
                "required": not header_args.strip().startswith("default=None"),
                "description": _first_regex_group(header_args, r"description\s*=\s*[\"']([^\"']+)[\"']") or "",
                "schema": {"type": "string"},
                "example": _extract_field_example(header_args) or "",
            }
        )
    return headers


def _schema_for_python_type(python_type: str) -> dict[str, Any]:
    normalized_type = python_type.replace(" ", "")
    if "EmailStr" in normalized_type:
        return {"type": "string", "format": "email"}
    if normalized_type in {"str", "StrictStr"}:
        return {"type": "string"}
    if normalized_type in {"int", "StrictInt"}:
        return {"type": "integer"}
    if normalized_type in {"float", "Decimal"}:
        return {"type": "number"}
    if normalized_type in {"bool", "StrictBool"}:
        return {"type": "boolean"}
    if normalized_type.startswith("list[") or normalized_type.startswith("List["):
        return {"type": "array", "items": {"type": "string"}}
    return {"type": "string"}


def _extract_field_example(field_args: str) -> Any:
    example_match = re.search(r"example\s*=\s*(?P<value>[^,\n)]+)", field_args)
    if not example_match:
        return None
    raw_value = example_match.group("value").strip()
    if raw_value in {"True", "False"}:
        return raw_value == "True"
    if raw_value.startswith(("\"", "'")) and raw_value.endswith(("\"", "'")):
        return raw_value[1:-1]
    try:
        return int(raw_value)
    except ValueError:
        return raw_value


def _example_for_property(property_schema: dict[str, Any]) -> Any:
    if "example" in property_schema:
        return property_schema["example"]
    property_type = property_schema.get("type")
    if property_schema.get("format") == "email":
        return "user@example.com"
    if property_type == "string":
        return "string"
    if property_type == "integer":
        return 1
    if property_type == "number":
        return 1.0
    if property_type == "boolean":
        return True
    if property_type == "array":
        return []
    return {}


def _response_description(status_code: int) -> str:
    return {
        200: "Successful response",
        201: "Created",
        400: "Missing or invalid request body",
        401: "Invalid credentials or unauthorized request",
        403: "Forbidden",
        404: "Not found",
        409: "Conflict",
        422: "Validation error",
        500: "Internal server error",
    }.get(status_code, f"HTTP {status_code} response")


def _tag_from_path(path: str) -> str:
    first_segment = path.strip("/").split("/", 1)[0]
    return first_segment.replace("-", " ").title() if first_segment else "API"


def _looks_auth_related(endpoint: DetectedEndpoint, classification: BackendDiffClassification) -> bool:
    haystack = " ".join(
        [
            endpoint.path,
            endpoint.operation_name,
            endpoint.summary,
            " ".join(classification.change_types),
            classification.summary,
        ]
    ).lower()
    return any(marker in haystack for marker in ("auth", "login", "token", "credential"))


def _first_regex_group(source_text: str, pattern: str) -> str | None:
    match = re.search(pattern, source_text, flags=re.DOTALL)
    return match.group(1) if match else None


def _dedupe_endpoints(endpoints: list[DetectedEndpoint]) -> list[DetectedEndpoint]:
    seen: set[tuple[str, str]] = set()
    deduped: list[DetectedEndpoint] = []
    for endpoint in endpoints:
        key = (endpoint.method, endpoint.path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(endpoint)
    return deduped


def _dedupe_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def build_openapi_prompt(
    pr_context: PullRequestContext,
    classification: BackendDiffClassification,
    api_analysis_markdown: str,
) -> str:
    return OPENAPI_GENERATOR_USER_PROMPT.format(
        repository=pr_context.repository,
        pr_number=pr_context.pr_number,
        title=pr_context.title,
        classification=", ".join(classification.change_types),
        classification_summary=classification.summary,
        api_analysis_markdown=api_analysis_markdown[:MAX_API_ANALYSIS_CHARS],
    )


def _generate_openapi_yaml_with_gemini(
    pr_context: PullRequestContext,
    classification: BackendDiffClassification,
    api_analysis_markdown: str,
) -> str:
    api_key = get_gemini_api_key()
    api_version = get_gemini_api_version()
    models = get_gemini_model_candidates()
    logger.info(
        "Configuring Gemini OpenAPI generator api_version={api_version} models={models}",
        api_version=api_version,
        models=models,
    )

    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(api_version=api_version),
    )
    prompt = build_openapi_prompt(pr_context, classification, api_analysis_markdown)
    config = types.GenerateContentConfig(
        system_instruction=OPENAPI_GENERATOR_SYSTEM_PROMPT,
        max_output_tokens=6000,
        temperature=0,
    )

    last_error: Exception | None = None
    for model_name in models:
        logger.info("Using Gemini OpenAPI generator model model={model}", model=model_name)
        try:
            response = client.models.generate_content(model=model_name, contents=prompt, config=config)
            openapi_yaml = _extract_response_text(response)
            return validate_openapi_yaml(openapi_yaml)
        except Exception as error:
            last_error = error
            if _should_try_fallback_model(error, model_name, models):
                logger.warning(
                    "Gemini OpenAPI model failed, trying fallback model={model} error={error}",
                    model=model_name,
                    error=str(error),
                )
                continue
            raise

    if last_error:
        raise last_error
    raise RuntimeError("No Gemini OpenAPI generator models were attempted")


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
