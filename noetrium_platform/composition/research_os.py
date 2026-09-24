from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from noetrium_platform.evidence.artifact.content.api import (
    ArtifactBlobRef,
    ArtifactBlobStorePort,
)
from noetrium_platform.foundation.kernel.kernel import (
    canonical_bytes,
    canonical_digest,
    strict_json_loads,
)
from noetrium_platform.foundation.portfolio.api import (
    PortfolioRevision,
    PortfolioRevisionStorePort,
)
from noetrium_platform.product.research_os import (
    RESEARCH_PORTFOLIO_SCHEMA,
    ResearchBranch,
    ResearchControlAction,
    ResearchControlReceipt,
    ResearchControlRequest,
    ResearchDefinition,
    ResearchDefinitionKind,
    ResearchDependency,
    ResearchGraphRevision,
    ResearchImpactState,
    ResearchImplementation,
    ResearchMethodProgramBindingKind,
    ResearchMethodProgramImplementation,
    ResearchInputBinding,
    ResearchNode,
    ResearchNodeImpact,
    ResearchNodeKind,
    ResearchNodeRef,
    ResearchOS,
    ResearchOutputSpec,
    ResearchPortfolio,
    ResearchPortfolioDependency,
    ResearchProgram,
    ResearchRevisionDiff,
    ResearchTag,
    ResearchValueKind,
    _research_portfolio_document,
    bind_research_os,
)


RESEARCH_PORTFOLIO_MEDIA_TYPE = "application/vnd.noetrium.research-portfolio.v3+json"


def _object(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def _array(value: object, field: str) -> tuple[object, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    return tuple(value)


def _text(value: object, field: str) -> str:
    if type(value) is not str:
        raise ValueError(f"{field} must be text")
    return value


def _exact(value: dict[str, object], fields: frozenset[str], field: str) -> None:
    if set(value) != fields:
        raise ValueError(f"{field} fields are not canonical")


def _decode_binding(value: object, field: str) -> ResearchInputBinding:
    row = _object(value, field)
    _exact(row, frozenset({"input_name", "output_name", "kind"}), field)
    return ResearchInputBinding(
        _text(row["input_name"], field + ".input_name"),
        _text(row["output_name"], field + ".output_name"),
        ResearchValueKind(_text(row["kind"], field + ".kind")),
    )


def _decode_implementation(
    value: object,
    field: str,
) -> ResearchImplementation | ResearchMethodProgramImplementation:
    row = _object(value, field)
    implementation_type = _text(
        row.get("implementation_type"),
        field + ".implementation_type",
    )
    if implementation_type == "callable":
        _exact(
            row,
            frozenset(
                {
                    "implementation_type",
                    "implementation_id",
                    "module",
                    "qualname",
                    "source_digest",
                    "implementation_digest",
                }
            ),
            field,
        )
        implementation: ResearchImplementation | ResearchMethodProgramImplementation = (
            ResearchImplementation(
                _text(row["implementation_id"], field + ".implementation_id"),
                _text(row["module"], field + ".module"),
                _text(row["qualname"], field + ".qualname"),
                _text(row["source_digest"], field + ".source_digest"),
            )
        )
    elif implementation_type == "method_program":
        _exact(
            row,
            frozenset(
                {
                    "implementation_type",
                    "implementation_id",
                    "module",
                    "qualname",
                    "program_digest",
                    "binding_kind",
                    "factory_args",
                    "factory_kwargs",
                    "implementation_digest",
                }
            ),
            field,
        )
        implementation = ResearchMethodProgramImplementation(
            _text(row["implementation_id"], field + ".implementation_id"),
            _text(row["module"], field + ".module"),
            _text(row["qualname"], field + ".qualname"),
            _text(row["program_digest"], field + ".program_digest"),
            ResearchMethodProgramBindingKind(
                _text(row["binding_kind"], field + ".binding_kind")
            ),
            tuple(
                _array(row["factory_args"], field + ".factory_args")
            ),
            _object(row["factory_kwargs"], field + ".factory_kwargs"),
        )
    else:
        raise ValueError(
            f"{field}.implementation_type is not canonical: "
            f"{implementation_type!r}"
        )
    if implementation.implementation_digest != _text(
        row["implementation_digest"], field + ".implementation_digest"
    ):
        raise ValueError("research implementation digest mismatch")
    return implementation


def _decode_definition(value: object, field: str) -> ResearchDefinition:
    row = _object(value, field)
    _exact(
        row,
        frozenset(
            {
                "definition_id",
                "kind",
                "implementation",
                "config",
                "definition_digest",
            }
        ),
        field,
    )
    implementation_raw = row["implementation"]
    definition = ResearchDefinition(
        _text(row["definition_id"], field + ".definition_id"),
        ResearchDefinitionKind(_text(row["kind"], field + ".kind")),
        (
            None
            if implementation_raw is None
            else _decode_implementation(
                implementation_raw,
                field + ".implementation",
            )
        ),
        row["config"],
    )
    if definition.definition_digest != _text(
        row["definition_digest"], field + ".definition_digest"
    ):
        raise ValueError("research definition digest mismatch")
    return definition


def _decode_output(value: object, field: str) -> ResearchOutputSpec:
    row = _object(value, field)
    _exact(row, frozenset({"name", "kind"}), field)
    return ResearchOutputSpec(
        _text(row["name"], field + ".name"),
        ResearchValueKind(_text(row["kind"], field + ".kind")),
    )


def _decode_node(value: object, field: str) -> ResearchNode:
    row = _object(value, field)
    _exact(
        row,
        frozenset(
            {
                "node_id",
                "kind",
                "definition_ids",
                "outputs",
                "config",
                "node_digest",
            }
        ),
        field,
    )
    node = ResearchNode(
        _text(row["node_id"], field + ".node_id"),
        ResearchNodeKind(_text(row["kind"], field + ".kind")),
        tuple(
            _text(item, field + ".definition_ids[]")
            for item in _array(row["definition_ids"], field + ".definition_ids")
        ),
        tuple(
            _decode_output(item, field + ".outputs[]")
            for item in _array(row["outputs"], field + ".outputs")
        ),
        row["config"],
    )
    if node.node_digest != _text(row["node_digest"], field + ".node_digest"):
        raise ValueError("research node digest mismatch")
    return node


def _decode_dependency(value: object, field: str) -> ResearchDependency:
    row = _object(value, field)
    _exact(
        row,
        frozenset(
            {
                "upstream_node_id",
                "downstream_node_id",
                "bindings",
                "dependency_digest",
            }
        ),
        field,
    )
    dependency = ResearchDependency(
        _text(row["upstream_node_id"], field + ".upstream_node_id"),
        _text(row["downstream_node_id"], field + ".downstream_node_id"),
        tuple(
            _decode_binding(item, field + ".bindings[]")
            for item in _array(row["bindings"], field + ".bindings")
        ),
    )
    if dependency.dependency_digest != _text(
        row["dependency_digest"], field + ".dependency_digest"
    ):
        raise ValueError("research dependency digest mismatch")
    return dependency


def _decode_program(value: object, field: str) -> ResearchProgram:
    row = _object(value, field)
    _exact(
        row,
        frozenset(
            {
                "program_id",
                "definitions",
                "nodes",
                "dependencies",
                "program_digest",
            }
        ),
        field,
    )
    program = ResearchProgram(
        _text(row["program_id"], field + ".program_id"),
        tuple(
            _decode_definition(item, field + ".definitions[]")
            for item in _array(row["definitions"], field + ".definitions")
        ),
        tuple(
            _decode_node(item, field + ".nodes[]")
            for item in _array(row["nodes"], field + ".nodes")
        ),
        tuple(
            _decode_dependency(item, field + ".dependencies[]")
            for item in _array(row["dependencies"], field + ".dependencies")
        ),
    )
    if program.program_digest != _text(
        row["program_digest"], field + ".program_digest"
    ):
        raise ValueError("research program digest mismatch")
    return program


def _decode_ref(value: object, field: str) -> ResearchNodeRef:
    row = _object(value, field)
    _exact(row, frozenset({"program_id", "node_id"}), field)
    return ResearchNodeRef(
        _text(row["program_id"], field + ".program_id"),
        _text(row["node_id"], field + ".node_id"),
    )


def _decode_portfolio_dependency(
    value: object,
    field: str,
) -> ResearchPortfolioDependency:
    row = _object(value, field)
    _exact(
        row,
        frozenset({"upstream", "downstream", "bindings", "dependency_digest"}),
        field,
    )
    dependency = ResearchPortfolioDependency(
        _decode_ref(row["upstream"], field + ".upstream"),
        _decode_ref(row["downstream"], field + ".downstream"),
        tuple(
            _decode_binding(item, field + ".bindings[]")
            for item in _array(row["bindings"], field + ".bindings")
        ),
    )
    if dependency.dependency_digest != _text(
        row["dependency_digest"], field + ".dependency_digest"
    ):
        raise ValueError("research portfolio dependency digest mismatch")
    return dependency


def encode_research_portfolio(portfolio: ResearchPortfolio) -> bytes:
    if type(portfolio) is not ResearchPortfolio:
        raise TypeError("research portfolio encoding requires ResearchPortfolio")
    raw = canonical_bytes(_research_portfolio_document(portfolio))
    ref_digest = canonical_digest(_research_portfolio_document(portfolio))
    if ref_digest != portfolio.portfolio_digest:
        raise ValueError("research portfolio semantic digest drifted during encoding")
    return raw


def decode_research_portfolio(raw: bytes) -> ResearchPortfolio:
    if type(raw) is not bytes:
        raise TypeError("research portfolio payload must be bytes")
    document = strict_json_loads(raw)
    root = _object(document, "research portfolio")
    _exact(
        root,
        frozenset({"schema", "portfolio_id", "programs", "dependencies"}),
        "research portfolio",
    )
    if _text(root["schema"], "research portfolio.schema") != RESEARCH_PORTFOLIO_SCHEMA:
        raise ValueError("unsupported research portfolio schema")
    portfolio = ResearchPortfolio(
        _text(root["portfolio_id"], "research portfolio.portfolio_id"),
        tuple(
            _decode_program(item, "research portfolio.programs[]")
            for item in _array(root["programs"], "research portfolio.programs")
        ),
        tuple(
            _decode_portfolio_dependency(
                item,
                "research portfolio.dependencies[]",
            )
            for item in _array(
                root["dependencies"],
                "research portfolio.dependencies",
            )
        ),
    )
    canonical = encode_research_portfolio(portfolio)
    if raw != canonical:
        raise ValueError("research portfolio payload is not canonical")
    return portfolio


def _local_node_digests(
    portfolio: ResearchPortfolio,
) -> dict[ResearchNodeRef, str]:
    rows: dict[ResearchNodeRef, str] = {}
    for program in portfolio.programs:
        definitions = {
            definition.definition_id: definition
            for definition in program.definitions
        }
        for node in program.nodes:
            refs = tuple(
                (
                    definition_id,
                    definitions[definition_id].definition_digest,
                )
                for definition_id in node.definition_ids
            )
            ref = ResearchNodeRef(program.program_id, node.node_id)
            rows[ref] = canonical_digest(
                {
                    "node_digest": node.node_digest,
                    "definitions": refs,
                }
            )
    return rows


def _incoming_edges(
    portfolio: ResearchPortfolio,
) -> dict[ResearchNodeRef, tuple[tuple[ResearchNodeRef, str], ...]]:
    rows: dict[ResearchNodeRef, list[tuple[ResearchNodeRef, str]]] = {
        ResearchNodeRef(program.program_id, node.node_id): []
        for program in portfolio.programs
        for node in program.nodes
    }
    for program in portfolio.programs:
        for dependency in program.dependencies:
            upstream = ResearchNodeRef(
                program.program_id,
                dependency.upstream_node_id,
            )
            downstream = ResearchNodeRef(
                program.program_id,
                dependency.downstream_node_id,
            )
            rows[downstream].append((upstream, dependency.dependency_digest))
    for dependency in portfolio.dependencies:
        rows[dependency.downstream].append(
            (dependency.upstream, dependency.dependency_digest)
        )
    return {
        ref: tuple(
            sorted(
                edges,
                key=lambda row: (
                    row[0].program_id,
                    row[0].node_id,
                    row[1],
                ),
            )
        )
        for ref, edges in rows.items()
    }


def _semantic_node_fingerprints(
    portfolio: ResearchPortfolio,
) -> tuple[dict[ResearchNodeRef, str], dict[ResearchNodeRef, str]]:
    local = _local_node_digests(portfolio)
    incoming = _incoming_edges(portfolio)
    memo: dict[ResearchNodeRef, str] = {}

    def fingerprint(ref: ResearchNodeRef) -> str:
        current = memo.get(ref)
        if current is not None:
            return current
        value = canonical_digest(
            {
                "local": local[ref],
                "incoming": tuple(
                    {
                        "program_id": upstream.program_id,
                        "node_id": upstream.node_id,
                        "dependency_digest": dependency_digest,
                        "upstream_fingerprint": fingerprint(upstream),
                    }
                    for upstream, dependency_digest in incoming[ref]
                ),
            }
        )
        memo[ref] = value
        return value

    for ref in sorted(local, key=lambda value: (value.program_id, value.node_id)):
        fingerprint(ref)
    return local, memo


def diff_research_portfolios(
    left: ResearchPortfolio,
    right: ResearchPortfolio,
    *,
    left_revision_digest: str,
    right_revision_digest: str,
) -> ResearchRevisionDiff:
    if type(left) is not ResearchPortfolio or type(right) is not ResearchPortfolio:
        raise TypeError("research diff requires ResearchPortfolio values")
    if left.portfolio_id != right.portfolio_id:
        raise ValueError("research diff portfolios must share identity")
    left_local, left_semantic = _semantic_node_fingerprints(left)
    right_local, right_semantic = _semantic_node_fingerprints(right)
    refs = sorted(
        set(left_local) | set(right_local),
        key=lambda value: (value.program_id, value.node_id),
    )
    same_revision = left_revision_digest == right_revision_digest
    impacts: list[ResearchNodeImpact] = []
    for ref in refs:
        if ref not in left_local:
            state = ResearchImpactState.NEW
        elif ref not in right_local:
            state = ResearchImpactState.REMOVED
        elif left_local[ref] != right_local[ref]:
            state = ResearchImpactState.INVALIDATED
        elif left_semantic[ref] != right_semantic[ref]:
            state = ResearchImpactState.STALE
        else:
            state = (
                ResearchImpactState.UNCHANGED
                if same_revision
                else ResearchImpactState.REUSABLE
            )
        impacts.append(ResearchNodeImpact(ref.program_id, ref.node_id, state))
    return ResearchRevisionDiff(
        left.portfolio_id,
        left_revision_digest,
        right_revision_digest,
        tuple(impacts),
    )


@runtime_checkable
class ResearchOSControlPort(Protocol):
    """Internal execution control over an already verified immutable portfolio."""

    def control(
        self,
        request: ResearchControlRequest,
        portfolio: ResearchPortfolio,
    ) -> ResearchControlReceipt: ...


@runtime_checkable
class ResearchOSRevisionMigrationPort(Protocol):
    """Internal bridge that binds live execution migration to durable revisions."""

    def active_revision_digest(self, execution_id: str) -> str: ...

    def migrate(
        self,
        request: ResearchControlRequest,
        source_revision: ResearchGraphRevision,
        source_portfolio: ResearchPortfolio,
        target_portfolio: ResearchPortfolio,
    ) -> ResearchControlReceipt: ...


class PortfolioBackedResearchOSPort:
    """Durable revision/diff/ref implementation over existing authorities."""

    def __init__(
        self,
        revisions: PortfolioRevisionStorePort,
        blobs: ArtifactBlobStorePort,
        *,
        control: ResearchOSControlPort | None = None,
    ) -> None:
        if not isinstance(revisions, PortfolioRevisionStorePort):
            raise TypeError("Research OS revisions must satisfy PortfolioRevisionStorePort")
        if not isinstance(blobs, ArtifactBlobStorePort):
            raise TypeError("Research OS blobs must satisfy ArtifactBlobStorePort")
        if control is not None and not isinstance(control, ResearchOSControlPort):
            raise TypeError("Research OS control must satisfy ResearchOSControlPort")
        self._revisions = revisions
        self._blobs = blobs
        self._control = control

    @staticmethod
    def _public_revision(value: PortfolioRevision) -> ResearchGraphRevision:
        revision = ResearchGraphRevision(
            value.subject_id,
            value.payload_digest,
            value.parent_revision_digests,
            value.message,
        )
        if revision.revision_digest != value.revision_digest:
            raise RuntimeError("Research OS revision identity drifted from Portfolio")
        return revision

    def _stored_revision(self, revision: ResearchGraphRevision) -> PortfolioRevision:
        stored = self._revisions.revision(
            revision.portfolio_id,
            revision.revision_digest,
        )
        if self._public_revision(stored) != revision:
            raise ValueError("Research OS revision does not match durable Portfolio state")
        return stored

    def _load(self, revision: ResearchGraphRevision) -> ResearchPortfolio:
        stored = self._stored_revision(revision)
        ref = ArtifactBlobRef(
            stored.payload_digest,
            stored.payload_size_bytes,
            RESEARCH_PORTFOLIO_MEDIA_TYPE,
        )
        portfolio = decode_research_portfolio(self._blobs.get(ref))
        if portfolio.portfolio_id != revision.portfolio_id:
            raise ValueError("Research OS portfolio identity drifted")
        if portfolio.portfolio_digest != revision.portfolio_digest:
            raise ValueError("Research OS portfolio digest drifted")
        return portfolio

    def commit(
        self,
        portfolio: ResearchPortfolio,
        *,
        parents: tuple[ResearchGraphRevision, ...],
        message: str,
    ) -> ResearchGraphRevision:
        if type(portfolio) is not ResearchPortfolio:
            raise TypeError("Research OS commit requires ResearchPortfolio")
        if type(parents) is not tuple or any(
            type(parent) is not ResearchGraphRevision for parent in parents
        ):
            raise TypeError("Research OS parents must be ResearchGraphRevision tuple")
        if any(parent.portfolio_id != portfolio.portfolio_id for parent in parents):
            raise ValueError("Research OS parents must share portfolio identity")
        raw = encode_research_portfolio(portfolio)
        ref = self._blobs.put(raw, media_type=RESEARCH_PORTFOLIO_MEDIA_TYPE)
        if ref.content_sha256 != portfolio.portfolio_digest:
            raise RuntimeError("Artifact CAS identity drifted from ResearchPortfolio")
        stored = self._revisions.commit(
            PortfolioRevision(
                portfolio.portfolio_id,
                portfolio.portfolio_digest,
                ref.size_bytes,
                tuple(parent.revision_digest for parent in parents),
                message,
            )
        )
        return self._public_revision(stored)

    def diff(
        self,
        left: ResearchGraphRevision,
        right: ResearchGraphRevision,
    ) -> ResearchRevisionDiff:
        if left.portfolio_id != right.portfolio_id:
            raise ValueError("Research OS diff revisions must share portfolio identity")
        return diff_research_portfolios(
            self._load(left),
            self._load(right),
            left_revision_digest=left.revision_digest,
            right_revision_digest=right.revision_digest,
        )

    def branch(
        self,
        name: str,
        revision: ResearchGraphRevision,
        *,
        expected: ResearchGraphRevision | None,
    ) -> ResearchBranch:
        self._stored_revision(revision)
        if expected is not None:
            self._stored_revision(expected)
            if expected.portfolio_id != revision.portfolio_id:
                raise ValueError("Research OS branch revisions must share portfolio identity")
        row = self._revisions.move_branch(
            revision.portfolio_id,
            name,
            revision.revision_digest,
            expected_revision_digest=(
                None if expected is None else expected.revision_digest
            ),
        )
        return ResearchBranch(
            row.subject_id,
            row.name,
            row.revision_digest,
            row.generation,
        )

    def tag(self, name: str, revision: ResearchGraphRevision) -> ResearchTag:
        self._stored_revision(revision)
        row = self._revisions.tag(
            revision.portfolio_id,
            name,
            revision.revision_digest,
        )
        return ResearchTag(row.subject_id, row.name, row.revision_digest)

    def merge(
        self,
        portfolio: ResearchPortfolio,
        left: ResearchGraphRevision,
        right: ResearchGraphRevision,
        *,
        message: str,
    ) -> ResearchGraphRevision:
        if left.portfolio_id != portfolio.portfolio_id or right.portfolio_id != portfolio.portfolio_id:
            raise ValueError("Research OS merge parents must share resolved portfolio identity")
        self._stored_revision(left)
        self._stored_revision(right)
        return self.commit(
            portfolio,
            parents=(left, right),
            message=message,
        )

    def control(self, request: ResearchControlRequest) -> ResearchControlReceipt:
        if self._control is None:
            raise RuntimeError("Research OS runtime control is not bound")
        portfolio = self._load(request.target.revision)
        if portfolio.portfolio_digest != request.target.revision.portfolio_digest:
            raise ValueError("Research OS control portfolio/revision digest drifted")
        if request.action is ResearchControlAction.MIGRATE:
            if not isinstance(self._control, ResearchOSRevisionMigrationPort):
                raise RuntimeError(
                    "Research OS migration requires a revision-aware execution control port"
                )
            source_digest = self._control.active_revision_digest(
                request.target.execution_id
            )
            source_stored = self._revisions.revision(
                request.target.portfolio_id,
                source_digest,
            )
            source_revision = self._public_revision(source_stored)
            source_portfolio = self._load(source_revision)
            receipt = self._control.migrate(
                request,
                source_revision,
                source_portfolio,
                portfolio,
            )
        else:
            receipt = self._control.control(request, portfolio)
        if type(receipt) is not ResearchControlReceipt:
            raise TypeError("Research OS control returned invalid receipt")
        if receipt.action is not request.action or receipt.target != request.target:
            raise ValueError("Research OS control receipt identity drifted")
        return receipt


def bind_portfolio_research_os(
    revisions: PortfolioRevisionStorePort,
    blobs: ArtifactBlobStorePort,
    *,
    control: ResearchOSControlPort | None = None,
) -> ResearchOS:
    return bind_research_os(
        PortfolioBackedResearchOSPort(
            revisions,
            blobs,
            control=control,
        )
    )


__all__ = [
    "PortfolioBackedResearchOSPort",
    "RESEARCH_PORTFOLIO_MEDIA_TYPE",
    "ResearchOSControlPort",
    "ResearchOSRevisionMigrationPort",
    "bind_portfolio_research_os",
    "decode_research_portfolio",
    "diff_research_portfolios",
    "encode_research_portfolio",
]
