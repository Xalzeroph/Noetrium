from __future__ import annotations

from typing import Protocol

from noetrium_platform.infrastructure.lifecycle.service.api.environment import (
    MaterializedServiceEnvironment,
)


class ServiceEnvironmentProvider(Protocol):
    """Resolve one exact materialized environment by its frozen digest."""

    def resolve(self, environment_digest: str) -> MaterializedServiceEnvironment: ...


class StaticServiceEnvironmentProvider:
    def __init__(
        self,
        environments: tuple[MaterializedServiceEnvironment, ...],
    ) -> None:
        self._by_digest = {
            environment.digest: environment
            for environment in environments
        }
        if len(self._by_digest) != len(environments):
            raise ValueError("duplicate materialized environment digest")

    def resolve(
        self,
        environment_digest: str,
    ) -> MaterializedServiceEnvironment:
        try:
            return self._by_digest[environment_digest]
        except KeyError as exc:
            raise KeyError(
                f"no materialized service environment for {environment_digest}"
            ) from exc


__all__ = ["ServiceEnvironmentProvider", "StaticServiceEnvironmentProvider"]
