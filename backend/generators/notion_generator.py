from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any, Protocol

import httpx
from loguru import logger
import yaml

from backend.run_store import run_id_for, update_run

if TYPE_CHECKING:
    from backend.classifier.diff_classifier import BackendDiffClassification
    from backend.generators.api_spec_generator import ApiSpecGenerationResult
    from backend.generators.openapi_generator import OpenApiGenerationResult
    from backend.generators.postman_generator import PostmanGenerationResult
    from backend.pipeline import PullRequestContext


NOTION_API_BASE_URL = "https://api.notion.com/v1"
NOTION_API_VERSION = "2022-06-28"
DEFAULT_NOTION_TITLE_PROPERTY = "Name"
MAX_NOTION_TEXT_CHARS = 1800
MAX_BLOCKS_PER_APPEND = 100


@dataclass(frozen=True)
class NotionSettings:
    api_key: str
    root_page_id: str


@dataclass(frozen=True)
class NotionPageRef:
    page_id: str
    page_url: str


@dataclass(frozen=True)
class NotionSyncResult:
    success: bool
    action: str
    page_id: str | None = None
    page_url: str | None = None
    error_message: str | None = None
    metadata_path: str | None = None


class NotionPageClient(Protocol):
    async def find_page_by_title(self, database_id: str, title_property: str, title: str) -> NotionPageRef | None:
        ...

    async def create_page(
        self,
        database_id: str,
        title_property: str,
        title: str,
        blocks: list[dict[str, Any]],
    ) -> NotionPageRef:
        ...

    async def update_page(
        self,
        page_id: str,
        title_property: str,
        title: str,
        blocks: list[dict[str, Any]],
    ) -> NotionPageRef:
        ...


class NotionApiClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    async def find_page_by_title(self, database_id: str, title_property: str, title: str) -> NotionPageRef | None:
        payload = {
            "filter": {
                "property": title_property,
                "title": {
                    "equals": title,
                },
            },
            "page_size": 1,
        }
        response_payload = await self._request("POST", f"/databases/{database_id}/query", json_payload=payload)
        results = response_payload.get("results")
        if not isinstance(results, list) or not results:
            return None

        page = results[0]
        if not isinstance(page, dict):
            return None
        return _page_ref_from_payload(page)

    async def create_page(
        self,
        database_id: str,
        title_property: str,
        title: str,
        blocks: list[dict[str, Any]],
    ) -> NotionPageRef:
        payload = {
            "parent": {"database_id": database_id},
            "properties": {
                title_property: {
                    "title": [_rich_text(title)],
                },
            },
            "children": blocks[:MAX_BLOCKS_PER_APPEND],
        }
        response_payload = await self._request("POST", "/pages", json_payload=payload)
        page_ref = _page_ref_from_payload(response_payload)
        await self._append_children(page_ref.page_id, blocks[MAX_BLOCKS_PER_APPEND:])
        return page_ref

    async def update_page(
        self,
        page_id: str,
        title_property: str,
        title: str,
        blocks: list[dict[str, Any]],
    ) -> NotionPageRef:
        response_payload = await self._request(
            "PATCH",
            f"/pages/{page_id}",
            json_payload={
                "properties": {
                    title_property: {
                        "title": [_rich_text(title)],
                    },
                },
            },
        )
        await self._replace_children(page_id, blocks)
        return _page_ref_from_payload(response_payload)

    async def _replace_children(self, page_id: str, blocks: list[dict[str, Any]]) -> None:
        for child_id in await self._list_replaceable_child_block_ids(page_id):
            await self._request("PATCH", f"/blocks/{child_id}", json_payload={"archived": True})
        await self._append_children(page_id, blocks)

    async def _append_children(self, page_id: str, blocks: list[dict[str, Any]]) -> None:
        for start in range(0, len(blocks), MAX_BLOCKS_PER_APPEND):
            chunk = blocks[start : start + MAX_BLOCKS_PER_APPEND]
            if not chunk:
                continue
            await self._request("PATCH", f"/blocks/{page_id}/children", json_payload={"children": chunk})

    async def _list_replaceable_child_block_ids(self, page_id: str) -> list[str]:
        child_ids: list[str] = []
        next_cursor: str | None = None
        while True:
            params = {"page_size": 100}
            if next_cursor:
                params["start_cursor"] = next_cursor

            response_payload = await self._request("GET", f"/blocks/{page_id}/children", params=params)
            results = response_payload.get("results")
            if isinstance(results, list):
                child_ids.extend(
                    str(block["id"])
                    for block in results
                    if (
                        isinstance(block, dict)
                        and isinstance(block.get("id"), str)
                        and block.get("type") != "child_page"
                    )
                )

            next_cursor_value = response_payload.get("next_cursor")
            if not response_payload.get("has_more") or not isinstance(next_cursor_value, str):
                return child_ids
            next_cursor = next_cursor_value

    async def _request(
        self,
        method: str,
        path: str,
        json_payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.request(
                method,
                f"{NOTION_API_BASE_URL}{path}",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "Notion-Version": NOTION_API_VERSION,
                },
                json=json_payload,
                params=params,
            )

        if response.is_error:
            raise RuntimeError(f"Notion API {method} {path} failed with status {response.status_code}: {response.text}")

        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError(f"Notion API {method} {path} returned a non-object response")
        return payload


class NotionHierarchyClient(NotionApiClient):
    async def find_child_page_by_title(self, parent_page_id: str, title: str) -> NotionPageRef | None:
        async for block in self._iter_block_children(parent_page_id):
            if block.get("type") != "child_page":
                continue
            child_page = block.get("child_page")
            if not isinstance(child_page, dict):
                continue
            child_title = child_page.get("title")
            if isinstance(child_title, str) and child_title == title:
                block_id = block.get("id")
                if isinstance(block_id, str):
                    page_payload = await self._request("GET", f"/pages/{block_id}")
                    return _page_ref_from_payload(page_payload)
        return None

    async def create_child_page(self, parent_page_id: str, title: str, blocks: list[dict[str, Any]]) -> NotionPageRef:
        payload = {
            "parent": {"page_id": parent_page_id},
            "properties": {
                "title": {
                    "title": [{"type": "text", "text": {"content": title[:2000]}}],
                },
            },
            "children": blocks[:MAX_BLOCKS_PER_APPEND],
        }
        response_payload = await self._request("POST", "/pages", json_payload=payload)
        page_ref = _page_ref_from_payload(response_payload)
        await self._append_children(page_ref.page_id, blocks[MAX_BLOCKS_PER_APPEND:])
        return page_ref

    async def update_child_page(self, page_id: str, blocks: list[dict[str, Any]]) -> NotionPageRef:
        await self._replace_children(page_id, blocks)
        page_payload = await self._request("GET", f"/pages/{page_id}")
        return _page_ref_from_payload(page_payload)

    async def get_page_blocks(self, page_id: str) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        async for block in self._iter_block_children(page_id):
            blocks.append(block)
        return blocks

    async def _iter_block_children(self, page_id: str):
        next_cursor: str | None = None
        while True:
            params: dict[str, Any] = {"page_size": 100}
            if next_cursor:
                params["start_cursor"] = next_cursor

            response_payload = await self._request("GET", f"/blocks/{page_id}/children", params=params)
            results = response_payload.get("results")
            if isinstance(results, list):
                for block in results:
                    if isinstance(block, dict):
                        yield block

            next_cursor_value = response_payload.get("next_cursor")
            if not response_payload.get("has_more") or not isinstance(next_cursor_value, str):
                return
            next_cursor = next_cursor_value


async def resolve_service_documentation_page(
    client: NotionHierarchyClient,
    root_page_id: str,
    team_name: str,
    service_name: str,
) -> NotionPageRef:
    team_page = await client.find_child_page_by_title(root_page_id, team_name)
    if team_page is None:
        raise RuntimeError(
            f"Team documentation page not found under Notion root: {team_name!r}. "
            f"Expected a child page of the root page with this exact title."
        )

    service_page = await client.find_child_page_by_title(team_page.page_id, service_name)
    if service_page is None:
        raise RuntimeError(
            f"Service documentation page not found for {service_name!r} under team {team_name!r}. "
            f"Expected a child page of the team page with this exact title."
        )

    return service_page


async def sync_notion_page(
    pr_context: PullRequestContext,
    classification: BackendDiffClassification,
    api_spec_result: ApiSpecGenerationResult,
    openapi_result: OpenApiGenerationResult,
    postman_result: PostmanGenerationResult,
    notion_client: NotionPageClient | None = None,
) -> NotionSyncResult:
    logger.info(
        "Notion sync started repo={repo} pr_number={pr_number}",
        repo=pr_context.repository,
        pr_number=pr_context.pr_number,
    )

    try:
        settings = get_notion_settings()
        title = build_notion_page_title(pr_context)
        blocks = build_notion_page_blocks(
            pr_context,
            classification,
            api_spec_result,
            openapi_result,
            postman_result,
        )
        client = notion_client or NotionHierarchyClient(settings.api_key)
        existing_page = await client.find_child_page_by_title(settings.root_page_id, title)

        if existing_page:
            page_ref = await client.update_child_page(existing_page.page_id, blocks)
            action = "updated"
        else:
            page_ref = await client.create_child_page(settings.root_page_id, title, blocks)
            action = "created"

        result = NotionSyncResult(
            success=True,
            action=action,
            page_id=page_ref.page_id,
            page_url=page_ref.page_url,
        )
        metadata_path = safe_write_notion_run_metadata(pr_context, result)
        result = NotionSyncResult(
            success=True,
            action=action,
            page_id=page_ref.page_id,
            page_url=page_ref.page_url,
            metadata_path=metadata_path,
        )
        logger.info(
            "Notion page {action} repo={repo} pr_number={pr_number} page_id={page_id} page_url={page_url}",
            action=action,
            repo=pr_context.repository,
            pr_number=pr_context.pr_number,
            page_id=page_ref.page_id,
            page_url=page_ref.page_url,
        )
        return result
    except Exception as error:
        error_message = str(error)
        logger.exception(
            "Notion sync failed repo={repo} pr_number={pr_number} reason={reason}",
            repo=pr_context.repository,
            pr_number=pr_context.pr_number,
            reason=error_message,
        )
        result = NotionSyncResult(success=False, action="failed", error_message=error_message)
        metadata_path = safe_write_notion_run_metadata(pr_context, result)
        return NotionSyncResult(
            success=False,
            action="failed",
            error_message=error_message,
            metadata_path=metadata_path,
        )


def get_notion_settings() -> NotionSettings:
    api_key = os.getenv("NOTION_API_KEY", "").strip()
    root_page_id = os.getenv("NOTION_ROOT_PAGE_ID", "").strip()

    missing = [name for name, value in (("NOTION_API_KEY", api_key), ("NOTION_ROOT_PAGE_ID", root_page_id)) if not value]
    if missing:
        raise RuntimeError(f"Missing Notion configuration: {', '.join(missing)}")

    return NotionSettings(api_key=api_key, root_page_id=root_page_id)


def build_notion_page_title(pr_context: PullRequestContext) -> str:
    repo_name = pr_context.repository.split("/")[-1] if pr_context.repository else "unknown-repo"
    pr_number = pr_context.pr_number if pr_context.pr_number is not None else "unknown"
    return f"MergeFlow - {repo_name} - PR #{pr_number}"


def build_notion_page_blocks(
    pr_context: PullRequestContext,
    classification: BackendDiffClassification,
    api_spec_result: ApiSpecGenerationResult,
    openapi_result: OpenApiGenerationResult,
    postman_result: PostmanGenerationResult,
) -> list[dict[str, Any]]:
    openapi_summary = summarize_openapi(openapi_result.yaml_content)
    postman_summary = summarize_postman_collection(postman_result.collection_json)
    api_summary = extract_markdown_section(api_spec_result.markdown, "Change Summary")
    endpoint_details = extract_markdown_section(api_spec_result.markdown, "Endpoint(s) Detected") or extract_markdown_section(
        api_spec_result.markdown,
        "API Specification Snapshot",
    )
    test_cases = extract_markdown_section(api_spec_result.markdown, "Test Cases")

    blocks: list[dict[str, Any]] = [
        _heading_1("MergeFlow API Change Summary"),
        *_bullets(
            [
                f"Repository: {pr_context.repository}",
                f"PR number: {pr_context.pr_number}",
                f"PR title: {pr_context.title}",
                f"Author: {pr_context.author or 'Unknown'}",
                f"Merged at: {pr_context.merged_at or 'Unknown'}",
            ]
        ),
        _heading_2("Classification Summary"),
        *_bullets([f"Change type: {change_type}" for change_type in classification.change_types]),
        *_paragraphs(classification.summary or "No classification summary was generated."),
        _heading_2("API Summary"),
        *_paragraphs(api_summary or "No API summary was detected in the Step 3 output."),
        _heading_2("Endpoint Details"),
        *_paragraphs(endpoint_details or "No endpoint details were detected in the Step 3 output."),
        *_bullets(openapi_summary.endpoint_lines),
        _heading_2("Test Cases"),
        *_paragraphs(test_cases or "No test cases were detected in the Step 3 output."),
        _heading_2("OpenAPI Summary"),
        *_bullets(
            [
                f"Artifact: {openapi_result.destination}",
                f"Target path: {openapi_result.target_path}",
                f"Operations: {openapi_summary.operation_count}",
            ]
        ),
        _heading_2("Postman Summary"),
        *_bullets(
            [
                f"Artifact: {postman_result.destination}",
                f"Target path: {postman_result.target_path}",
                f"Requests: {postman_summary.request_count}",
            ]
        ),
        *_bullets(postman_summary.request_lines),
        _heading_2("Source Artifacts"),
        *_bullets(
            [
                f"Step 3 API analysis and test cases: {api_spec_result.destination}",
                f"Step 4 OpenAPI YAML: {openapi_result.destination}",
                f"Step 5 Postman collection: {postman_result.destination}",
            ]
        ),
    ]
    return blocks


@dataclass(frozen=True)
class OpenApiSummary:
    operation_count: int
    endpoint_lines: list[str]


@dataclass(frozen=True)
class PostmanSummary:
    request_count: int
    request_lines: list[str]


def summarize_openapi(openapi_yaml: str) -> OpenApiSummary:
    try:
        document = yaml.safe_load(openapi_yaml) or {}
    except yaml.YAMLError:
        return OpenApiSummary(operation_count=0, endpoint_lines=["OpenAPI YAML could not be parsed for endpoint summary."])

    if not isinstance(document, dict):
        return OpenApiSummary(operation_count=0, endpoint_lines=["OpenAPI YAML did not contain an object document."])

    paths = document.get("paths")
    if not isinstance(paths, dict):
        return OpenApiSummary(operation_count=0, endpoint_lines=["OpenAPI paths were not detected."])

    endpoint_lines: list[str] = []
    for path, path_item in paths.items():
        if not isinstance(path, str) or not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete", "head", "options"}:
                continue
            summary = operation.get("summary") if isinstance(operation, dict) else ""
            endpoint_lines.append(f"{method.upper()} {path} - {summary or 'No summary provided'}")

    return OpenApiSummary(
        operation_count=len(endpoint_lines),
        endpoint_lines=endpoint_lines[:20] or ["No OpenAPI operations were detected."],
    )


def summarize_postman_collection(collection_json: str) -> PostmanSummary:
    try:
        collection = json.loads(collection_json)
    except json.JSONDecodeError:
        return PostmanSummary(request_count=0, request_lines=["Postman collection JSON could not be parsed for request summary."])

    items = collection.get("item") if isinstance(collection, dict) else None
    if not isinstance(items, list):
        return PostmanSummary(request_count=0, request_lines=["Postman request items were not detected."])

    request_lines: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        request = item.get("request")
        method = request.get("method") if isinstance(request, dict) else "UNKNOWN"
        url = request.get("url") if isinstance(request, dict) else None
        raw_url = url.get("raw") if isinstance(url, dict) else ""
        request_lines.append(f"{method or 'UNKNOWN'} {raw_url or item.get('name', 'Unnamed request')}")

    return PostmanSummary(
        request_count=len(request_lines),
        request_lines=request_lines[:20] or ["No Postman requests were generated."],
    )


def extract_markdown_section(markdown: str, section_title: str) -> str:
    escaped_title = re.escape(section_title)
    pattern = re.compile(
        rf"^##\s+(?:\d+\.\s+)?{escaped_title}\s*$"
        rf"(?P<body>.*?)(?=^##\s+|\Z)",
        flags=re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(markdown)
    return match.group("body").strip() if match else ""


def write_notion_run_metadata(pr_context: PullRequestContext, result: NotionSyncResult) -> str:
    update_run(
        pr_context,
        notion={
            "success": result.success,
            "action": result.action,
            "page_id": result.page_id,
            "page_url": result.page_url,
            "error_message": result.error_message,
        },
    )
    logger.info(
        "Saved MergeFlow run metadata repo={repo} pr_number={pr_number}",
        repo=pr_context.repository,
        pr_number=pr_context.pr_number,
    )
    return run_id_for(pr_context.repository, pr_context.pr_number)


def safe_write_notion_run_metadata(pr_context: PullRequestContext, result: NotionSyncResult) -> str | None:
    try:
        return write_notion_run_metadata(pr_context, result)
    except Exception as error:
        logger.exception(
            "Could not save MergeFlow run metadata repo={repo} pr_number={pr_number} error={error}",
            repo=pr_context.repository,
            pr_number=pr_context.pr_number,
            error=str(error),
        )
        return None


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _page_ref_from_payload(payload: dict[str, Any]) -> NotionPageRef:
    page_id = payload.get("id")
    page_url = payload.get("url")
    if not isinstance(page_id, str) or not page_id:
        raise ValueError("Notion page response did not include a page id")
    return NotionPageRef(page_id=page_id, page_url=page_url if isinstance(page_url, str) else "")


def _heading_1(text: str) -> dict[str, Any]:
    return {"object": "block", "type": "heading_1", "heading_1": {"rich_text": [_rich_text(text)]}}


def _heading_2(text: str) -> dict[str, Any]:
    return {"object": "block", "type": "heading_2", "heading_2": {"rich_text": [_rich_text(text)]}}


def _code_block(content: str, language: str = "plain text") -> dict[str, Any]:
    return {
        "object": "block",
        "type": "code",
        "code": {
            "rich_text": [_rich_text(content)],
            "language": language,
        },
    }


def _paragraphs(text: str) -> list[dict[str, Any]]:
    return [
        {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [_rich_text(chunk)]}}
        for chunk in _split_text(text)
    ]


def _bullets(items: list[str]) -> list[dict[str, Any]]:
    return [
        {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [_rich_text(item)]}}
        for item in items
        if item
    ]


def _rich_text(content: str) -> dict[str, Any]:
    return {"type": "text", "text": {"content": content[:MAX_NOTION_TEXT_CHARS]}}


def _split_text(text: str) -> list[str]:
    normalized = text.strip()
    if not normalized:
        return []
    return [normalized[index : index + MAX_NOTION_TEXT_CHARS] for index in range(0, len(normalized), MAX_NOTION_TEXT_CHARS)]
