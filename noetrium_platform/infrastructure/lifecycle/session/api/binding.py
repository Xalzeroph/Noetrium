from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .contracts import PersistentSessionSpec


@dataclass(frozen=True, slots=True)
class PersistentSessionBinding:
    """Authoritative frozen association between one session name and transport identity."""

    spec: PersistentSessionSpec
    spec_digest: str
    control_identity_digest: str

    @classmethod
    def from_spec(
        cls,
        spec: PersistentSessionSpec,
        control_identity_digest: str,
    ) -> "PersistentSessionBinding":
        if len(control_identity_digest) != 64:
            raise ValueError("persistent session control identity must be SHA-256")
        return cls(spec, spec.digest(), control_identity_digest)


class PersistentSessionBindingStorePort(Protocol):
    def read(self, session_name: str) -> PersistentSessionBinding | None: ...

    def bind_once(self, binding: PersistentSessionBinding) -> PersistentSessionBinding: ...


__all__ = ["PersistentSessionBinding", "PersistentSessionBindingStorePort"]
