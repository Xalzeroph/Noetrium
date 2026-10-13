from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from hashlib import sha256
import json

from noetrium_platform.capabilities.participant.core.api import ParticipantRuntimeBinding
from noetrium_platform.capabilities.participant.core.api import (
    participant_implementation_id,
    participant_implementation_kind,
)
from noetrium_platform.capabilities.participant.api.unit_semantics import (
    participant_requirement_kind,
    participant_requirement_method_id,
    participant_requirement_role,
    require_participant_requirement,
)
from noetrium_platform.foundation.kernel.kernel import canonical_bytes, canonical_digest, require_sha256
from noetrium_platform.foundation.kernel.structure import NoetriumUnit


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value


def _tokens(values: object, field_name: str) -> tuple[str, ...]:
    if type(values) is not tuple:
        raise TypeError(f"{field_name} must be a tuple")
    normalized = tuple(sorted(_text(value, field_name) for value in values))
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field_name} must not contain duplicates")
    return normalized


@dataclass(frozen=True, slots=True)
class ParticipantProviderProfile:
    provider_id: str
    supported_kinds: tuple[str, ...]
    capabilities: tuple[str, ...] = ()
    schema_version: str = "project-participant-provider.v1"

    def __post_init__(self) -> None:
        _text(self.provider_id, "participant provider_id")
        if self.schema_version != "project-participant-provider.v1":
            raise ValueError("unsupported project participant provider schema")
        object.__setattr__(
            self,
            "supported_kinds",
            _tokens(self.supported_kinds, "participant provider supported_kinds"),
        )
        object.__setattr__(
            self,
            "capabilities",
            _tokens(self.capabilities, "participant provider capabilities"),
        )

    def digest(self) -> str:
        return _participant_provider_profile_digest(
            self.provider_id, self.supported_kinds, self.capabilities, self.schema_version
        )


@lru_cache(maxsize=256)
def _participant_provider_profile_digest(
    provider_id: str,
    supported_kinds: tuple[str, ...],
    capabilities: tuple[str, ...],
    schema_version: str,
) -> str:
    # Exact canonical document produced by the frozen dataclass.
    return canonical_digest({
        "provider_id": provider_id,
        "supported_kinds": supported_kinds,
        "capabilities": capabilities,
        "schema_version": schema_version,
    })


@lru_cache(maxsize=8192)
def _participant_runtime_canonical_bytes(
    binding: ParticipantRuntimeBinding,
) -> bytes:
    return canonical_bytes(binding)


def _project_participant_binding_digest(
    requirement_digest: str,
    provider_id: str,
    provider_profile_digest: str,
    binding: ParticipantRuntimeBinding,
) -> str:
    """Hash the exact canonical dataclass document without re-expanding binding."""

    # Canonical dataclass encoding is a JSON object sorted by field name. Keep
    # this byte-for-byte identical to canonical_digest(ProjectParticipantBinding).
    enc = lambda value: json.encoder.encode_basestring(value).encode("utf-8")
    digest = sha256()
    digest.update(b'{"binding":')
    digest.update(_participant_runtime_canonical_bytes(binding))
    digest.update(b',"provider_id":')
    digest.update(enc(provider_id))
    digest.update(b',"provider_profile_digest":')
    digest.update(enc(provider_profile_digest))
    digest.update(b',"requirement_digest":')
    digest.update(enc(requirement_digest))
    digest.update(b'}')
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class ProjectParticipantBinding:
    requirement_digest: str
    provider_id: str
    provider_profile_digest: str
    binding: ParticipantRuntimeBinding

    def __post_init__(self) -> None:
        require_sha256(self.requirement_digest, "project participant requirement_digest")
        _text(self.provider_id, "project participant provider_id")
        require_sha256(
            self.provider_profile_digest,
            "project participant provider_profile_digest",
        )
        if type(self.binding) is not ParticipantRuntimeBinding:
            raise TypeError(
                "project participant binding must carry ParticipantRuntimeBinding"
            )

    @classmethod
    def from_runtime(
        cls,
        requirement: NoetriumUnit,
        profile: ParticipantProviderProfile,
        binding: ParticipantRuntimeBinding,
    ) -> "ProjectParticipantBinding":
        requirement = require_participant_requirement(requirement)
        if binding.role != participant_requirement_role(requirement):
            raise ValueError("participant binding changed requested role")
        if participant_implementation_kind(binding.implementation) != participant_requirement_kind(requirement):
            raise ValueError("participant binding changed requested implementation kind")
        if participant_implementation_id(binding.implementation) != participant_requirement_method_id(requirement):
            raise ValueError("participant binding changed requested implementation identity")
        return cls(
            requirement.unit_digest,
            profile.provider_id,
            profile.digest(),
            binding,
        )

    def digest(self) -> str:
        return _project_participant_binding_digest(
            self.requirement_digest,
            self.provider_id,
            self.provider_profile_digest,
            self.binding,
        )


class ParticipantBindingDiagnosticSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ParticipantBindingDiagnosticCode(StrEnum):
    KIND_UNSUPPORTED = "PARTICIPANT_KIND_UNSUPPORTED"
    CAPABILITY_MISSING = "PARTICIPANT_CAPABILITY_MISSING"
    RUNTIME_UNAVAILABLE = "PARTICIPANT_RUNTIME_UNAVAILABLE"
    BINDING_PROVENANCE_DRIFT = "PARTICIPANT_BINDING_PROVENANCE_DRIFT"


@dataclass(frozen=True, slots=True)
class ParticipantBindingDiagnostic:
    code: ParticipantBindingDiagnosticCode
    severity: ParticipantBindingDiagnosticSeverity
    message: str
    requirement_digest: str
    provider_id: str
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.code) is not ParticipantBindingDiagnosticCode:
            raise TypeError("participant diagnostic code must be typed")
        if type(self.severity) is not ParticipantBindingDiagnosticSeverity:
            raise TypeError("participant diagnostic severity must be typed")
        _text(self.message, "participant diagnostic message")
        require_sha256(
            self.requirement_digest,
            "participant diagnostic requirement_digest",
        )
        _text(self.provider_id, "participant diagnostic provider_id")
        if type(self.evidence_refs) is not tuple or any(
            type(ref) is not str or not ref.strip() for ref in self.evidence_refs
        ):
            raise TypeError(
                "participant diagnostic evidence_refs must be non-empty strings"
            )


class ParticipantProjectBindingError(RuntimeError):
    def __init__(
        self,
        diagnostics: tuple[ParticipantBindingDiagnostic, ...],
    ) -> None:
        if not diagnostics:
            raise ValueError("participant binding error requires diagnostics")
        self.diagnostics = diagnostics
        super().__init__("; ".join(row.message for row in diagnostics))


__all__ = [
    "ParticipantBindingDiagnostic",
    "ParticipantBindingDiagnosticCode",
    "ParticipantBindingDiagnosticSeverity",
    "ParticipantProjectBindingError",
    "ParticipantProviderProfile",
    "ProjectParticipantBinding",
]
