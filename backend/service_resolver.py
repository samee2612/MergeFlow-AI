from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from loguru import logger

from backend.organization import list_services, service_context_for_repository


ResolutionMethod = Literal["repository_mapping", "unmapped"]


@dataclass(frozen=True)
class ServiceResolution:
    team_id: str
    team_name: str
    service_id: str
    service_name: str
    method: ResolutionMethod
    confidence: str

    def as_dict(self) -> dict[str, str]:
        return {
            "teamId": self.team_id,
            "teamName": self.team_name,
            "serviceId": self.service_id,
            "serviceName": self.service_name,
            "resolutionMethod": self.method,
            "confidence": self.confidence,
        }


def resolve_service(
    repository: str,
    pr_title: str = "",
    changed_files: list[str] | None = None,
) -> ServiceResolution:
    """Resolve team/service for a merged PR from the configured service catalog."""
    del pr_title, changed_files  # kept for call-site compatibility and future metadata use

    context = service_context_for_repository(repository)
    if context is not None:
        logger.info(
            "Resolved service via repository mapping repo={repo} service={service}",
            repo=repository,
            service=context["serviceName"],
        )
        return ServiceResolution(
            team_id=context["teamId"],
            team_name=context["teamName"],
            service_id=context["serviceId"],
            service_name=context["serviceName"],
            method="repository_mapping",
            confidence="high",
        )

    repo_slug = repository.split("/")[-1] if repository else "unknown"
    logger.warning(
        "Repository is not registered in the MergeFlow service catalog repo={repo} catalog_size={catalog_size}",
        repo=repository,
        catalog_size=len(list_services()),
    )
    return ServiceResolution(
        team_id="unmapped",
        team_name="Unmapped Repository",
        service_id="unmapped",
        service_name=repo_slug,
        method="unmapped",
        confidence="none",
    )
