from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
import json
import os
import re
from typing import TYPE_CHECKING, Protocol

from loguru import logger

from backend.generators.notion_generator import (
    extract_markdown_section,
    summarize_openapi,
    summarize_postman_collection,
)
from backend.run_store import build_run_metadata_path

if TYPE_CHECKING:
    from backend.classifier.diff_classifier import BackendDiffClassification
    from backend.generators.api_spec_generator import ApiSpecGenerationResult
    from backend.generators.notion_draft_generator import NotionDocumentationResult
    from backend.generators.notion_generator import NotionSyncResult
    from backend.generators.openapi_generator import OpenApiGenerationResult
    from backend.generators.postman_generator import PostmanGenerationResult
    from backend.pipeline import PullRequestContext


DEFAULT_FROM_NAME = "MergeFlow"
MAX_EMAIL_ITEMS = 8


@dataclass(frozen=True)
class EmailSettings:
    api_key: str
    from_email: str
    from_name: str
    recipients: list[str]


@dataclass(frozen=True)
class ReleaseEmail:
    subject: str
    plain_text: str
    html: str
    recipients: list[str]


@dataclass(frozen=True)
class EmailSendResult:
    success: bool
    recipients: list[str]
    subject: str | None = None
    status_code: int | None = None
    error_message: str | None = None


class ReleaseEmailClient(Protocol):
    async def send_email(self, settings: EmailSettings, email: ReleaseEmail) -> int | None:
        ...


class SendGridReleaseEmailClient:
    async def send_email(self, settings: EmailSettings, email: ReleaseEmail) -> int | None:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Email, Mail

        message = Mail(
            from_email=Email(settings.from_email, settings.from_name),
            to_emails=email.recipients,
            subject=email.subject,
            plain_text_content=email.plain_text,
            html_content=email.html,
        )
        response = SendGridAPIClient(settings.api_key).send(message)
        return getattr(response, "status_code", None)


async def generate_and_send_release_email(
    pr_context: PullRequestContext,
    classification: BackendDiffClassification,
    api_spec_result: ApiSpecGenerationResult,
    openapi_result: OpenApiGenerationResult,
    postman_result: PostmanGenerationResult,
    notion_result: NotionDocumentationResult | NotionSyncResult,
    email_client: ReleaseEmailClient | None = None,
) -> EmailSendResult:
    logger.info(
        "Email generation started repo={repo} pr_number={pr_number}",
        repo=pr_context.repository,
        pr_number=pr_context.pr_number,
    )

    try:
        settings = get_email_settings()
        email = build_release_email(
            pr_context,
            classification,
            api_spec_result,
            openapi_result,
            postman_result,
            notion_result,
            settings.recipients,
        )
        logger.info(
            "Email generated repo={repo} pr_number={pr_number} recipients={recipients}",
            repo=pr_context.repository,
            pr_number=pr_context.pr_number,
            recipients=settings.recipients,
        )

        client = email_client or SendGridReleaseEmailClient()
        status_code = await client.send_email(settings, email)
        logger.info(
            "Email sent successfully repo={repo} pr_number={pr_number} recipients={recipients} status_code={status_code}",
            repo=pr_context.repository,
            pr_number=pr_context.pr_number,
            recipients=settings.recipients,
            status_code=status_code,
        )
        result = EmailSendResult(
            success=True,
            recipients=settings.recipients,
            subject=email.subject,
            status_code=status_code,
        )
        safe_write_email_run_metadata(pr_context, result)
        return result
    except Exception as error:
        error_message = str(error)
        logger.error(
            "Email failed repo={repo} pr_number={pr_number}",
            repo=pr_context.repository,
            pr_number=pr_context.pr_number,
        )
        logger.error("Reason: {reason}", reason=error_message)
        result = EmailSendResult(success=False, recipients=[], error_message=error_message)
        safe_write_email_run_metadata(pr_context, result)
        return result


def get_email_settings() -> EmailSettings:
    api_key = os.getenv("SENDGRID_API_KEY", "").strip()
    from_email = os.getenv("SENDGRID_FROM_EMAIL", "").strip()
    from_name = os.getenv("SENDGRID_FROM_NAME", DEFAULT_FROM_NAME).strip() or DEFAULT_FROM_NAME
    recipients = parse_recipient_list(os.getenv("SENDGRID_RECIPIENT_EMAILS", ""))

    missing = [
        name
        for name, value in (
            ("SENDGRID_API_KEY", api_key),
            ("SENDGRID_FROM_EMAIL", from_email),
            ("SENDGRID_RECIPIENT_EMAILS", ",".join(recipients)),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(f"Missing SendGrid configuration: {', '.join(missing)}")

    return EmailSettings(api_key=api_key, from_email=from_email, from_name=from_name, recipients=recipients)


def parse_recipient_list(raw_recipients: str) -> list[str]:
    recipients: list[str] = []
    seen: set[str] = set()
    for recipient in re.split(r"[,;\s]+", raw_recipients):
        normalized = recipient.strip()
        if not normalized or normalized in seen:
            continue
        if "@" not in normalized:
            raise ValueError(f"Invalid email recipient: {normalized}")
        seen.add(normalized)
        recipients.append(normalized)
    return recipients


def build_release_email(
    pr_context: PullRequestContext,
    classification: BackendDiffClassification,
    api_spec_result: ApiSpecGenerationResult,
    openapi_result: OpenApiGenerationResult,
    postman_result: PostmanGenerationResult,
    notion_result: NotionDocumentationResult | NotionSyncResult,
    recipients: list[str],
    generated_at: datetime | None = None,
) -> ReleaseEmail:
    timestamp = (generated_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    subject = f"[MergeFlow] PR #{pr_context.pr_number} Processed - {pr_context.title}"
    report = build_release_report(
        pr_context,
        classification,
        api_spec_result,
        openapi_result,
        postman_result,
        notion_result,
        timestamp,
    )
    return ReleaseEmail(
        subject=subject,
        plain_text=render_plain_text_email(report),
        html=render_html_email(report),
        recipients=recipients,
    )


def build_release_report(
    pr_context: PullRequestContext,
    classification: BackendDiffClassification,
    api_spec_result: ApiSpecGenerationResult,
    openapi_result: OpenApiGenerationResult,
    postman_result: PostmanGenerationResult,
    notion_result: NotionDocumentationResult | NotionSyncResult,
    timestamp: str,
) -> dict[str, object]:
    openapi_summary = summarize_openapi(openapi_result.yaml_content)
    postman_summary = summarize_postman_collection(postman_result.collection_json)
    change_summary = extract_markdown_section(api_spec_result.markdown, "Change Summary") or classification.summary
    test_cases = extract_list_items(extract_markdown_section(api_spec_result.markdown, "Test Cases"))
    risks = extract_list_items(extract_markdown_section(api_spec_result.markdown, "Regression Risks"))
    if not risks:
        risks = extract_list_items(extract_markdown_section(api_spec_result.markdown, "Edge Cases"))

    artifacts = [
        artifact_line("PR Documentation Draft", _notion_pr_review_url(notion_result), notion_result.success, notion_result.error_message),
        artifact_line("Service Documentation", _notion_service_page_url(notion_result), notion_result.success, notion_result.error_message),
        artifact_line("OpenAPI Specification", openapi_result.destination, True, None),
        artifact_line("Postman Collection", postman_result.destination, True, None),
    ]

    return {
        "repository": pr_context.repository,
        "pr": f"#{pr_context.pr_number} {pr_context.title}",
        "author": pr_context.author or "Unknown",
        "classification": list(classification.change_types),
        "summary": change_summary or "No summary was generated.",
        "affected_apis": openapi_summary.endpoint_lines[:MAX_EMAIL_ITEMS],
        "test_cases": test_cases[:MAX_EMAIL_ITEMS] or postman_summary.request_lines[:MAX_EMAIL_ITEMS],
        "artifacts": artifacts,
        "risks": risks[:MAX_EMAIL_ITEMS] or ["Review generated artifacts and run the repository's backend validation suite."],
        "timestamp": timestamp,
    }


def render_plain_text_email(report: dict[str, object]) -> str:
    lines = [
        "MergeFlow Release Report",
        "",
        "Repository:",
        str(report["repository"]),
        "",
        "PR:",
        str(report["pr"]),
        "",
        "Author:",
        str(report["author"]),
        "",
        "Classification:",
        *[str(item) for item in report["classification"]],
        "",
        "Summary:",
        str(report["summary"]),
        "",
        "Affected APIs:",
        *format_plain_list(report["affected_apis"]),
        "",
        "Key Test Cases Generated:",
        *format_plain_list(report["test_cases"]),
        "",
        "Generated Artifacts:",
        *format_plain_list(report["artifacts"]),
        "",
        "Risks / Validation Notes:",
        *format_plain_list(report["risks"]),
        "",
        "Timestamp:",
        str(report["timestamp"]),
    ]
    return "\n".join(lines).rstrip() + "\n"


def render_html_email(report: dict[str, object]) -> str:
    classification_items = "".join(f"<li>{escape(str(item))}</li>" for item in report["classification"])
    return f"""<!doctype html>
<html>
  <body style="font-family: Arial, sans-serif; color: #1f2937; line-height: 1.5;">
    <h1>MergeFlow Release Report</h1>
    <p><strong>Repository:</strong><br>{escape(str(report["repository"]))}</p>
    <p><strong>PR:</strong><br>{escape(str(report["pr"]))}</p>
    <p><strong>Author:</strong><br>{escape(str(report["author"]))}</p>
    <p><strong>Classification:</strong></p>
    <ul>{classification_items}</ul>
    <p><strong>Summary:</strong><br>{escape(str(report["summary"]))}</p>
    {render_html_list("Affected APIs", report["affected_apis"])}
    {render_html_list("Key Test Cases Generated", report["test_cases"])}
    {render_html_list("Generated Artifacts", report["artifacts"])}
    {render_html_list("Risks / Validation Notes", report["risks"])}
    <p><strong>Timestamp:</strong><br>{escape(str(report["timestamp"]))}</p>
  </body>
</html>
"""


def render_html_list(title: str, items: object) -> str:
    item_list = items if isinstance(items, list) else []
    rendered_items = "".join(f"<li>{escape(str(item))}</li>" for item in item_list)
    return f"<p><strong>{escape(title)}:</strong></p><ul>{rendered_items}</ul>"


def format_plain_list(items: object) -> list[str]:
    item_list = items if isinstance(items, list) else []
    return [f"- {item}" for item in item_list] or ["- None detected"]


def extract_list_items(markdown: str) -> list[str]:
    items: list[str] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        normalized = re.sub(r"^(?:[-*]|\d+\.)\s+", "", stripped).strip()
        if normalized and normalized not in items:
            items.append(normalized)
    return items


def artifact_line(label: str, destination: str | None, success: bool, error_message: str | None) -> str:
    if success and destination:
        return f"[ok] {label}: {destination}"
    if error_message:
        return f"[failed] {label}: {error_message}"
    return f"[missing] {label}"


def _notion_pr_review_url(notion_result: NotionDocumentationResult | NotionSyncResult) -> str | None:
    return getattr(notion_result, "pr_review_page_url", None) or getattr(notion_result, "page_url", None)


def _notion_service_page_url(notion_result: NotionDocumentationResult | NotionSyncResult) -> str | None:
    return getattr(notion_result, "service_page_url", None)


def write_email_run_metadata(pr_context: PullRequestContext, result: EmailSendResult) -> str:
    metadata_path = build_run_metadata_path(pr_context)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    existing = _read_json_object(metadata_path)
    existing["email"] = {
        "success": result.success,
        "recipients": result.recipients,
        "subject": result.subject,
        "status_code": result.status_code,
        "error_message": result.error_message,
    }
    metadata_path.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    logger.info(
        "Saved MergeFlow email metadata repo={repo} pr_number={pr_number} metadata_path={metadata_path}",
        repo=pr_context.repository,
        pr_number=pr_context.pr_number,
        metadata_path=str(metadata_path),
    )
    return str(metadata_path)


def safe_write_email_run_metadata(pr_context: PullRequestContext, result: EmailSendResult) -> str | None:
    try:
        return write_email_run_metadata(pr_context, result)
    except Exception as error:
        logger.exception(
            "Could not save MergeFlow email metadata repo={repo} pr_number={pr_number} error={error}",
            repo=pr_context.repository,
            pr_number=pr_context.pr_number,
            error=str(error),
        )
        return None


def _read_json_object(path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}
