from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import (
    JsonObject,
    JsonValue,
    canonical_digest,
    freeze_json,
    require_sha256,
)
from noetrium_platform.product.research_os import ResearchValueKind

from .research_os_graph import (
    CompiledResearchOSGraph,
    CompiledResearchOSGraphNode,
)


def _text(value: str, field_name: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ValueError(f"{field_name} must be non-empty canonical text")
    return value


@dataclass(frozen=True, slots=True)
class ResearchOSValueSubject:
    """Semantic address for one declared ResearchGraph output."""

    execution_cut_id: str
    graph_node_id: str
    output_name: str
    kind: ResearchValueKind
    semantic_digest: str
    subject_digest: str = field(init=False)

    def __post_init__(self) -> None:
        require_sha256(self.execution_cut_id, "research value execution_cut_id")
        _text(self.graph_node_id, "research value graph_node_id")
        _text(self.output_name, "research value output_name")
        if not isinstance(self.kind, ResearchValueKind):
            raise TypeError("research value kind must be ResearchValueKind")
        require_sha256(self.semantic_digest, "research value semantic_digest")
        object.__setattr__(
            self,
            "subject_digest",
            canonical_digest(
                {
                    "execution_cut_id": self.execution_cut_id,
                    "graph_node_id": self.graph_node_id,
                    "output_name": self.output_name,
                    "kind": self.kind.value,
                    "semantic_digest": self.semantic_digest,
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class ResearchOSValueReference:
    """Routing envelope; the named lower authority remains the value truth."""

    subject: ResearchOSValueSubject
    authority_id: str
    authority_ref: str
    content_digest: str | None = None
    reference_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.subject) is not ResearchOSValueSubject:
            raise TypeError("research value reference subject must be typed")
        _text(self.authority_id, "research value authority_id")
        _text(self.authority_ref, "research value authority_ref")
        if self.content_digest is not None:
            require_sha256(self.content_digest, "research value content_digest")
        object.__setattr__(
            self,
            "reference_digest",
            canonical_digest(
                {
                    "subject_digest": self.subject.subject_digest,
                    "authority_id": self.authority_id,
                    "authority_ref": self.authority_ref,
                    "content_digest": self.content_digest,
                }
            ),
        )


@runtime_checkable
class ResearchOSValueAuthorityPort(Protocol):
    """Adapter over an existing lower authority; owns no ResearchGraph state."""

    @property
    def authority_id(self) -> str: ...

    @property
    def supported_kinds(self) -> frozenset[ResearchValueKind]: ...

    def publish(
        self,
        subject: ResearchOSValueSubject,
        value: JsonValue,
    ) -> ResearchOSValueReference: ...

    def lookup(
        self,
        subject: ResearchOSValueSubject,
    ) -> ResearchOSValueReference: ...

    def resolve(
        self,
        reference: ResearchOSValueReference,
    ) -> JsonValue: ...

    def reuse_proof(
        self,
        reference: ResearchOSValueReference,
    ) -> str: ...


@runtime_checkable
class ResearchOSValueExecutionReleasePort(Protocol):
    """Optional lower-authority release of one terminal execution reference."""

    def release_execution(
        self,
        subject: ResearchOSValueSubject,
    ) -> str: ...


@runtime_checkable
class ResearchOSValueReusePort(Protocol):
    """Optional lower-authority capability for immutable cross-cut value reuse."""

    def reuse(
        self,
        source: ResearchOSValueReference,
        target: ResearchOSValueSubject,
    ) -> ResearchOSValueReference: ...


class ResearchOSValueAuthorityMissing(RuntimeError):
    pass


class ResearchOSValueRouter:
    """Strict kind router over producer-owned authorities; stores no values."""

    def __init__(
        self,
        authorities: tuple[ResearchOSValueAuthorityPort, ...],
    ) -> None:
        if type(authorities) is not tuple:
            raise TypeError("research value router authorities must be a tuple")
        by_kind: dict[ResearchValueKind, ResearchOSValueAuthorityPort] = {}
        by_id: dict[str, ResearchOSValueAuthorityPort] = {}
        for authority in authorities:
            if not isinstance(authority, ResearchOSValueAuthorityPort):
                raise TypeError("research value authority does not satisfy typed port")
            authority_id = _text(
                authority.authority_id,
                "research value authority_id",
            )
            if authority_id in by_id:
                raise ValueError(
                    f"duplicate research value authority: {authority_id}"
                )
            kinds = authority.supported_kinds
            if type(kinds) is not frozenset or not kinds or any(
                not isinstance(kind, ResearchValueKind) for kind in kinds
            ):
                raise TypeError(
                    "research value authority supported_kinds must be a "
                    "non-empty typed frozenset"
                )
            for kind in kinds:
                if kind in by_kind:
                    raise ValueError(
                        "research value kind has multiple authorities: "
                        f"{kind.value}"
                    )
                by_kind[kind] = authority
            by_id[authority_id] = authority
        self._by_kind = by_kind
        self._by_id = by_id

    def require_kinds(
        self,
        kinds: frozenset[ResearchValueKind],
    ) -> None:
        if type(kinds) is not frozenset or any(
            not isinstance(kind, ResearchValueKind) for kind in kinds
        ):
            raise TypeError("research value required kinds must be typed")
        missing = tuple(
            sorted(
                kind.value
                for kind in kinds
                if kind not in self._by_kind
            )
        )
        if missing:
            raise ResearchOSValueAuthorityMissing(
                "research value authorities are incomplete; missing="
                f"{missing}"
            )

    def authority(
        self,
        kind: ResearchValueKind,
    ) -> ResearchOSValueAuthorityPort:
        if not isinstance(kind, ResearchValueKind):
            raise TypeError("research value route kind must be typed")
        try:
            return self._by_kind[kind]
        except KeyError as exc:
            raise ResearchOSValueAuthorityMissing(
                "research value kind has no explicit authority: "
                f"{kind.value}"
            ) from exc

    def publish(
        self,
        subject: ResearchOSValueSubject,
        value: JsonValue,
    ) -> ResearchOSValueReference:
        if type(subject) is not ResearchOSValueSubject:
            raise TypeError("research value publish subject must be typed")
        authority = self.authority(subject.kind)
        reference = authority.publish(subject, freeze_json(value))
        self._validate_reference(reference, subject, authority)
        return reference

    def lookup(
        self,
        subject: ResearchOSValueSubject,
    ) -> ResearchOSValueReference:
        if type(subject) is not ResearchOSValueSubject:
            raise TypeError("research value lookup subject must be typed")
        authority = self.authority(subject.kind)
        reference = authority.lookup(subject)
        self._validate_reference(reference, subject, authority)
        return reference

    def resolve(
        self,
        reference: ResearchOSValueReference,
    ) -> JsonValue:
        if type(reference) is not ResearchOSValueReference:
            raise TypeError("research value resolve reference must be typed")
        try:
            authority = self._by_id[reference.authority_id]
        except KeyError as exc:
            raise ResearchOSValueAuthorityMissing(
                "research value reference authority is not explicitly bound: "
                f"{reference.authority_id}"
            ) from exc
        if reference.subject.kind not in authority.supported_kinds:
            raise ValueError("research value reference kind/authority drifted")
        return freeze_json(authority.resolve(reference))

    def release_execution(
        self,
        subject: ResearchOSValueSubject,
    ) -> str | None:
        """Release this execution's retention reason without deleting content.

        Authorities without explicit release semantics are left untouched.  The
        caller therefore cannot mistake router-level release for physical GC.
        """

        if type(subject) is not ResearchOSValueSubject:
            raise TypeError("research value execution release subject must be typed")
        authority = self.authority(subject.kind)
        if not isinstance(authority, ResearchOSValueExecutionReleasePort):
            return None
        return require_sha256(
            authority.release_execution(subject),
            "research value execution release proof",
        )

    def reuse(
        self,
        reference: ResearchOSValueReference,
        target: ResearchOSValueSubject,
    ) -> ResearchOSValueReference:
        if type(reference) is not ResearchOSValueReference:
            raise TypeError("research value reuse reference must be typed")
        if type(target) is not ResearchOSValueSubject:
            raise TypeError("research value reuse target must be typed")
        try:
            authority = self._by_id[reference.authority_id]
        except KeyError as exc:
            raise ResearchOSValueAuthorityMissing(
                "research value reuse authority is not explicitly bound: "
                f"{reference.authority_id}"
            ) from exc
        if reference.subject.kind not in authority.supported_kinds:
            raise ValueError("research value reuse source kind/authority drifted")
        if target.kind is not reference.subject.kind:
            raise ValueError("research value reuse target kind drifted")
        if not isinstance(authority, ResearchOSValueReusePort):
            raise ResearchOSValueAuthorityMissing(
                "research value authority does not support immutable cross-cut reuse: "
                f"{reference.authority_id}"
            )
        reused = authority.reuse(reference, target)
        self._validate_reference(reused, target, authority)
        if reused.authority_id != reference.authority_id:
            raise ValueError("research value reuse changed authority identity")
        return reused

    def reuse_proof(
        self,
        reference: ResearchOSValueReference,
    ) -> str:
        if type(reference) is not ResearchOSValueReference:
            raise TypeError("research value reuse reference must be typed")
        try:
            authority = self._by_id[reference.authority_id]
        except KeyError as exc:
            raise ResearchOSValueAuthorityMissing(
                "research value reference authority is not explicitly bound: "
                f"{reference.authority_id}"
            ) from exc
        if reference.subject.kind not in authority.supported_kinds:
            raise ValueError("research value reuse kind/authority drifted")
        return require_sha256(
            authority.reuse_proof(reference),
            "research value authority reuse proof",
        )

    @staticmethod
    def _validate_reference(
        reference: ResearchOSValueReference,
        subject: ResearchOSValueSubject,
        authority: ResearchOSValueAuthorityPort,
    ) -> None:
        if type(reference) is not ResearchOSValueReference:
            raise TypeError("research value authority returned invalid reference")
        if reference.subject != subject:
            raise ValueError("research value authority changed semantic subject")
        if reference.authority_id != authority.authority_id:
            raise ValueError("research value authority reference identity drifted")


def required_research_os_value_kinds(
    compilation: CompiledResearchOSGraph,
    *,
    selected_node_ids: tuple[str, ...] | None = None,
) -> frozenset[ResearchValueKind]:
    if type(compilation) is not CompiledResearchOSGraph:
        raise TypeError("research value kind analysis requires compiled graph")
    nodes = compilation.nodes
    if selected_node_ids is not None:
        if type(selected_node_ids) is not tuple or not selected_node_ids or any(
            type(node_id) is not str or not node_id.strip()
            for node_id in selected_node_ids
        ):
            raise TypeError("research value selection must be a non-empty text tuple")
        selected = set(selected_node_ids)
        if len(selected) != len(selected_node_ids):
            raise ValueError("research value selection node ids must be unique")
        known = {node.graph_node_id for node in compilation.nodes}
        unknown = tuple(sorted(selected - known))
        if unknown:
            raise ValueError(
                f"research value selection references unknown nodes: {unknown}"
            )
        nodes = tuple(
            node for node in compilation.nodes if node.graph_node_id in selected
        )
    kinds = {
        output.kind
        for node in nodes
        for output in node.node.outputs
    }
    kinds.update(
        binding.kind
        for node in nodes
        for edge in node.incoming_edges
        for binding in edge.bindings
    )
    return frozenset(kinds)


def validate_research_os_value_authorities(
    compilation: CompiledResearchOSGraph,
    values: ResearchOSValueRouter,
    *,
    selected_node_ids: tuple[str, ...] | None = None,
) -> None:
    if type(values) is not ResearchOSValueRouter:
        raise TypeError("research value validation requires ResearchOSValueRouter")
    values.require_kinds(
        required_research_os_value_kinds(
            compilation,
            selected_node_ids=selected_node_ids,
        )
    )


def _node_by_ref(
    compilation: CompiledResearchOSGraph,
    program_id: str,
    node_id: str,
) -> CompiledResearchOSGraphNode:
    for row in compilation.nodes:
        if row.ref.program_id == program_id and row.ref.node_id == node_id:
            return row
    raise KeyError(f"{program_id}::{node_id}")


def lookup_research_os_node_input_references(
    execution_cut_id: str,
    compilation: CompiledResearchOSGraph,
    node: CompiledResearchOSGraphNode,
    values: ResearchOSValueRouter,
) -> dict[str, ResearchOSValueReference]:
    """Resolve exact typed input references without collapsing authority identity."""

    require_sha256(execution_cut_id, "research input execution_cut_id")
    if type(compilation) is not CompiledResearchOSGraph:
        raise TypeError("research input resolution requires compiled graph")
    if type(node) is not CompiledResearchOSGraphNode:
        raise TypeError("research input resolution requires compiled graph node")
    if compilation.node(node.graph_node_id) != node:
        raise ValueError("research input node does not belong to compilation")
    if type(values) is not ResearchOSValueRouter:
        raise TypeError("research input resolution requires ResearchOSValueRouter")

    references: dict[str, ResearchOSValueReference] = {}
    for edge in node.incoming_edges:
        upstream = _node_by_ref(
            compilation,
            edge.upstream.program_id,
            edge.upstream.node_id,
        )
        declared_outputs = {
            output.name: output.kind
            for output in upstream.node.outputs
        }
        for binding in edge.bindings:
            if declared_outputs.get(binding.output_name) is not binding.kind:
                raise ValueError(
                    "research input binding drifted from upstream output schema"
                )
            subject = ResearchOSValueSubject(
                execution_cut_id,
                upstream.graph_node_id,
                binding.output_name,
                binding.kind,
                upstream.semantic_digest,
            )
            reference = values.lookup(subject)
            if binding.input_name in references:
                raise ValueError(
                    "research input reference name was bound more than once"
                )
            references[binding.input_name] = reference
    return references


def resolve_research_os_node_inputs(
    execution_cut_id: str,
    compilation: CompiledResearchOSGraph,
    node: CompiledResearchOSGraphNode,
    values: ResearchOSValueRouter,
) -> JsonObject:
    """Resolve exact typed inputs through their owning lower authorities."""

    references = lookup_research_os_node_input_references(
        execution_cut_id,
        compilation,
        node,
        values,
    )
    return {
        input_name: values.resolve(reference)
        for input_name, reference in references.items()
    }


def publish_research_os_node_outputs(
    execution_cut_id: str,
    node: CompiledResearchOSGraphNode,
    values: ResearchOSValueRouter,
    result: JsonValue,
) -> tuple[ResearchOSValueReference, ...]:
    """Publish declared outputs; no implicit authority or undeclared output exists."""

    require_sha256(execution_cut_id, "research output execution_cut_id")
    if type(node) is not CompiledResearchOSGraphNode:
        raise TypeError("research output publication requires compiled graph node")
    if type(values) is not ResearchOSValueRouter:
        raise TypeError("research output publication requires ResearchOSValueRouter")
    outputs = node.node.outputs
    if not outputs:
        if result is not None:
            raise ValueError(
                "research node returned a value without declaring outputs"
            )
        return ()
    if len(outputs) == 1:
        payloads: dict[str, JsonValue] = {outputs[0].name: result}
    else:
        if not isinstance(result, Mapping):
            raise TypeError(
                "research node with multiple outputs must return a mapping "
                "by output name"
            )
        expected = {output.name for output in outputs}
        actual = set(result)
        if actual != expected:
            raise ValueError(
                "research node multi-output result keys do not match declared outputs"
            )
        payloads = {
            name: freeze_json(result[name])
            for name in expected
        }

    references = []
    for output in outputs:
        subject = ResearchOSValueSubject(
            execution_cut_id,
            node.graph_node_id,
            output.name,
            output.kind,
            node.semantic_digest,
        )
        references.append(
            values.publish(
                subject,
                freeze_json(payloads[output.name]),
            )
        )
    return tuple(references)


__all__ = [
    "ResearchOSValueAuthorityMissing",
    "ResearchOSValueAuthorityPort",
    "ResearchOSValueReference",
    "ResearchOSValueExecutionReleasePort",
    "ResearchOSValueReusePort",
    "ResearchOSValueRouter",
    "ResearchOSValueSubject",
    "lookup_research_os_node_input_references",
    "publish_research_os_node_outputs",
    "required_research_os_value_kinds",
    "resolve_research_os_node_inputs",
    "validate_research_os_value_authorities",
]
