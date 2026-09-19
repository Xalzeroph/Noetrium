"""Neutral identity contracts for qualified external capability providers.

These contracts pin an external implementation and its qualification facts without
exposing SDK, CLI, MCP, HTTP, package-manager, or service-native types to consumers.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re

from noetrium_platform.foundation.governance.api import RepositorySourceIndexPort
from noetrium_platform.foundation.kernel.kernel import Sha256Digest, canonical_digest, require_sha256

_TOKEN = re.compile(r"[a-z][a-z0-9_.-]*")
_GIT_COMMIT = re.compile(r"[0-9a-f]{40}")
_OCI_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
_EXACT_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+:/@-]*")
_MUTABLE_ALIASES = frozenset({"latest", "main", "master", "head", "stable", "current"})


class ProviderIngressContractError(ValueError):
    """Provider ingress identity is not exact enough for governance use."""


class ProviderRevisionKind(StrEnum):
    """Revision forms accepted by the neutral provider qualification boundary."""

    GIT_COMMIT = "git_commit"
    CONTENT_SHA256 = "content_sha256"
    OCI_SHA256 = "oci_sha256"
    PACKAGE_VERSION = "package_version"
    SERVICE_REVISION = "service_revision"


@dataclass(frozen=True, slots=True, order=True)
class ProviderIngressProtocol:
    """Open ingress/adapter identity such as ``mcp``, ``sdk.python`` or ``http``."""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or _TOKEN.fullmatch(self.value) is None:
            raise ProviderIngressContractError("provider ingress protocol must be a canonical open token")




_MODULE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")


@dataclass(frozen=True, slots=True, order=True)
class ProviderIngressBoundary:
    """Public declaration of the only package allowed to import one provider-native implementation."""

    provider_identity: str
    ingress: ProviderIngressProtocol
    adapter_module_prefix: str
    implementation_import_prefixes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.provider_identity, str) or not self.provider_identity.strip():
            raise ProviderIngressContractError("provider ingress boundary requires provider identity")
        if not isinstance(self.ingress, ProviderIngressProtocol):
            raise ProviderIngressContractError("provider ingress boundary requires typed ingress")
        if _MODULE.fullmatch(self.adapter_module_prefix) is None:
            raise ProviderIngressContractError("adapter_module_prefix must be a canonical Python module prefix")
        prefixes = tuple(sorted(self.implementation_import_prefixes))
        if not prefixes or any(_MODULE.fullmatch(value) is None for value in prefixes):
            raise ProviderIngressContractError("implementation_import_prefixes must contain Python module prefixes")
        if len(prefixes) != len(set(prefixes)):
            raise ProviderIngressContractError("implementation_import_prefixes must be unique")
        for index, prefix in enumerate(prefixes):
            if any(
                prefix.startswith(other + ".") or other.startswith(prefix + ".")
                for other in prefixes[index + 1 :]
            ):
                raise ProviderIngressContractError("implementation import prefixes must not overlap")
        object.__setattr__(self, "implementation_import_prefixes", prefixes)


@dataclass(frozen=True, slots=True, order=True)
class ProviderIngressViolation:
    """Machine-readable static evidence that provider-native types escaped their adapter."""

    code: str
    path: str
    line: int
    imported_module: str
    provider_identity: str | None
    detail: str


@dataclass(frozen=True, slots=True, order=True)
class ProviderRevision:
    """One exact implementation revision; mutable aliases are not representable."""

    kind: ProviderRevisionKind
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ProviderRevisionKind):
            raise ProviderIngressContractError("provider revision kind must be typed")
        if self.kind is ProviderRevisionKind.GIT_COMMIT:
            if not isinstance(self.value, str) or _GIT_COMMIT.fullmatch(self.value) is None:
                raise ProviderIngressContractError("git provider revision must be a full lowercase commit id")
            return
        if self.kind is ProviderRevisionKind.CONTENT_SHA256:
            try:
                require_sha256(self.value, "provider content revision")
            except (TypeError, ValueError) as exc:
                raise ProviderIngressContractError(str(exc)) from exc
            return
        if self.kind is ProviderRevisionKind.OCI_SHA256:
            if not isinstance(self.value, str) or _OCI_SHA256.fullmatch(self.value) is None:
                raise ProviderIngressContractError("OCI provider revision must be sha256:<lowercase digest>")
            return
        if (
            not isinstance(self.value, str)
            or self.value != self.value.strip()
            or _EXACT_VERSION.fullmatch(self.value) is None
            or self.value.lower() in _MUTABLE_ALIASES
        ):
            raise ProviderIngressContractError(
                "package/service revision must be canonical exact version text, not a mutable alias"
            )


@dataclass(frozen=True, slots=True)
class ProviderImplementationIdentity:
    """Exact implementation identity plus immutable provenance/descriptor digest.

    ``implementation_id`` names the upstream package/service/source/image. The
    revision records its ecosystem-native exact revision. ``provenance_digest``
    binds the immutable source/package descriptor, lock, image manifest, or service
    qualification descriptor so a version label cannot become authority by itself.
    """

    implementation_id: str
    revision: ProviderRevision
    provenance_digest: Sha256Digest

    def __post_init__(self) -> None:
        if (
            not isinstance(self.implementation_id, str)
            or not self.implementation_id.strip()
            or self.implementation_id != self.implementation_id.strip()
        ):
            raise ProviderIngressContractError("provider implementation_id must be canonical non-empty text")
        if not isinstance(self.revision, ProviderRevision):
            raise ProviderIngressContractError("provider implementation revision must be typed")
        if not isinstance(self.provenance_digest, Sha256Digest):
            raise ProviderIngressContractError("provider provenance_digest must be typed")

    @property
    def digest(self) -> Sha256Digest:
        return Sha256Digest(canonical_digest({
            "implementation_id": self.implementation_id,
            "revision_kind": self.revision.kind.value,
            "revision": self.revision.value,
            "provenance_digest": self.provenance_digest.value,
        }))


def provider_implementation_from_repository_source(
    implementation_id: str, source_index: RepositorySourceIndexPort
) -> ProviderImplementationIdentity:
    """Pin one Git-backed immutable repository cut for provider qualification."""
    revision = source_index.source_revision
    if revision is None:
        raise ProviderIngressContractError(
            "provider qualification requires an exact resolved repository revision"
        )
    return ProviderImplementationIdentity(
        implementation_id=implementation_id,
        revision=ProviderRevision(ProviderRevisionKind.GIT_COMMIT, revision),
        provenance_digest=Sha256Digest(source_index.source_digest),
    )


@dataclass(frozen=True, slots=True)
class ProviderQualificationIdentity:
    """Neutral qualification identity suitable for ``BindingProof.provider_profile_digest``."""

    provider_identity: str
    implementation: ProviderImplementationIdentity
    ingress: ProviderIngressProtocol
    capability_contract_digest: Sha256Digest
    adapter_contract_digest: Sha256Digest
    qualification_evidence_digest: Sha256Digest

    def __post_init__(self) -> None:
        if (
            not isinstance(self.provider_identity, str)
            or not self.provider_identity.strip()
            or self.provider_identity != self.provider_identity.strip()
        ):
            raise ProviderIngressContractError("provider_identity must be canonical non-empty text")
        if not isinstance(self.implementation, ProviderImplementationIdentity):
            raise ProviderIngressContractError("provider qualification implementation must be typed")
        if not isinstance(self.ingress, ProviderIngressProtocol):
            raise ProviderIngressContractError("provider qualification ingress must be typed")
        for field_name in (
            "capability_contract_digest",
            "adapter_contract_digest",
            "qualification_evidence_digest",
        ):
            if not isinstance(getattr(self, field_name), Sha256Digest):
                raise ProviderIngressContractError(f"{field_name} must be typed")

    @property
    def profile_digest(self) -> Sha256Digest:
        return Sha256Digest(canonical_digest({
            "provider_identity": self.provider_identity,
            "implementation": self.implementation.digest.value,
            "ingress": self.ingress.value,
            "capability_contract_digest": self.capability_contract_digest.value,
            "adapter_contract_digest": self.adapter_contract_digest.value,
            "qualification_evidence_digest": self.qualification_evidence_digest.value,
        }))


__all__ = [
    "ProviderImplementationIdentity",
    "ProviderIngressBoundary",
    "ProviderIngressContractError",
    "ProviderIngressProtocol",
    "ProviderIngressViolation",
    "ProviderQualificationIdentity",
    "ProviderRevision",
    "ProviderRevisionKind",
    "provider_implementation_from_repository_source",
]
