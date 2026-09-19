from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Mapping, Protocol


def service_environment_digest(variables: Mapping[str, str] | tuple[tuple[str, str], ...]) -> str:
    """Stable digest for a *complete* child-process environment.

    The caller must provide the entire environment. The service layer never merges
    os.environ implicitly because that would make launches host-dependent.
    """

    items = tuple(sorted(dict(variables).items()))
    raw = json.dumps(items, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class MaterializedServiceEnvironment:
    variables: tuple[tuple[str, str], ...]
    evidence_ref: str

    def __post_init__(self) -> None:
        keys = [key for key, _ in self.variables]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate service environment variable")
        for key, value in self.variables:
            if not key or "=" in key or "\x00" in key:
                raise ValueError("invalid service environment variable name")
            if "\x00" in value:
                raise ValueError("service environment variable contains NUL")
        if not self.evidence_ref:
            raise ValueError("environment materialization requires an evidence ref")

    @classmethod
    def from_mapping(cls, variables: Mapping[str, str], evidence_ref: str) -> "MaterializedServiceEnvironment":
        return cls(tuple(sorted((str(k), str(v)) for k, v in variables.items())), evidence_ref)

    @property
    def digest(self) -> str:
        return service_environment_digest(self.variables)

    def as_dict(self) -> dict[str, str]:
        return dict(self.variables)


class ServiceEnvironmentProvider(Protocol):
    """Secret/config authority that materializes the exact frozen environment by digest."""

    def resolve(self, environment_digest: str) -> MaterializedServiceEnvironment: ...


class StaticServiceEnvironmentProvider:
    """Simple exact provider useful for local deployments and tests."""

    def __init__(self, environments: tuple[MaterializedServiceEnvironment, ...]) -> None:
        self._by_digest = {environment.digest: environment for environment in environments}
        if len(self._by_digest) != len(environments):
            raise ValueError("duplicate materialized environment digest")

    def resolve(self, environment_digest: str) -> MaterializedServiceEnvironment:
        try:
            return self._by_digest[environment_digest]
        except KeyError as exc:
            raise KeyError(f"no materialized service environment for {environment_digest}") from exc


__all__ = [
    "MaterializedServiceEnvironment",
    "ServiceEnvironmentProvider",
    "StaticServiceEnvironmentProvider",
    "service_environment_digest",
]
