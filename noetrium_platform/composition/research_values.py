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
from noetrium_platform.foundation.kernel.structure import GraphStorageKind

from .research_execution_graph import (
    ResearchCompilationView,
    ResearchExecutionBinding,
)


def _text(value: str, field_name: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ValueError(f"{field_name} must be non-empty canonical text")
    return value


@dataclass(frozen=True, slots=True)
class ResearchValueSubject:
    """Semantic address for one declared NoetriumUnit output."""

    execution_cut_id: str
    graph_node_id: str
    output_name: str
    kind: GraphStorageKind
    semantic_digest: str
    subject_digest: str = field(init=False)

    def __post_init__(self) -> None:
        require_sha256(self.execution_cut_id, "research value execution_cut_id")
        _text(self.graph_node_id, "research value graph_node_id")
        _text(self.output_name, "research value output_name")
        if not isinstance(self.kind, GraphStorageKind):
            raise TypeError("research value kind must be GraphStorageKind")
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
class ResearchValueReference:
    """Routing envelope; the named lower authority remains the value truth."""

    subject: ResearchValueSubject
    authority_id: str
    authority_ref: str
    content_digest: str | None = None
    reference_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.subject) is not ResearchValueSubject:
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
class ResearchValueAuthorityPort(Protocol):
    """Adapter over an existing lower authority; owns no NoetriumUnit state."""

    @property
    def authority_id(self) -> str: ...

    @property
    def supported_kinds(self) -> frozenset[GraphStorageKind]: ...

    def publish(
        self,
        subject: ResearchValueSubject,
        value: JsonValue,
    ) -> ResearchValueReference: ...

    def lookup(
        self,
        subject: ResearchValueSubject,
    ) -> ResearchValueReference: ...

    def resolve(
        self,
        reference: ResearchValueReference,
    ) -> JsonValue: ...

    def reuse_proof(
        self,
        reference: ResearchValueReference,
    ) -> str: ...


@runtime_checkable
class ResearchValueExecutionReleasePort(Protocol):
    """Optional lower-authority release of one terminal execution reference."""

    def release_execution(
        self,
        subject: ResearchValueSubject,
    ) -> str: ...


@runtime_checkable
class ResearchValueReusePort(Protocol):
    """Optional lower-authority capability for immutable cross-cut value reuse."""

    def reuse(
        self,
        source: ResearchValueReference,
        target: ResearchValueSubject,
    ) -> ResearchValueReference: ...


class ResearchValueAuthorityMissing(RuntimeError):
    pass


class ResearchValueRouter:
    """Strict kind router over producer-owned authorities; stores no values."""

    def __init__(
        self,
        authorities: tuple[ResearchValueAuthorityPort, ...],
    ) -> None:
        if type(authorities) is not tuple:
            raise TypeError("research value router authorities must be a tuple")
        by_kind: dict[GraphStorageKind, ResearchValueAuthorityPort] = {}
        by_id: dict[str, ResearchValueAuthorityPort] = {}
        for authority in authorities:
            if not isinstance(authority, ResearchValueAuthorityPort):
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
                not isinstance(kind, GraphStorageKind) for kind in kinds
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
        kinds: frozenset[GraphStorageKind],
    ) -> None:
        if type(kinds) is not frozenset or any(
            not isinstance(kind, GraphStorageKind) for kind in kinds
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
            raise ResearchValueAuthorityMissing(
                "research value authorities are incomplete; missing="
                f"{missing}"
            )

    def authority(
        self,
        kind: GraphStorageKind,
    ) -> ResearchValueAuthorityPort:
        if not isinstance(kind, GraphStorageKind):
            raise TypeError("research value route kind must be typed")
        try:
            return self._by_kind[kind]
        except KeyError as exc:
            raise ResearchValueAuthorityMissing(
                "research value kind has no explicit authority: "
                f"{kind.value}"
            ) from exc

    def publish(
        self,
        subject: ResearchValueSubject,
        value: JsonValue,
    ) -> ResearchValueReference:
        if type(subject) is not ResearchValueSubject:
            raise TypeError("research value publish subject must be typed")
        authority = self.authority(subject.kind)
        reference = authority.publish(subject, freeze_json(value))
        self._validate_reference(reference, subject, authority)
        return reference

    def lookup(
        self,
        subject: ResearchValueSubject,
    ) -> ResearchValueReference:
        if type(subject) is not ResearchValueSubject:
            raise TypeError("research value lookup subject must be typed")
        authority = self.authority(subject.kind)
        reference = authority.lookup(subject)
        self._validate_reference(reference, subject, authority)
        return reference

    def resolve(
        self,
        reference: ResearchValueReference,
    ) -> JsonValue:
        if type(reference) is not ResearchValueReference:
            raise TypeError("research value resolve reference must be typed")
        try:
            authority = self._by_id[reference.authority_id]
        except KeyError as exc:
            raise ResearchValueAuthorityMissing(
                "research value reference authority is not explicitly bound: "
                f"{reference.authority_id}"
            ) from exc
        if reference.subject.kind not in authority.supported_kinds:
            raise ValueError("research value reference kind/authority drifted")
        return freeze_json(authority.resolve(reference))

    def release_execution(
        self,
        subject: ResearchValueSubject,
    ) -> str | None:
        """Release this execution's retention reason without deleting content.

        Authorities without explicit release semantics are left untouched.  The
        caller therefore cannot mistake router-level release for physical GC.
        """

        if type(subject) is not ResearchValueSubject:
            raise TypeError("research value execution release subject must be typed")
        authority = self.authority(subject.kind)
        if not isinstance(authority, ResearchValueExecutionReleasePort):
            return None
        return require_sha256(
            authority.release_execution(subject),
            "research value execution release proof",
        )

    def reuse(
        self,
        reference: ResearchValueReference,
        target: ResearchValueSubject,
    ) -> ResearchValueReference:
        if type(reference) is not ResearchValueReference:
            raise TypeError("research value reuse reference must be typed")
        if type(target) is not ResearchValueSubject:
            raise TypeError("research value reuse target must be typed")
        try:
            authority = self._by_id[reference.authority_id]
        except KeyError as exc:
            raise ResearchValueAuthorityMissing(
                "research value reuse authority is not explicitly bound: "
                f"{reference.authority_id}"
            ) from exc
        if reference.subject.kind not in authority.supported_kinds:
            raise ValueError("research value reuse source kind/authority drifted")
        if target.kind is not reference.subject.kind:
            raise ValueError("research value reuse target kind drifted")
        if not isinstance(authority, ResearchValueReusePort):
            raise ResearchValueAuthorityMissing(
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
        reference: ResearchValueReference,
    ) -> str:
        if type(reference) is not ResearchValueReference:
            raise TypeError("research value reuse reference must be typed")
        try:
            authority = self._by_id[reference.authority_id]
        except KeyError as exc:
            raise ResearchValueAuthorityMissing(
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
        reference: ResearchValueReference,
        subject: ResearchValueSubject,
        authority: ResearchValueAuthorityPort,
    ) -> None:
        if type(reference) is not ResearchValueReference:
            raise TypeError("research value authority returned invalid reference")
        if reference.subject != subject:
            raise ValueError("research value authority changed semantic subject")
        if reference.authority_id != authority.authority_id:
            raise ValueError("research value authority reference identity drifted")


def required_research_value_kinds(
    compilation: ResearchCompilationView,
    *,
    selected_node_ids: tuple[str, ...] | None = None,
) -> frozenset[GraphStorageKind]:
    if type(compilation) is not ResearchCompilationView:
        raise TypeError("research value kind analysis requires compiled graph")
    nodes: tuple[ResearchExecutionBinding, ...]
    if selected_node_ids is None:
        nodes = compilation.bindings
    else:
        if type(selected_node_ids) is not tuple or not selected_node_ids or any(
            type(node_id) is not str or not node_id.strip()
            for node_id in selected_node_ids
        ):
            raise TypeError("research value selection must be a non-empty text tuple")
        selected = set(selected_node_ids)
        if len(selected) != len(selected_node_ids):
            raise ValueError("research value selection node ids must be unique")
        resolved_nodes: list[ResearchExecutionBinding] = []
        unknown: list[str] = []
        for node_id in selected_node_ids:
            try:
                resolved_nodes.append(compilation.binding(node_id))
            except KeyError:
                unknown.append(node_id)
        if unknown:
            raise ValueError(
                "research value selection references unknown nodes: "
                f"{tuple(sorted(unknown))}"
            )
        nodes = tuple(resolved_nodes)
    kinds = {
        output.type_ref.storage_kind
        for node in nodes
        for output in node.graph.boundary.outputs
    }
    kinds.update(
        edge.storage_kind
        for node in nodes
        for edge in node.incoming_edges
        if edge.target_port is not None
    )
    return frozenset(kinds)


def validate_research_value_authorities(
    compilation: ResearchCompilationView,
    values: ResearchValueRouter,
    *,
    selected_node_ids: tuple[str, ...] | None = None,
) -> None:
    if type(values) is not ResearchValueRouter:
        raise TypeError("research value validation requires ResearchValueRouter")
    values.require_kinds(
        required_research_value_kinds(
            compilation,
            selected_node_ids=selected_node_ids,
        )
    )


def _node_by_ref(
    compilation: ResearchCompilationView,
    ref,
) -> ResearchExecutionBinding:
    from noetrium_platform.foundation.kernel.structure import UnitRef

    if type(ref) is not UnitRef:
        raise TypeError("research graph lookup requires UnitRef")
    return compilation.binding_by_ref(ref)


def lookup_research_node_input_references(
    execution_cut_id: str,
    compilation: ResearchCompilationView,
    node: ResearchExecutionBinding,
    values: ResearchValueRouter,
) -> dict[str, ResearchValueReference]:
    """Resolve exact typed input references without collapsing authority identity."""

    require_sha256(execution_cut_id, "research input execution_cut_id")
    if type(compilation) is not ResearchCompilationView:
        raise TypeError("research input resolution requires compiled graph")
    if type(node) is not ResearchExecutionBinding:
        raise TypeError("research input resolution requires compiled graph node")
    if compilation.binding(node.graph_node_id) != node:
        raise ValueError("research input node does not belong to compilation")
    if type(values) is not ResearchValueRouter:
        raise TypeError("research input resolution requires ResearchValueRouter")

    references: dict[str, ResearchValueReference] = {}
    for edge in node.incoming_edges:
        if edge.target_port is None:
            continue
        if edge.source_port is None:
            raise ValueError(
                "typed research input edge is missing an upstream source port"
            )
        upstream = _node_by_ref(compilation, edge.upstream)
        try:
            output_type = upstream.output_type(edge.source_port)
        except KeyError as exc:
            raise ValueError(
                "research input edge references an undeclared upstream output"
            ) from exc
        if output_type.type_digest != edge.type_ref.type_digest:
            raise ValueError(
                "research input edge semantic type drifted from upstream output schema"
            )
        subject = ResearchValueSubject(
            execution_cut_id,
            upstream.graph_node_id,
            edge.source_port,
            edge.storage_kind,
            upstream.semantic_digest,
        )
        reference = values.lookup(subject)
        if edge.target_port in references:
            raise ValueError(
                "research input reference name was bound more than once"
            )
        references[edge.target_port] = reference
    return references


def resolve_research_node_inputs(
    execution_cut_id: str,
    compilation: ResearchCompilationView,
    node: ResearchExecutionBinding,
    values: ResearchValueRouter,
) -> JsonObject:
    """Resolve exact typed inputs through their owning lower authorities."""

    references = lookup_research_node_input_references(
        execution_cut_id,
        compilation,
        node,
        values,
    )
    return {
        input_name: values.resolve(reference)
        for input_name, reference in references.items()
    }


def publish_research_node_outputs(
    execution_cut_id: str,
    node: ResearchExecutionBinding,
    values: ResearchValueRouter,
    result: JsonValue,
) -> tuple[ResearchValueReference, ...]:
    """Publish declared outputs; no implicit authority or undeclared output exists."""

    require_sha256(execution_cut_id, "research output execution_cut_id")
    if type(node) is not ResearchExecutionBinding:
        raise TypeError("research output publication requires compiled graph node")
    if type(values) is not ResearchValueRouter:
        raise TypeError("research output publication requires ResearchValueRouter")
    outputs = node.graph.boundary.outputs
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
        subject = ResearchValueSubject(
            execution_cut_id,
            node.graph_node_id,
            output.name,
            output.type_ref.storage_kind,
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
    "ResearchValueAuthorityMissing",
    "ResearchValueAuthorityPort",
    "ResearchValueReference",
    "ResearchValueExecutionReleasePort",
    "ResearchValueReusePort",
    "ResearchValueRouter",
    "ResearchValueSubject",
    "lookup_research_node_input_references",
    "publish_research_node_outputs",
    "required_research_value_kinds",
    "resolve_research_node_inputs",
    "validate_research_value_authorities",
]
