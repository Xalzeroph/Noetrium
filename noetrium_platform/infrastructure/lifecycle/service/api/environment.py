from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Mapping

from noetrium_platform.foundation.kernel.kernel.durability import sha256_bytes


def service_environment_digest(
    variables: Mapping[str, str] | tuple[tuple[str, str], ...],
) -> str:
    """Stable digest for a complete materialized child-process environment."""

    items = tuple(sorted(dict(variables).items()))
    raw = json.dumps(
        items,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256_bytes(raw)


@dataclass(frozen=True, slots=True)
class MaterializedServiceEnvironment:
    """Exact immutable environment value crossing the Runtime service boundary."""

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
    def from_mapping(
        cls,
        variables: Mapping[str, str],
        evidence_ref: str,
    ) -> "MaterializedServiceEnvironment":
        return cls(
            tuple(sorted((str(key), str(value)) for key, value in variables.items())),
            evidence_ref,
        )

    @property
    def digest(self) -> str:
        return service_environment_digest(self.variables)

    def as_dict(self) -> dict[str, str]:
        return dict(self.variables)


__all__ = ["MaterializedServiceEnvironment", "service_environment_digest"]
