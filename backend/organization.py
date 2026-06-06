from __future__ import annotations

from typing import Any


# MergeFlow service catalog.
#
# Treat this file like an environment/config registry for the company:
# - add a service here before expecting it to appear on the dashboard
# - set `repository` to the exact GitHub full name, for example
#   `samee2612/identity-service`
# - set `owner` to the owning team name
ORGANIZATION: dict[str, Any] = {
    "id": "acmeflow",
    "name": "AcmeFlow Technologies",
    "description": "Service-aware engineering platform for post-merge documentation, API specs, and release artifacts.",
    "teams": [
        {
            "id": "platform-engineering",
            "name": "Platform Engineering",
            "description": "Shared platform capabilities used across product lines: identity, ingress, and developer operations.",
            "services": [
                {
                    "id": "identity-service",
                    "name": "Identity Service",
                    "repository": "samee2612/identity-service",
                    "description": "User auth, login/logout, token lifecycle, roles, and permissions APIs.",
                    "owner": "Platform Engineering",
                },
                {
                    "id": "api-gateway-service",
                    "name": "API Gateway Service",
                    "repository": "samee2612/api-gateway-service",
                    "description": "Request routing, rate limiting, service ingress, and auth handoff APIs.",
                    "owner": "Platform Engineering",
                },
                {
                    "id": "developer-tooling-service",
                    "name": "Developer Tooling Service",
                    "repository": "samee2612/developer-tooling-service",
                    "description": "Internal service catalog, deployment helpers, and developer workflow APIs.",
                    "owner": "Platform Engineering",
                },
            ],
        },
        {
            "id": "revenue-engineering",
            "name": "Revenue Engineering",
            "description": "Revenue lifecycle services for billing, subscriptions, invoices, and payments.",
            "services": [
                {
                    "id": "billing-service",
                    "name": "Billing Service",
                    "repository": "samee2612/billing-service",
                    "description": "Invoices, usage charges, payment methods, and billing reconciliation APIs.",
                    "owner": "Revenue Engineering",
                },
                {
                    "id": "subscription-service",
                    "name": "Subscription Service",
                    "repository": "samee2612/subscription-service",
                    "description": "Plans, trials, renewals, cancellations, and entitlement updates.",
                    "owner": "Revenue Engineering",
                },
                {
                    "id": "invoice-service",
                    "name": "Invoice Service",
                    "repository": "samee2612/invoice-service",
                    "description": "Invoice generation, tax details, payment status, and invoice delivery APIs.",
                    "owner": "Revenue Engineering",
                },
            ],
        },
        {
            "id": "video-services-engineering",
            "name": "Video Services Engineering",
            "description": "Video catalog, playback, processing, and streaming services.",
            "services": [
                {
                    "id": "video-catalog-service",
                    "name": "Video Catalog Service",
                    "repository": "samee2612/video-catalog-service",
                    "description": "Video metadata, catalog search, categories, and availability APIs.",
                    "owner": "Video Services Engineering",
                },
                {
                    "id": "streaming-service",
                    "name": "Streaming Service",
                    "repository": "samee2612/streaming-service",
                    "description": "Playback sessions, stream URLs, quality selection, and playback telemetry APIs.",
                    "owner": "Video Services Engineering",
                },
                {
                    "id": "media-processing-service",
                    "name": "Media Processing Service",
                    "repository": "samee2612/media-processing-service",
                    "description": "Encoding jobs, thumbnails, captions, transcodes, and media pipeline status APIs.",
                    "owner": "Video Services Engineering",
                },
            ],
        },
        {
            "id": "customer-engagement-engineering",
            "name": "Customer Engagement Engineering",
            "description": "Customer communication and notification services across channels.",
            "services": [
                {
                    "id": "notification-service",
                    "name": "Notification Service",
                    "repository": "samee2612/notification-service",
                    "description": "Transactional email, SMS, webhooks, templates, and delivery status APIs.",
                    "owner": "Customer Engagement Engineering",
                },
                {
                    "id": "preference-service",
                    "name": "Preference Service",
                    "repository": "samee2612/preference-service",
                    "description": "Customer communication preferences, opt-ins, and channel settings.",
                    "owner": "Customer Engagement Engineering",
                },
                {
                    "id": "order-service",
                    "name": "Order Service",
                    "repository": "samee2612/order-service",
                    "description": "Reusable email templates, localization, rendering, and template validation APIs.",
                    "owner": "Customer Engagement Engineering",
                },
            ],
        },
    ],
}


def get_organization() -> dict[str, Any]:
    return ORGANIZATION


def list_services() -> list[dict[str, Any]]:
    services: list[dict[str, Any]] = []
    for team in ORGANIZATION["teams"]:
        for service in team["services"]:
            services.append(
                {
                    **service,
                    "teamId": team["id"],
                    "teamName": team["name"],
                }
            )
    return services


def service_context_for_repository(repository: str) -> dict[str, str] | None:
    normalized_repository = repository.lower()
    for service in list_services():
        if service["repository"].lower() == normalized_repository:
            return {
                "teamId": service["teamId"],
                "teamName": service["teamName"],
                "serviceId": service["id"],
                "serviceName": service["name"],
            }
    return None


def service_by_id(service_id: str) -> dict[str, Any] | None:
    for service in list_services():
        if service["id"] == service_id:
            return service
    return None


def team_by_id(team_id: str) -> dict[str, Any] | None:
    for team in ORGANIZATION["teams"]:
        if team["id"] == team_id:
            return team
    return None
