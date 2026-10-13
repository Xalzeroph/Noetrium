from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DeploymentStatusIdentity:
    deployment_id: str
    stack_digest: str
    qualification_digest: str


__all__ = ["DeploymentStatusIdentity"]
