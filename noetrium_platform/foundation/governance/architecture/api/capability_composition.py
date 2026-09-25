"""Public contracts for frozen, typed composition plans.

Projects and systems may depend on these values and the planner port. Concrete
validation remains in ``governance.architecture.runtime`` and is injected only
at a composition boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import inspect
import re
from typing import Generic, Protocol, TypeVar

from noetrium_platform.foundation.governance.system_registry.api import SystemIdentity
from noetrium_platform.foundation.kernel.kernel import Sha256Digest, canonical_digest
from noetrium_platform.foundation.scope.api import ScopeIdentity


_TOKEN = re.compile(r"[a-z][a-z0-9_.-]*")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_BINDING_REQUIREMENT = TypeVar("_BINDING_REQUIREMENT")
_BINDING_PAYLOAD = TypeVar("_BINDING_PAYLOAD")


class CompositionContractError(ValueError):
    """A capability contract cannot be safely represented in a binding plan."""


class CompositionTopologyError(CompositionContractError):
    """A composition root attempts to compose a non-local subject."""


class CapabilityBindingError(CompositionContractError):
    """A requirement cannot be bound; machine semantics live in ``diagnostic``."""

    def __init__(self, diagnostic: "BindingDiagnostic") -> None:
        if not isinstance(diagnostic, BindingDiagnostic):
            raise TypeError("capability binding error requires typed BindingDiagnostic")
        self.diagnostic = diagnostic
        super().__init__(diagnostic.summary)


class MissingCapabilityProvider(CapabilityBindingError):
    pass


class AmbiguousCapabilityProvider(CapabilityBindingError):
    pass


class CapabilityInterfaceMismatch(CapabilityBindingError):
    pass


class CapabilityDependencyCycle(CompositionContractError):
    """Graph-level cycle error; unlike one-requirement failures it has no diagnostic envelope."""

    def __init__(self, message: str) -> None:
        CompositionContractError.__init__(self, message)


class RequirementCardinality(StrEnum):
    EXACTLY_ONE = "exactly_one"
    ONE_OR_MORE = "one_or_more"


class BindingDiagnosticSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class BindingDiagnosticReferenceKind(StrEnum):
    IDENTITY = "identity"
    EVIDENCE = "evidence"


class BindingResolutionState(StrEnum):
    BOUND = "bound"
    DIAGNOSTIC = "diagnostic"


class BindingRemediationCategory(StrEnum):
    NONE = "none"
    CONFIGURATION = "configuration"
    PROVIDER_SELECTION = "provider_selection"
    CAPABILITY = "capability"
    INTERFACE = "interface"
    TOPOLOGY = "topology"
    DEPENDENCY = "dependency"
    QUALIFICATION = "qualification"
    OWNER_ACTION = "owner_action"


@dataclass(frozen=True, slots=True, order=True)
class BindingDiagnosticCode:
    """Stable namespaced code value without owning domain-specific enumerations."""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not _TOKEN.fullmatch(self.value) or "." not in self.value:
            raise CompositionContractError(
                "binding diagnostic code must be a lowercase namespaced token"
            )

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True, order=True)
class BindingDiagnosticReference:
    kind: BindingDiagnosticReferenceKind
    reference_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, BindingDiagnosticReferenceKind):
            raise CompositionContractError("binding diagnostic reference kind must be typed")
        if (
            not isinstance(self.reference_id, str)
            or not self.reference_id.strip()
            or self.reference_id != self.reference_id.strip()
        ):
            raise CompositionContractError("binding diagnostic reference_id must be canonical non-empty text")


class CompositionSubjectKind(StrEnum):
    """Topology-governed system or independently composed project."""

    SYSTEM = "system"
    PROJECT = "project"


@dataclass(frozen=True, slots=True, order=True)
class CompositionSubject:
    """Owner/consumer identity without turning a project into a system node."""

    kind: CompositionSubjectKind
    subject_id: str
    system: SystemIdentity | None = None

    def __post_init__(self) -> None:
        if not self.subject_id.strip():
            raise CompositionContractError("composition subject_id must be non-empty")
        if self.kind is CompositionSubjectKind.SYSTEM:
            if self.system is None or self.subject_id != self.system.key:
                raise CompositionContractError(
                    "a system composition subject must carry its exact SystemIdentity"
                )
        elif self.system is not None:
            raise CompositionContractError("a project composition subject cannot carry SystemIdentity")

    @classmethod
    def system_subject(cls, identity: SystemIdentity) -> "CompositionSubject":
        return cls(CompositionSubjectKind.SYSTEM, identity.key, identity)

    @classmethod
    def project_subject(cls, project_id: str, version: str) -> "CompositionSubject":
        if not project_id.strip() or not version.strip():
            raise CompositionContractError("project composition identity requires id and version")
        return cls(CompositionSubjectKind.PROJECT, f"{project_id}@{version}")

    @property
    def key(self) -> str:
        return f"{self.kind.value}:{self.subject_id}"


@dataclass(frozen=True, slots=True, order=True)
class CapabilityKey:
    """Stable public identity of one composition-time capability."""

    namespace: str
    name: str
    major_version: int

    def __post_init__(self) -> None:
        if not _TOKEN.fullmatch(self.namespace):
            raise CompositionContractError("capability namespace must be a lowercase dotted token")
        if not _TOKEN.fullmatch(self.name):
            raise CompositionContractError("capability name must be a lowercase dotted token")
        if self.major_version <= 0:
            raise CompositionContractError("capability major_version must be positive")

    @property
    def value(self) -> str:
        return f"{self.namespace}.{self.name}.v{self.major_version}"


def _public_interface_members(base: type) -> dict[str, dict[str, str]]:
    """Materialize one MRO level; total work is linear in that level's members."""

    rows: dict[str, dict[str, str]] = {}
    for name, member in base.__dict__.items():
        if name.startswith("_"):
            continue
        if isinstance(member, property):
            getter = member.fget
            signature = str(inspect.signature(getter)) if getter is not None else ""
            rows[name] = {"name": name, "kind": "property", "signature": signature}
        elif callable(member):
            rows[name] = {
                "name": name,
                "kind": "callable",
                "signature": str(inspect.signature(member)),
            }
    return rows


def interface_contract_digest(interface: type) -> str:
    """Fingerprint the effective public callable/property surface of a port.

    Inherited members are part of the ABI. Walking the MRO from least to most
    specific preserves normal Python override semantics while preventing a
    parent Protocol signature change from leaving a child port digest stale.
    Runtime is O(N log N) for N total public members because each MRO level is
    visited once and only the final effective member names are sorted.
    """

    resolved: dict[str, dict[str, str]] = {}
    for base in reversed(interface.__mro__):
        if base is not object:
            resolved.update(_public_interface_members(base))
    members = tuple(resolved[name] for name in sorted(resolved))
    return canonical_digest(
        {"module": interface.__module__, "qualname": interface.__qualname__, "members": members}
    )


def _require_digest(value: str, field: str) -> None:
    if not _DIGEST.fullmatch(value):
        raise CompositionContractError(f"{field} must be a lowercase SHA-256 digest")


@dataclass(frozen=True, slots=True, order=True)
class RequirementAddress:
    consumer: CompositionSubject
    requirement_id: str

    def __post_init__(self) -> None:
        if not _TOKEN.fullmatch(self.requirement_id):
            raise CompositionContractError("requirement_id must be a lowercase dotted token")

    @property
    def value(self) -> str:
        return f"{self.consumer.key}:{self.requirement_id}"


@dataclass(frozen=True, slots=True)
class BindingDiagnostic:
    """Neutral machine projection of a producer-owned binding diagnosis."""

    code: BindingDiagnosticCode
    severity: BindingDiagnosticSeverity
    blocking: bool
    owner: CompositionSubject
    subject: CompositionSubject
    requirement_digest: Sha256Digest
    summary: str
    requirement: RequirementAddress | None = None
    provider_identity: str | None = None
    provider_profile_digest: Sha256Digest | None = None
    related_refs: tuple[BindingDiagnosticReference, ...] = ()
    remediation: BindingRemediationCategory = BindingRemediationCategory.NONE
    remediation_action: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, BindingDiagnosticCode):
            raise CompositionContractError("binding diagnostic code must be typed")
        if not isinstance(self.severity, BindingDiagnosticSeverity):
            raise CompositionContractError("binding diagnostic severity must be typed")
        if not isinstance(self.blocking, bool):
            raise CompositionContractError("binding diagnostic blocking must be bool")
        if not isinstance(self.owner, CompositionSubject) or not isinstance(self.subject, CompositionSubject):
            raise CompositionContractError("binding diagnostic owner/subject must be typed")
        if not isinstance(self.requirement_digest, Sha256Digest):
            raise CompositionContractError("binding diagnostic requirement_digest must be typed")
        if not isinstance(self.summary, str) or not self.summary.strip():
            raise CompositionContractError("binding diagnostic summary must be non-empty")
        if self.requirement is not None and not isinstance(self.requirement, RequirementAddress):
            raise CompositionContractError("binding diagnostic requirement must be typed")
        if self.requirement is not None and self.requirement.consumer != self.subject:
            raise CompositionContractError(
                "binding diagnostic requirement consumer must equal diagnostic subject"
            )
        if self.provider_identity is not None and (
            not isinstance(self.provider_identity, str) or not self.provider_identity.strip()
        ):
            raise CompositionContractError("binding diagnostic provider_identity must be non-empty")
        if self.provider_profile_digest is not None and not isinstance(
            self.provider_profile_digest, Sha256Digest
        ):
            raise CompositionContractError("binding diagnostic provider_profile_digest must be typed")
        if not isinstance(self.related_refs, tuple) or any(
            not isinstance(ref, BindingDiagnosticReference) for ref in self.related_refs
        ):
            raise CompositionContractError("binding diagnostic related_refs must be typed")
        ordered_refs = tuple(sorted(self.related_refs, key=lambda ref: (ref.kind.value, ref.reference_id)))
        if len(ordered_refs) != len(set(ordered_refs)):
            raise CompositionContractError("binding diagnostic related_refs must be unique")
        object.__setattr__(self, "related_refs", ordered_refs)
        if not isinstance(self.remediation, BindingRemediationCategory):
            raise CompositionContractError("binding diagnostic remediation must be typed")
        if self.remediation_action is not None and (
            not isinstance(self.remediation_action, str)
            or not _TOKEN.fullmatch(self.remediation_action)
            or "." not in self.remediation_action
        ):
            raise CompositionContractError(
                "binding diagnostic remediation_action must be a namespaced token"
            )

    @property
    def machine_digest(self) -> str:
        """Machine identity intentionally excludes the human rendering summary."""
        return canonical_digest({
            "code": self.code.value,
            "severity": self.severity.value,
            "blocking": self.blocking,
            "owner": self.owner.key,
            "subject": self.subject.key,
            "requirement_digest": self.requirement_digest.value,
            "requirement": self.requirement.value if self.requirement is not None else None,
            "provider_identity": self.provider_identity,
            "provider_profile_digest": (
                self.provider_profile_digest.value
                if self.provider_profile_digest is not None else None
            ),
            "related_refs": tuple(
                (ref.kind.value, ref.reference_id) for ref in self.related_refs
            ),
            "remediation": self.remediation.value,
            "remediation_action": self.remediation_action,
        })


@dataclass(frozen=True, slots=True)
class BindingProof:
    """Neutral proof metadata paired with a producer-owned typed binding payload."""

    owner: CompositionSubject
    subject: CompositionSubject
    requirement_digest: Sha256Digest
    provider_identity: str
    provider_profile_digest: Sha256Digest
    binding_generation: str
    evidence_refs: tuple[BindingDiagnosticReference, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.owner, CompositionSubject) or not isinstance(self.subject, CompositionSubject):
            raise CompositionContractError("binding proof owner/subject must be typed")
        if not isinstance(self.requirement_digest, Sha256Digest):
            raise CompositionContractError("binding proof requirement_digest must be typed")
        if not isinstance(self.provider_identity, str) or not self.provider_identity.strip():
            raise CompositionContractError("binding proof provider_identity must be non-empty")
        if not isinstance(self.provider_profile_digest, Sha256Digest):
            raise CompositionContractError("binding proof provider_profile_digest must be typed")
        if not isinstance(self.binding_generation, str) or not _TOKEN.fullmatch(self.binding_generation):
            raise CompositionContractError("binding proof binding_generation must be a canonical token")
        if not isinstance(self.evidence_refs, tuple) or any(
            not isinstance(ref, BindingDiagnosticReference)
            or ref.kind is not BindingDiagnosticReferenceKind.EVIDENCE
            for ref in self.evidence_refs
        ):
            raise CompositionContractError("binding proof evidence_refs must be typed evidence references")
        ordered_refs = tuple(sorted(self.evidence_refs, key=lambda ref: ref.reference_id))
        if len(ordered_refs) != len(set(ordered_refs)):
            raise CompositionContractError("binding proof evidence_refs must be unique")
        object.__setattr__(self, "evidence_refs", ordered_refs)

    @property
    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class BindingResolution(Generic[_BINDING_PAYLOAD]):
    """Exactly one successful typed binding or one blocking diagnostic set."""

    binding: _BINDING_PAYLOAD | None = None
    proof: BindingProof | None = None
    diagnostics: tuple[BindingDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        if self.binding is not None:
            if not isinstance(self.proof, BindingProof) or self.diagnostics:
                raise CompositionContractError(
                    "successful binding resolution requires proof and no diagnostics"
                )
            return
        if self.proof is not None or not self.diagnostics:
            raise CompositionContractError(
                "diagnostic binding resolution requires diagnostics and no proof"
            )
        if not isinstance(self.diagnostics, tuple):
            raise CompositionContractError("binding resolution diagnostics must be an immutable tuple")
        if any(not isinstance(item, BindingDiagnostic) for item in self.diagnostics):
            raise CompositionContractError("binding resolution diagnostics must be typed")
        if not any(item.blocking for item in self.diagnostics):
            raise CompositionContractError(
                "diagnostic binding resolution requires at least one blocking diagnostic"
            )
        ordered = tuple(sorted(
            self.diagnostics,
            key=lambda item: (
                item.code.value, item.requirement_digest.value,
                item.provider_identity or "", item.machine_digest,
            ),
        ))
        if len({item.machine_digest for item in ordered}) != len(ordered):
            raise CompositionContractError("binding resolution diagnostics must be machine-unique")
        object.__setattr__(self, "diagnostics", ordered)

    @property
    def state(self) -> BindingResolutionState:
        return (
            BindingResolutionState.BOUND
            if self.binding is not None else BindingResolutionState.DIAGNOSTIC
        )

    @property
    def projection_digest(self) -> str:
        """Digest the neutral envelope only; domain payload identity remains producer-owned."""
        if self.binding is not None:
            assert self.proof is not None
            return canonical_digest({"state": self.state.value, "proof": self.proof.digest})
        return canonical_digest({
            "state": self.state.value,
            "diagnostics": tuple(item.machine_digest for item in self.diagnostics),
        })

    @classmethod
    def bound(
        cls, binding: _BINDING_PAYLOAD, proof: BindingProof
    ) -> "BindingResolution[_BINDING_PAYLOAD]":
        return cls(binding=binding, proof=proof)

    @classmethod
    def diagnosed(
        cls, diagnostics: tuple[BindingDiagnostic, ...]
    ) -> "BindingResolution[_BINDING_PAYLOAD]":
        return cls(diagnostics=diagnostics)


class BindingResolverPort(Protocol[_BINDING_REQUIREMENT, _BINDING_PAYLOAD]):
    """Producer-owned resolver with one common binding-or-diagnostics result shape."""

    def resolve(
        self, requirement: _BINDING_REQUIREMENT
    ) -> BindingResolution[_BINDING_PAYLOAD]: ...


@dataclass(frozen=True, slots=True)
class CapabilityOffer:
    """One provider candidate; it contains identity, never the provider object."""

    offer_id: str
    owner: CompositionSubject
    scope: ScopeIdentity
    capability: CapabilityKey
    interface_digest: str
    provider_identity: str
    configuration_digest: str
    exported_to_descendants: bool = True

    def __post_init__(self) -> None:
        if not _TOKEN.fullmatch(self.offer_id):
            raise CompositionContractError("offer_id must be a lowercase dotted token")
        if not self.provider_identity.strip():
            raise CompositionContractError("provider_identity must be non-empty")
        _require_digest(self.interface_digest, "interface_digest")
        _require_digest(self.configuration_digest, "configuration_digest")


@dataclass(frozen=True, slots=True)
class CapabilityRequirement:
    """One typed dependency declared by the consuming subject."""

    address: RequirementAddress
    scope: ScopeIdentity
    capability: CapabilityKey
    interface_digest: str
    cardinality: RequirementCardinality = RequirementCardinality.EXACTLY_ONE
    optional: bool = False

    def __post_init__(self) -> None:
        _require_digest(self.interface_digest, "interface_digest")


@dataclass(frozen=True, slots=True)
class CompositionContract:
    """All composition-facing offers and requirements of one local subject."""

    subject: CompositionSubject
    scope: ScopeIdentity
    offers: tuple[CapabilityOffer, ...] = ()
    requirements: tuple[CapabilityRequirement, ...] = ()

    def __post_init__(self) -> None:
        offer_ids = [offer.offer_id for offer in self.offers]
        if len(offer_ids) != len(set(offer_ids)):
            raise CompositionContractError(f"duplicate offer id in {self.subject.key}")
        requirement_ids = [requirement.address.requirement_id for requirement in self.requirements]
        if len(requirement_ids) != len(set(requirement_ids)):
            raise CompositionContractError(f"duplicate requirement id in {self.subject.key}")
        for offer in self.offers:
            if offer.owner != self.subject or offer.scope != self.scope:
                raise CompositionContractError("an offer must be owned at its contract subject and scope")
        for requirement in self.requirements:
            if requirement.address.consumer != self.subject or requirement.scope != self.scope:
                raise CompositionContractError(
                    "a requirement must be consumed at its contract subject and scope"
                )


@dataclass(frozen=True, slots=True)
class ProviderSelection:
    """Explicit provider policy when a requirement has more than one candidate."""

    requirement: RequirementAddress
    offer_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.offer_ids:
            raise CompositionContractError("provider selection must name at least one offer")
        if len(self.offer_ids) != len(set(self.offer_ids)):
            raise CompositionContractError("provider selection contains a duplicate offer")


@dataclass(frozen=True, slots=True)
class CompositionIdentity:
    """Identity of one recursive composition root and its immutable scope."""

    composition_id: str
    scope: ScopeIdentity
    owner: CompositionSubject
    parent_plan_digest: str | None = None

    def __post_init__(self) -> None:
        if not _TOKEN.fullmatch(self.composition_id):
            raise CompositionContractError("composition_id must be a lowercase dotted token")
        if self.parent_plan_digest is not None:
            _require_digest(self.parent_plan_digest, "parent_plan_digest")


@dataclass(frozen=True, slots=True)
class BindingEdge:
    requirement: RequirementAddress
    offer: CapabilityOffer


@dataclass(frozen=True, slots=True)
class BindingPlan:
    """Frozen, inspectable wiring evidence; it never stores runtime objects."""

    identity: CompositionIdentity
    contracts: tuple[CompositionContract, ...]
    imported_offers: tuple[CapabilityOffer, ...]
    edges: tuple[BindingEdge, ...]
    digest: str

    def bindings_for(self, requirement: RequirementAddress) -> tuple[BindingEdge, ...]:
        return tuple(edge for edge in self.edges if edge.requirement == requirement)


class CapabilityCompositionPlannerPort(Protocol):
    """Project-safe planner port injected by an outer composition boundary."""

    def freeze(
        self,
        identity: CompositionIdentity,
        contracts: tuple[CompositionContract, ...],
        *,
        imported_offers: tuple[CapabilityOffer, ...] = (),
        selections: tuple[ProviderSelection, ...] = (),
    ) -> BindingPlan: ...


__all__ = [
    "AmbiguousCapabilityProvider",
    "BindingDiagnostic",
    "BindingDiagnosticCode",
    "BindingDiagnosticReference",
    "BindingDiagnosticReferenceKind",
    "BindingDiagnosticSeverity",
    "BindingEdge",
    "BindingPlan",
    "BindingProof",
    "BindingRemediationCategory",
    "BindingResolution",
    "BindingResolutionState",
    "BindingResolverPort",
    "CapabilityBindingError",
    "CapabilityCompositionPlannerPort",
    "CapabilityDependencyCycle",
    "CapabilityInterfaceMismatch",
    "CapabilityKey",
    "CapabilityOffer",
    "CapabilityRequirement",
    "CompositionContract",
    "CompositionContractError",
    "CompositionIdentity",
    "CompositionSubject",
    "CompositionSubjectKind",
    "CompositionTopologyError",
    "MissingCapabilityProvider",
    "ProviderSelection",
    "RequirementAddress",
    "RequirementCardinality",
    "interface_contract_digest",
]
