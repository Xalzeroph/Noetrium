"""Paper-programmable scientific visibility semantics for RuntimeMachine.

VisibilityProgram decides what model/participant-visible view may be derived
from an already identified research-state resource.  It owns no content, memory,
authorization, context rendering, or transport.  A request binds the viewer and
the exact resource content digest; the Runtime Machine journals only the policy
decision and its reproducibility identity.

This is scientific execution visibility (private/shared/asymmetric information),
not account access control.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from threading import RLock
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import (
    JsonObject,
    JsonValue,
    MachineStatus,
    canonical_digest,
    freeze_json,
    require_sha256,
    thaw_json,
)
from .program import ProgramNodeRequest, ProgramNodeResult
from .program_host import ResearchHostOperation
from .runtime_module import RuntimeModule, RuntimeModuleBuilder


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value.strip()


def _text_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if type(value) is not tuple or any(
        type(item) is not str or not item.strip() for item in value
    ):
        raise TypeError(f"{field_name} must be a text tuple")
    values = tuple(item.strip() for item in value)
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} must be unique")
    return values


def _sequence(value: object, field_name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value, (tuple, list)
    ):
        raise TypeError(f"{field_name} must be a sequence")
    return tuple(value)


class VisibilityDisposition(StrEnum):
    FULL = "full"
    METADATA_ONLY = "metadata_only"
    PROJECTED = "projected"
    HIDDEN = "hidden"


@dataclass(frozen=True, slots=True)
class VisibilitySubject:
    subject_id: str
    roles: tuple[str, ...] = ()
    groups: tuple[str, ...] = ()
    attributes: JsonObject = field(default_factory=dict)
    subject_digest: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "subject_id",
            _text(self.subject_id, "visibility subject_id"),
        )
        object.__setattr__(
            self,
            "roles",
            _text_tuple(self.roles, "visibility subject roles"),
        )
        object.__setattr__(
            self,
            "groups",
            _text_tuple(self.groups, "visibility subject groups"),
        )
        if not isinstance(self.attributes, Mapping):
            raise TypeError("visibility subject attributes must be an object")
        object.__setattr__(self, "attributes", freeze_json(self.attributes))
        object.__setattr__(
            self,
            "subject_digest",
            canonical_digest({
                "subject_id": self.subject_id,
                "roles": self.roles,
                "groups": self.groups,
                "attributes": thaw_json(self.attributes),
            }),
        )

    def payload(self) -> JsonObject:
        return {
            "subject_id": self.subject_id,
            "roles": self.roles,
            "groups": self.groups,
            "attributes": thaw_json(self.attributes),
            "subject_digest": self.subject_digest,
        }

    @classmethod
    def from_payload(cls, value: object) -> "VisibilitySubject":
        if not isinstance(value, Mapping):
            raise TypeError("visibility subject payload must be an object")
        subject = cls(
            subject_id=value.get("subject_id"),
            roles=_sequence(
                value.get("roles", ()),
                "visibility subject roles",
            ),
            groups=_sequence(
                value.get("groups", ()),
                "visibility subject groups",
            ),
            attributes=value.get("attributes", {}),
        )
        supplied = value.get("subject_digest")
        if supplied is not None and require_sha256(
            supplied,
            "visibility subject_digest",
        ) != subject.subject_digest:
            raise ValueError("visibility subject digest mismatch")
        return subject


@dataclass(frozen=True, slots=True)
class VisibilityResource:
    resource_id: str
    resource_kind: str
    content_digest: str
    owner_id: str | None = None
    namespace: str | None = None
    labels: tuple[str, ...] = ()
    metadata: JsonObject = field(default_factory=dict)
    resource_digest: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "resource_id",
            _text(self.resource_id, "visibility resource_id"),
        )
        object.__setattr__(
            self,
            "resource_kind",
            _text(self.resource_kind, "visibility resource_kind"),
        )
        object.__setattr__(
            self,
            "content_digest",
            require_sha256(
                self.content_digest,
                "visibility resource content_digest",
            ),
        )
        if self.owner_id is not None:
            object.__setattr__(
                self,
                "owner_id",
                _text(self.owner_id, "visibility resource owner_id"),
            )
        if self.namespace is not None:
            object.__setattr__(
                self,
                "namespace",
                _text(self.namespace, "visibility resource namespace"),
            )
        object.__setattr__(
            self,
            "labels",
            _text_tuple(self.labels, "visibility resource labels"),
        )
        if not isinstance(self.metadata, Mapping):
            raise TypeError("visibility resource metadata must be an object")
        object.__setattr__(self, "metadata", freeze_json(self.metadata))
        object.__setattr__(
            self,
            "resource_digest",
            canonical_digest({
                "resource_id": self.resource_id,
                "resource_kind": self.resource_kind,
                "content_digest": self.content_digest,
                "owner_id": self.owner_id,
                "namespace": self.namespace,
                "labels": self.labels,
                "metadata": thaw_json(self.metadata),
            }),
        )

    def payload(self) -> JsonObject:
        return {
            "resource_id": self.resource_id,
            "resource_kind": self.resource_kind,
            "content_digest": self.content_digest,
            "owner_id": self.owner_id,
            "namespace": self.namespace,
            "labels": self.labels,
            "metadata": thaw_json(self.metadata),
            "resource_digest": self.resource_digest,
        }

    @classmethod
    def from_payload(cls, value: object) -> "VisibilityResource":
        if not isinstance(value, Mapping):
            raise TypeError("visibility resource payload must be an object")
        resource = cls(
            resource_id=value.get("resource_id"),
            resource_kind=value.get("resource_kind"),
            content_digest=value.get("content_digest"),
            owner_id=value.get("owner_id"),
            namespace=value.get("namespace"),
            labels=_sequence(
                value.get("labels", ()),
                "visibility resource labels",
            ),
            metadata=value.get("metadata", {}),
        )
        supplied = value.get("resource_digest")
        if supplied is not None and require_sha256(
            supplied,
            "visibility resource_digest",
        ) != resource.resource_digest:
            raise ValueError("visibility resource digest mismatch")
        return resource


@dataclass(frozen=True, slots=True)
class VisibilityRequest:
    decision_id: str
    subject: VisibilitySubject
    resource: VisibilityResource
    context: JsonObject = field(default_factory=dict)
    context_digest: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "decision_id",
            _text(self.decision_id, "visibility decision_id"),
        )
        if not isinstance(self.subject, VisibilitySubject):
            raise TypeError("visibility request requires VisibilitySubject")
        if not isinstance(self.resource, VisibilityResource):
            raise TypeError("visibility request requires VisibilityResource")
        if not isinstance(self.context, Mapping):
            raise TypeError("visibility request context must be an object")
        object.__setattr__(self, "context", freeze_json(self.context))
        object.__setattr__(
            self,
            "context_digest",
            canonical_digest(thaw_json(self.context)),
        )


@dataclass(frozen=True, slots=True)
class VisibilityDecision:
    disposition: VisibilityDisposition
    projection_profile: str | None = None
    reason_code: str = "policy"
    receipt: JsonValue = None
    decision_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, VisibilityDisposition):
            raise TypeError("visibility disposition must be VisibilityDisposition")
        if self.disposition is VisibilityDisposition.PROJECTED:
            if self.projection_profile is None:
                raise ValueError(
                    "projected visibility requires projection_profile"
                )
        elif self.projection_profile is not None:
            raise ValueError(
                "projection_profile is valid only for projected visibility"
            )
        if self.projection_profile is not None:
            object.__setattr__(
                self,
                "projection_profile",
                _text(
                    self.projection_profile,
                    "visibility projection_profile",
                ),
            )
        object.__setattr__(
            self,
            "reason_code",
            _text(self.reason_code, "visibility reason_code"),
        )
        object.__setattr__(self, "receipt", freeze_json(self.receipt))
        object.__setattr__(
            self,
            "decision_digest",
            canonical_digest({
                "disposition": self.disposition.value,
                "projection_profile": self.projection_profile,
                "reason_code": self.reason_code,
                "receipt": thaw_json(self.receipt),
            }),
        )


VisibilityDecider = Callable[[VisibilityRequest], VisibilityDecision]


@runtime_checkable
class VisibilityDeciderRegistryPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def resolve(self, decider: str) -> VisibilityDecider: ...

    def implementation_digest(self, decider: str) -> str: ...


class VisibilityDeciderRegistry(VisibilityDeciderRegistryPort):
    def __init__(self) -> None:
        self._deciders: dict[str, tuple[VisibilityDecider, str]] = {}
        self._lock = RLock()

    def register(
        self,
        decider: str,
        handler: VisibilityDecider,
        *,
        implementation_digest: str,
    ) -> None:
        decider = _text(decider, "visibility decider")
        if not callable(handler):
            raise TypeError("visibility decider must be callable")
        digest = require_sha256(
            implementation_digest,
            "visibility decider implementation_digest",
        )
        value = (handler, digest)
        with self._lock:
            current = self._deciders.get(decider)
            if current is not None and current != value:
                raise ValueError(
                    f"visibility decider already registered: {decider}"
                )
            self._deciders[decider] = value

    def resolve(self, decider: str) -> VisibilityDecider:
        decider = _text(decider, "visibility decider")
        with self._lock:
            try:
                return self._deciders[decider][0]
            except KeyError as exc:
                raise KeyError(
                    f"unbound visibility decider: {decider}"
                ) from exc

    def implementation_digest(self, decider: str) -> str:
        decider = _text(decider, "visibility decider")
        with self._lock:
            try:
                return self._deciders[decider][1]
            except KeyError as exc:
                raise KeyError(
                    f"unbound visibility decider: {decider}"
                ) from exc

    @property
    def identity_digest(self) -> str:
        with self._lock:
            return canonical_digest(tuple(
                (name, digest)
                for name, (_, digest) in sorted(self._deciders.items())
            ))


@dataclass(frozen=True, slots=True)
class VisibilityProgram:
    program_id: str
    version: str
    decider: str
    decider_digest: str
    program_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for name in ("program_id", "version", "decider"):
            object.__setattr__(
                self,
                name,
                _text(
                    getattr(self, name),
                    f"visibility program {name}",
                ),
            )
        object.__setattr__(
            self,
            "decider_digest",
            require_sha256(
                self.decider_digest,
                "visibility program decider_digest",
            ),
        )
        object.__setattr__(
            self,
            "program_digest",
            canonical_digest({
                "program_id": self.program_id,
                "version": self.version,
                "decider": self.decider,
                "decider_digest": self.decider_digest,
            }),
        )


@dataclass(slots=True)
class VisibilityRuntimeBinding:
    program: VisibilityProgram
    deciders: VisibilityDeciderRegistryPort
    decision: VisibilityDecision | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.program, VisibilityProgram):
            raise TypeError("visibility binding requires VisibilityProgram")
        if not isinstance(self.deciders, VisibilityDeciderRegistryPort):
            raise TypeError("visibility binding requires decider registry")
        require_sha256(
            self.deciders.identity_digest,
            "visibility decider registry identity_digest",
        )
        actual = require_sha256(
            self.deciders.implementation_digest(self.program.decider),
            "visibility decider implementation_digest",
        )
        if actual != self.program.decider_digest:
            raise ValueError(
                "visibility decider implementation identity drifted"
            )

    @property
    def binding_digest(self) -> str:
        return canonical_digest({
            "visibility_program_digest": self.program.program_digest,
            "registry_identity_digest": self.deciders.identity_digest,
            "decider_implementation_digest": (
                self.deciders.implementation_digest(self.program.decider)
            ),
        })


def visibility_initial_data(
    *,
    decision_id: str,
    program: VisibilityProgram,
    subject: VisibilitySubject,
    resource: VisibilityResource,
    context: JsonObject | None = None,
) -> JsonObject:
    if not isinstance(program, VisibilityProgram):
        raise TypeError("visibility initial data requires VisibilityProgram")
    if not isinstance(subject, VisibilitySubject):
        raise TypeError("visibility initial data requires VisibilitySubject")
    if not isinstance(resource, VisibilityResource):
        raise TypeError("visibility initial data requires VisibilityResource")
    context_value = {} if context is None else context
    if not isinstance(context_value, Mapping):
        raise TypeError("visibility context must be an object")
    return {
        "decision_id": _text(decision_id, "visibility decision_id"),
        "visibility_program_digest": program.program_digest,
        "subject": subject.payload(),
        "resource": resource.payload(),
        "context": dict(context_value),
        "context_digest": canonical_digest(dict(context_value)),
        "decision": None,
        "decision_digest": None,
    }


def _decide(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    if not isinstance(binding, VisibilityRuntimeBinding):
        raise TypeError(
            "runtime visibility requires VisibilityRuntimeBinding"
        )
    if (
        request.data.get("visibility_program_digest")
        != binding.program.program_digest
    ):
        raise ValueError("Runtime VisibilityProgram identity drifted")

    subject = VisibilitySubject.from_payload(request.data.get("subject"))
    resource = VisibilityResource.from_payload(request.data.get("resource"))
    context_value = request.data.get("context", {})
    if not isinstance(context_value, Mapping):
        raise TypeError("visibility Machine context must be an object")
    supplied_context_digest = request.data.get("context_digest")
    expected_context_digest = canonical_digest(dict(context_value))
    if supplied_context_digest != expected_context_digest:
        raise ValueError("visibility context digest mismatch")

    policy_request = VisibilityRequest(
        decision_id=_text(
            request.data.get("decision_id"),
            "visibility decision_id",
        ),
        subject=subject,
        resource=resource,
        context=dict(context_value),
    )
    decision = binding.deciders.resolve(binding.program.decider)(
        policy_request
    )
    if not isinstance(decision, VisibilityDecision):
        raise TypeError(
            "visibility decider must return VisibilityDecision"
        )
    binding.decision = decision

    payload = {
        "disposition": decision.disposition.value,
        "projection_profile": decision.projection_profile,
        "reason_code": decision.reason_code,
        "receipt": thaw_json(decision.receipt),
        "decision_digest": decision.decision_digest,
    }
    return ProgramNodeResult(
        value=payload,
        state_update={
            "decision": payload,
            "decision_digest": decision.decision_digest,
        },
        status=MachineStatus.COMPLETED,
        events=({
            "type": "runtime_visibility_decided",
            "decision_id": policy_request.decision_id,
            "subject_digest": subject.subject_digest,
            "resource_digest": resource.resource_digest,
            "content_digest": resource.content_digest,
            "context_digest": policy_request.context_digest,
            "disposition": decision.disposition.value,
            "projection_profile": decision.projection_profile,
            "reason_code": decision.reason_code,
            "decision_digest": decision.decision_digest,
            "decider": binding.program.decider,
            "decider_digest": binding.program.decider_digest,
        },),
    )


def visibility_runtime_module(
    program: VisibilityProgram,
    *,
    module_id: str = "runtime.visibility",
) -> RuntimeModule:
    if not isinstance(program, VisibilityProgram):
        raise TypeError(
            "visibility runtime module requires VisibilityProgram"
        )
    return (
        RuntimeModuleBuilder.visibility(
            module_id=module_id,
            entrypoint="decide",
        )
        .node(
            "decide",
            "runtime.visibility.decide",
            configuration={
                "visibility_program_digest": program.program_digest,
                "decider": program.decider,
                "decider_digest": program.decider_digest,
            },
        )
        .build()
    )


def visibility_runtime_operations() -> tuple[ResearchHostOperation, ...]:
    return (
        ResearchHostOperation(
            "runtime.visibility.decide",
            _decide,
            canonical_digest({
                "operation": "runtime.visibility.decide",
                "implementation_revision": 1,
            }),
        ),
    )


__all__ = [
    "VisibilityDecision",
    "VisibilityDecider",
    "VisibilityDeciderRegistry",
    "VisibilityDeciderRegistryPort",
    "VisibilityDisposition",
    "VisibilityProgram",
    "VisibilityRequest",
    "VisibilityResource",
    "VisibilityRuntimeBinding",
    "VisibilitySubject",
    "visibility_initial_data",
    "visibility_runtime_module",
    "visibility_runtime_operations",
]
