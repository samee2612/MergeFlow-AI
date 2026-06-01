"""Pre-merge self-review feature runner."""

from __future__ import annotations

import json
import os
from typing import Any, Literal, TypedDict

import httpx
from dotenv import load_dotenv
import google.generativeai as genai
from loguru import logger

load_dotenv()

GITHUB_API_BASE_URL = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")
MAX_DIFF_CHARS = 20000

Severity = Literal["warning", "info"]


class SelfReviewFinding(TypedDict):
    severity: Severity
    file: str | None
    line: int | None
    explanation: str
    fix: str


def run_self_review(repo: str, pr_number: int, diff_text: str) -> list[SelfReviewFinding]:
    """Run Gemini-powered pre-merge review and post the result on the PR."""
    findings = _analyze_diff_with_gemini(diff_text)
    comment_body = _format_review_comment(findings)
    _post_pr_comment(repo, pr_number, comment_body)

    logger.info(
        "Posted self review comment repo={repo} pr_number={pr_number} finding_count={finding_count}",
        repo=repo,
        pr_number=pr_number,
        finding_count=len(findings),
    )
    return findings


def _analyze_diff_with_gemini(diff_text: str) -> list[SelfReviewFinding]:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        GEMINI_MODEL,
        system_instruction=(
            "You are MergeFlow AI's pre-merge self-review bot. "
            "Analyze only the added or changed lines in the diff. "
            "Return strict JSON only, with no markdown or commentary."
        ),
    )
    response = model.generate_content(
        (
            "Find concrete issues in this pull request diff:\n"
            "1. Hardcoded values that should be config, including URLs, API keys, and magic numbers.\n"
            "2. Leftover TODO, FIXME, console.log, or print statements.\n"
            "3. New functions or endpoints without corresponding tests in the diff.\n"
            "4. Missing error handling on new API calls.\n\n"
            "Return JSON in this exact shape:\n"
            "{\n"
            '  "findings": [\n'
            "    {\n"
            '      "severity": "warning" | "info",\n'
            '      "file": "path/to/file.py" | null,\n'
            '      "line": 123 | null,\n'
            '      "explanation": "clear explanation of the issue",\n'
            '      "fix": "what the developer should change"\n'
            "    }\n"
            "  ]\n"
            "}\n\n"
            "Use warning for likely bugs, security risks, missing error handling, or missing tests. "
            "Use info for cleanup reminders like TODOs or debug statements. "
            "If there are no issues, return {\"findings\": []}.\n\n"
            f"Diff:\n{diff_text[:MAX_DIFF_CHARS]}"
        ),
        generation_config=genai.types.GenerationConfig(
            max_output_tokens=2000,
            temperature=0,
        ),
    )

    response_text = _strip_json_code_fence(_extract_response_text(response))
    payload = json.loads(response_text)
    return _validate_findings(payload.get("findings", []))


def _extract_response_text(response: object) -> str:
    text = getattr(response, "text", "")
    if isinstance(text, str):
        return text.strip()

    return ""


def _strip_json_code_fence(response_text: str) -> str:
    stripped_text = response_text.strip()
    if stripped_text.startswith("```json") and stripped_text.endswith("```"):
        return stripped_text.removeprefix("```json").removesuffix("```").strip()
    if stripped_text.startswith("```") and stripped_text.endswith("```"):
        return stripped_text.removeprefix("```").removesuffix("```").strip()

    return stripped_text


def _validate_findings(raw_findings: Any) -> list[SelfReviewFinding]:
    if not isinstance(raw_findings, list):
        raise ValueError("Gemini self-review response did not include a findings list")

    findings: list[SelfReviewFinding] = []
    for raw_finding in raw_findings:
        if not isinstance(raw_finding, dict):
            raise ValueError("Gemini self-review finding was not an object")

        severity = raw_finding.get("severity")
        if severity not in {"warning", "info"}:
            raise ValueError(f"Invalid self-review severity: {severity}")

        line = raw_finding.get("line")
        if line is not None and not isinstance(line, int):
            line = None

        findings.append(
            {
                "severity": severity,
                "file": _optional_string(raw_finding.get("file")),
                "line": line,
                "explanation": str(raw_finding.get("explanation") or "").strip(),
                "fix": str(raw_finding.get("fix") or "").strip(),
            }
        )

    return findings


def _optional_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None

    stripped_value = value.strip()
    return stripped_value or None


def _format_review_comment(findings: list[SelfReviewFinding]) -> str:
    if not findings:
        return (
            "## MergeFlow AI Self Review\n\n"
            "Self review passed. I did not find hardcoded config values, leftover debug notes, "
            "missing tests for new functions/endpoints, or missing API error handling in this diff."
        )

    finding_sections = "\n\n".join(_format_finding(index, finding) for index, finding in enumerate(findings, 1))
    return (
        "## MergeFlow AI Self Review\n\n"
        "I found the following items worth checking before merge:\n\n"
        f"{finding_sections}"
    )


def _format_finding(index: int, finding: SelfReviewFinding) -> str:
    location = _format_location(finding)
    location_line = f"\n- File: `{location}`" if location else ""

    return (
        f"### {index}. Severity: {finding['severity']}"
        f"{location_line}\n"
        f"- Issue: {finding['explanation']}\n"
        f"- Fix: {finding['fix']}"
    )


def _format_location(finding: SelfReviewFinding) -> str | None:
    file_path = finding.get("file")
    line = finding.get("line")

    if file_path and line:
        return f"{file_path}:{line}"
    if file_path:
        return file_path

    return None


def _post_pr_comment(repo: str, pr_number: int, body: str) -> None:
    token = _get_github_token()

    try:
        response = httpx.post(
            f"{GITHUB_API_BASE_URL}/repos/{repo}/issues/{pr_number}/comments",
            headers=_github_headers(token),
            json={"body": body},
            timeout=15,
        )
        response.raise_for_status()
    except httpx.HTTPError as error:
        logger.error(
            "Failed to post self review comment repo={repo} pr_number={pr_number} error={error}",
            repo=repo,
            pr_number=pr_number,
            error=str(error),
        )
        raise


def _get_github_token() -> str:
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is not configured")

    return token


def _github_headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }
