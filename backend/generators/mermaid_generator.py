from __future__ import annotations

from dataclasses import dataclass
import re

import yaml

from backend.generators.notion_generator import summarize_openapi


@dataclass(frozen=True)
class MermaidDiagrams:
    flowchart: str
    sequence_diagram: str


def generate_mermaid_diagrams(
    service_name: str,
    openapi_yaml: str,
    architecture_summary: str = "",
) -> MermaidDiagrams:
    """Generate small flow and sequence Mermaid diagrams from OpenAPI output."""
    openapi_summary = summarize_openapi(openapi_yaml)
    primary_endpoint = _parse_primary_endpoint(openapi_summary.endpoint_lines)

    service_node = _sanitize_node(service_name or "Service")
    api_node = f"{service_node}API"
    flowchart = _build_flowchart(service_node, api_node, primary_endpoint)
    sequence_diagram = _build_sequence_diagram(api_node, service_node, primary_endpoint, architecture_summary)

    return MermaidDiagrams(flowchart=flowchart, sequence_diagram=sequence_diagram)


def _parse_primary_endpoint(endpoint_lines: list[str]) -> tuple[str, str]:
    if not endpoint_lines:
        return "POST", "/resource"

    first_line = endpoint_lines[0]
    match = re.match(r"^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(\S+)", first_line.strip())
    if match:
        return match.group(1), match.group(2)
    return "POST", "/resource"


def _build_flowchart(service_node: str, api_node: str, endpoint: tuple[str, str]) -> str:
    method, path = endpoint
    handler_node = _sanitize_node(path.strip("/").replace("/", "_") or "handler")
    return "\n".join(
        [
            "flowchart TD",
            "    Client --> ServiceAPI",
            f"    ServiceAPI[{api_node}] --> {service_node}[{service_node}]",
            f"    {service_node} --> {handler_node}[{method} {path}]",
        ]
    ).replace("ServiceAPI", api_node, 1)


def _build_sequence_diagram(
    api_node: str,
    service_node: str,
    endpoint: tuple[str, str],
    architecture_summary: str,
) -> str:
    method, path = endpoint
    detail = architecture_summary.strip().split(".")[0] if architecture_summary.strip() else "process request"
    return "\n".join(
        [
            "sequenceDiagram",
            f"    Client->>{api_node}: {method} {path}",
            f"    {api_node}->>{service_node}: {detail}",
            f"    {service_node}-->>{api_node}: result",
            f"    {api_node}-->>Client: 200 OK",
        ]
    )


def _sanitize_node(label: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_ ]+", "", label).strip().replace(" ", "")
    return cleaned or "Service"


def extract_openapi_operations(openapi_yaml: str) -> list[dict[str, str]]:
    try:
        document = yaml.safe_load(openapi_yaml) or {}
    except yaml.YAMLError:
        return []

    if not isinstance(document, dict):
        return []

    paths = document.get("paths")
    if not isinstance(paths, dict):
        return []

    operations: list[dict[str, str]] = []
    for path, path_item in paths.items():
        if not isinstance(path, str) or not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            summary = operation.get("summary") if isinstance(operation, dict) else ""
            operations.append(
                {
                    "method": method.upper(),
                    "path": path,
                    "summary": str(summary or "No summary provided"),
                }
            )
    return operations
