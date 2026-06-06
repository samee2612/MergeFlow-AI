from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import TYPE_CHECKING, Any, Protocol

from loguru import logger

from backend.generators.mermaid_generator import MermaidDiagrams, extract_openapi_operations, generate_mermaid_diagrams
from backend.generators.notion_generator import (
    NotionApiClient,
    NotionPageRef,
    NotionSyncResult,
    extract_markdown_section,
    get_notion_settings,
    safe_write_notion_run_metadata,
    summarize_openapi,
    summarize_postman_collection,
    write_notion_run_metadata,
    _bullets,
    _code_block,
    _heading_1,
    _heading_2,
    _paragraphs,
)
from backend.generators.notion_generator import MAX_BLOCKS_PER_APPEND

if TYPE_CHECKING:
    from backend.classifier.diff_classifier import BackendDiffClassification
    from backend.generators.api_spec_generator import ApiSpecGenerationResult
    from backend.generators.openapi_generator import OpenApiGenerationResult
    from backend.generators.postman_generator import PostmanGenerationResult
    from backend.pipeline import PullRequestContext
    from backend.service_resolver import ServiceResolution

PR_REVIEWS_FOLDER = "MergeFlow PR Reviews"
SERVICE_SECTIONS = (
    "Overview",
    "Features",
    "Architecture",
    "API Reference",
    "Test Suites",
    "Release History",
)


@dataclass(frozen=True)
class NotionDocumentationResult:
    success: bool
    action: str
    pr_review_page_id: str | None = None
    pr_review_page_url: str | None = None
    service_page_id: str | None = None
    service_page_url: str | None = None
    feature_folder_id: str | None = None
    error_message: str | None = None
    metadata_path: str | None = None

    @property
    def page_id(self) -> str | None:
        return self.pr_review_page_id

    @property
    def page_url(self) -> str | None:
        return self.pr_review_page_url


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

    async def merge_service_page_sections(self, page_id: str, section_blocks: dict[str, list[dict[str, Any]]]) -> NotionPageRef:
        existing_blocks = await self.get_page_blocks(page_id)
        merged_blocks = _merge_section_blocks(existing_blocks, section_blocks)
        return await self.update_child_page(page_id, merged_blocks)

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


class NotionDocumentationClient(Protocol):
    async def find_page_by_title(self, database_id: str, title_property: str, title: str) -> NotionPageRef | None:
        ...

    async def find_child_page_by_title(self, parent_page_id: str, title: str) -> NotionPageRef | None:
        ...

    async def create_child_page(self, parent_page_id: str, title: str, blocks: list[dict[str, Any]]) -> NotionPageRef:
        ...

    async def update_child_page(self, page_id: str, blocks: list[dict[str, Any]]) -> NotionPageRef:
        ...

    async def merge_service_page_sections(self, page_id: str, section_blocks: dict[str, list[dict[str, Any]]]) -> NotionPageRef:
        ...


async def update_notion_documentation(
    pr_context: PullRequestContext,
    service: ServiceResolution,
    classification: BackendDiffClassification,
    api_spec_result: ApiSpecGenerationResult,
    openapi_result: OpenApiGenerationResult,
    postman_result: PostmanGenerationResult,
    notion_client: NotionDocumentationClient | None = None,
) -> NotionDocumentationResult:
    logger.info(
        "Notion documentation update started repo={repo} pr_number={pr_number} service={service}",
        repo=pr_context.repository,
        pr_number=pr_context.pr_number,
        service=service.service_name,
    )

    try:
        settings = get_notion_settings()
        client = notion_client or NotionHierarchyClient(settings.api_key)
        diagrams = generate_mermaid_diagrams(
            service.service_name,
            openapi_result.yaml_content,
            extract_markdown_section(api_spec_result.markdown, "Change Summary") or classification.summary,
        )

        service_page = await client.find_page_by_title(
            settings.database_id,
            settings.title_property,
            service.service_name,
        )
        if service_page is None:
            raise RuntimeError(f"Service documentation page not found for {service.service_name}")

        reviews_folder = await _ensure_child_page(client, service_page.page_id, PR_REVIEWS_FOLDER, [])
        feature_slug = build_feature_folder_slug(pr_context)
        feature_folder = await _ensure_child_page(client, reviews_folder.page_id, feature_slug, [])

        pr_title = build_pr_review_page_title(pr_context)
        pr_blocks = build_pr_review_page_blocks(
            pr_context,
            service,
            classification,
            api_spec_result,
            openapi_result,
            postman_result,
            diagrams,
        )
        existing_pr_page = await client.find_child_page_by_title(feature_folder.page_id, pr_title)
        if existing_pr_page:
            pr_page = await client.update_child_page(existing_pr_page.page_id, pr_blocks)
            pr_action = "updated"
        else:
            pr_page = await client.create_child_page(feature_folder.page_id, pr_title, pr_blocks)
            pr_action = "created"

        service_sections = build_service_page_section_blocks(
            pr_context,
            service,
            classification,
            api_spec_result,
            openapi_result,
            postman_result,
            diagrams,
            pr_page.page_url,
        )
        updated_service_page = await client.merge_service_page_sections(service_page.page_id, service_sections)

        result = NotionDocumentationResult(
            success=True,
            action=f"service_updated_pr_{pr_action}",
            pr_review_page_id=pr_page.page_id,
            pr_review_page_url=pr_page.page_url,
            service_page_id=updated_service_page.page_id,
            service_page_url=updated_service_page.page_url,
            feature_folder_id=feature_folder.page_id,
        )
        metadata_path = _write_documentation_metadata(pr_context, result)
        logger.info(
            "Notion documentation updated repo={repo} pr_number={pr_number} service_page={service_page} pr_review_page={pr_review_page}",
            repo=pr_context.repository,
            pr_number=pr_context.pr_number,
            service_page=updated_service_page.page_url,
            pr_review_page=pr_page.page_url,
        )
        return NotionDocumentationResult(
            success=True,
            action=f"service_updated_pr_{pr_action}",
            pr_review_page_id=pr_page.page_id,
            pr_review_page_url=pr_page.page_url,
            service_page_id=updated_service_page.page_id,
            service_page_url=updated_service_page.page_url,
            feature_folder_id=feature_folder.page_id,
            metadata_path=metadata_path,
        )
    except Exception as error:
        error_message = str(error)
        logger.exception(
            "Notion documentation update failed repo={repo} pr_number={pr_number} reason={reason}",
            repo=pr_context.repository,
            pr_number=pr_context.pr_number,
            reason=error_message,
        )
        result = NotionDocumentationResult(success=False, action="failed", error_message=error_message)
        metadata_path = _write_documentation_metadata(pr_context, result)
        return NotionDocumentationResult(
            success=False,
            action="failed",
            error_message=error_message,
            metadata_path=metadata_path,
        )


def build_feature_folder_slug(pr_context: PullRequestContext) -> str:
    pr_number = pr_context.pr_number if pr_context.pr_number is not None else "unknown"
    title_slug = re.sub(r"[^a-z0-9]+", "-", pr_context.title.lower()).strip("-")
    if title_slug:
        return f"feature-{pr_number}-{title_slug[:40]}"
    return f"feature-{pr_number}"


def build_pr_review_page_title(pr_context: PullRequestContext) -> str:
    pr_number = pr_context.pr_number if pr_context.pr_number is not None else "unknown"
    return f"PR #{pr_number} Documentation Draft"


def build_pr_review_page_blocks(
    pr_context: PullRequestContext,
    service: ServiceResolution,
    classification: BackendDiffClassification,
    api_spec_result: ApiSpecGenerationResult,
    openapi_result: OpenApiGenerationResult,
    postman_result: PostmanGenerationResult,
    diagrams: MermaidDiagrams,
) -> list[dict[str, Any]]:
    openapi_summary = summarize_openapi(openapi_result.yaml_content)
    postman_summary = summarize_postman_collection(postman_result.collection_json)
    change_summary = extract_markdown_section(api_spec_result.markdown, "Change Summary") or classification.summary
    architecture_changes = extract_markdown_section(api_spec_result.markdown, "Architecture Changes") or change_summary
    test_cases = extract_markdown_section(api_spec_result.markdown, "Test Cases")
    release_notes = extract_markdown_section(api_spec_result.markdown, "Release Notes") or change_summary
    proposed_updates = _build_proposed_service_updates(service, classification, openapi_summary.endpoint_lines)

    blocks: list[dict[str, Any]] = [
        _heading_1(build_pr_review_page_title(pr_context)),
        *_bullets(["DRAFT", "Generated by MergeFlow", "Awaiting Review"]),
        _heading_2("Summary"),
        *_paragraphs(change_summary or "No summary was generated."),
        _heading_2("Affected APIs"),
        *_bullets(openapi_summary.endpoint_lines or ["No affected APIs detected."]),
        _heading_2("Architecture Changes"),
        *_paragraphs(architecture_changes or "No architecture changes were detected."),
        _heading_2("Generated Mermaid Diagrams"),
        _heading_2("Flow Diagram"),
        _code_block(diagrams.flowchart, "mermaid"),
        _heading_2("Sequence Diagram"),
        _code_block(diagrams.sequence_diagram, "mermaid"),
        _heading_2("Documentation Updates Proposed"),
        *_bullets(proposed_updates),
        _heading_2("Generated Test Cases"),
        *_paragraphs(test_cases or "No test cases were detected."),
        *_bullets(postman_summary.request_lines),
        _heading_2("Release Notes"),
        *_paragraphs(release_notes or "No release notes were generated."),
        _heading_2("Source Artifacts"),
        *_bullets(
            [
                f"Service: {service.service_name}",
                f"Team: {service.team_name}",
                f"Repository: {pr_context.repository}",
                f"OpenAPI: {openapi_result.destination}",
                f"Postman: {postman_result.destination}",
                f"API analysis: {api_spec_result.destination}",
            ]
        ),
    ]
    return blocks


def build_service_page_section_blocks(
    pr_context: PullRequestContext,
    service: ServiceResolution,
    classification: BackendDiffClassification,
    api_spec_result: ApiSpecGenerationResult,
    openapi_result: OpenApiGenerationResult,
    postman_result: PostmanGenerationResult,
    diagrams: MermaidDiagrams,
    pr_review_page_url: str,
) -> dict[str, list[dict[str, Any]]]:
    openapi_summary = summarize_openapi(openapi_result.yaml_content)
    postman_summary = summarize_postman_collection(postman_result.collection_json)
    change_summary = extract_markdown_section(api_spec_result.markdown, "Change Summary") or classification.summary
    test_cases = extract_markdown_section(api_spec_result.markdown, "Test Cases")
    features = _extract_feature_names(classification, openapi_result.yaml_content)

    api_reference_lines = [
        f"{operation['method']} {operation['path']} - {operation['summary']}"
        for operation in extract_openapi_operations(openapi_result.yaml_content)
    ] or openapi_summary.endpoint_lines

    release_entry = (
        f"PR #{pr_context.pr_number} by {pr_context.author or 'Unknown'} on "
        f"{pr_context.merged_at or 'Unknown'} - {change_summary}"
    )

    return {
        "Overview": [
            *_paragraphs(
                f"{service.service_name} provides backend capabilities for {service.team_name}. "
                f"Latest update from PR #{pr_context.pr_number}: {change_summary}"
            ),
            *_bullets(
                [
                    "Updated by MergeFlow",
                    f"Repository: {pr_context.repository}",
                    f"PR review page: {pr_review_page_url}",
                ]
            ),
        ],
        "Features": [
            *_bullets(features or ["No new features detected in this PR."]),
        ],
        "Architecture": [
            _heading_2("Component Diagram"),
            _code_block(diagrams.flowchart, "mermaid"),
            _heading_2("Sequence Diagram"),
            _code_block(diagrams.sequence_diagram, "mermaid"),
        ],
        "API Reference": [
            *_bullets(api_reference_lines or ["No API operations detected."]),
            *_bullets([f"OpenAPI source: {openapi_result.destination}"]),
        ],
        "Test Suites": [
            *_paragraphs(test_cases or "No generated test cases were detected."),
            *_bullets(postman_summary.request_lines or ["No Postman requests generated."]),
            *_bullets([f"Postman collection: {postman_result.destination}"]),
        ],
        "Release History": [
            *_bullets([release_entry]),
        ],
    }


async def _ensure_child_page(
    client: NotionDocumentationClient,
    parent_page_id: str,
    title: str,
    blocks: list[dict[str, Any]],
) -> NotionPageRef:
    existing_page = await client.find_child_page_by_title(parent_page_id, title)
    if existing_page:
        return existing_page
    return await client.create_child_page(parent_page_id, title, blocks)


def _merge_section_blocks(
    existing_blocks: list[dict[str, Any]],
    section_blocks: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    sections = _split_blocks_by_heading(existing_blocks, level=2)
    merged: list[dict[str, Any]] = []

    seen_sections: set[str] = set()
    for heading, blocks in sections:
        if heading in section_blocks:
            merged.append(_heading_2(heading))
            if heading == "Release History":
                existing_body = [block for block in blocks if block.get("type") != "heading_2"]
                merged.extend(existing_body)
                merged.extend(section_blocks[heading])
            else:
                merged.extend(section_blocks[heading])
            seen_sections.add(heading)
        else:
            merged.extend(blocks)

    for heading in SERVICE_SECTIONS:
        if heading in section_blocks and heading not in seen_sections:
            merged.append(_heading_2(heading))
            merged.extend(section_blocks[heading])

    if not merged:
        for heading in SERVICE_SECTIONS:
            if heading in section_blocks:
                merged.append(_heading_2(heading))
                merged.extend(section_blocks[heading])

    return merged


def _split_blocks_by_heading(blocks: list[dict[str, Any]], level: int = 2) -> list[tuple[str | None, list[dict[str, Any]]]]:
    heading_type = f"heading_{level}"
    sections: list[tuple[str | None, list[dict[str, Any]]]] = []
    current_heading: str | None = None
    current_blocks: list[dict[str, Any]] = []

    for block in blocks:
        if block.get("type") == heading_type:
            if current_blocks or current_heading is not None:
                sections.append((current_heading, current_blocks))
            current_heading = _heading_text(block, heading_type)
            current_blocks = [block]
            continue
        current_blocks.append(block)

    if current_blocks or current_heading is not None:
        sections.append((current_heading, current_blocks))

    return sections


def _heading_text(block: dict[str, Any], heading_type: str) -> str:
    payload = block.get(heading_type)
    if not isinstance(payload, dict):
        return ""
    rich_text = payload.get("rich_text")
    if not isinstance(rich_text, list) or not rich_text:
        return ""
    first = rich_text[0]
    if not isinstance(first, dict):
        return ""
    text = first.get("text")
    if isinstance(text, dict) and isinstance(text.get("content"), str):
        return text["content"]
    return ""


def _build_proposed_service_updates(
    service: ServiceResolution,
    classification: BackendDiffClassification,
    endpoint_lines: list[str],
) -> list[str]:
    updates = [
        f"Update Overview for {service.service_name}.",
        f"Refresh API Reference with {len(endpoint_lines)} affected endpoint(s).",
        "Append Release History entry for this PR.",
    ]
    if "Authentication" in classification.change_types:
        updates.append("Review auth-related architecture and test coverage.")
    return updates


def _extract_feature_names(classification: BackendDiffClassification, openapi_yaml: str) -> list[str]:
    features: list[str] = []
    for change_type in classification.change_types:
        if change_type not in {"Unknown"}:
            features.append(change_type)

    for operation in extract_openapi_operations(openapi_yaml):
        summary = operation["summary"].strip()
        if summary and summary not in features:
            features.append(summary)

    return features


def _page_ref_from_payload(payload: dict[str, Any]) -> NotionPageRef:
    page_id = payload.get("id")
    page_url = payload.get("url")
    if not isinstance(page_id, str) or not page_id:
        raise ValueError("Notion page response did not include a page id")
    return NotionPageRef(page_id=page_id, page_url=page_url if isinstance(page_url, str) else "")


def _write_documentation_metadata(pr_context: PullRequestContext, result: NotionDocumentationResult) -> str | None:
    legacy_result = NotionSyncResult(
        success=result.success,
        action=result.action,
        page_id=result.pr_review_page_id,
        page_url=result.pr_review_page_url,
        error_message=result.error_message,
    )
    try:
        metadata_path = write_notion_run_metadata(pr_context, legacy_result)
        from backend.run_store import build_run_metadata_path

        metadata_path_obj = build_run_metadata_path(pr_context)
        existing = _read_json_object(metadata_path_obj)
        existing["notionDocumentation"] = {
            "success": result.success,
            "action": result.action,
            "prReviewPageId": result.pr_review_page_id,
            "prReviewPageUrl": result.pr_review_page_url,
            "servicePageId": result.service_page_id,
            "servicePageUrl": result.service_page_url,
            "featureFolderId": result.feature_folder_id,
            "errorMessage": result.error_message,
        }
        metadata_path_obj.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return metadata_path
    except Exception as error:
        logger.exception(
            "Could not save Notion documentation metadata repo={repo} pr_number={pr_number} error={error}",
            repo=pr_context.repository,
            pr_number=pr_context.pr_number,
            error=str(error),
        )
        return safe_write_notion_run_metadata(pr_context, legacy_result)


def _read_json_object(path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}
