from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from noetrium_platform.composition.research_os_graph import (
    compile_research_portfolio_graph,
)
from noetrium_platform.composition.research_os_values import (
    ResearchOSValueAuthorityMissing,
    ResearchOSValueReference,
    ResearchOSValueRouter,
    ResearchOSValueSubject,
    publish_research_os_node_outputs,
    resolve_research_os_node_inputs,
    validate_research_os_value_authorities,
)
from noetrium_platform.foundation.kernel.kernel import (
    JsonValue,
    canonical_digest,
    freeze_json,
)
from noetrium_platform.product import research_os as api


@dataclass
class _Authority:
    authority_id: str = "test.authority"
    supported_kinds: frozenset[api.ResearchValueKind] = frozenset(
        api.ResearchValueKind
    )
    _values: dict[str, JsonValue] = field(default_factory=dict)

    def publish(
        self,
        subject: ResearchOSValueSubject,
        value: JsonValue,
    ) -> ResearchOSValueReference:
        frozen = freeze_json(value)
        self._values[subject.subject_digest] = frozen
        return ResearchOSValueReference(
            subject,
            self.authority_id,
            subject.subject_digest,
            canonical_digest(frozen),
        )

    def lookup(
        self,
        subject: ResearchOSValueSubject,
    ) -> ResearchOSValueReference:
        value = self._values[subject.subject_digest]
        return ResearchOSValueReference(
            subject,
            self.authority_id,
            subject.subject_digest,
            canonical_digest(value),
        )

    def resolve(
        self,
        reference: ResearchOSValueReference,
    ) -> JsonValue:
        return self._values[reference.authority_ref]

    def reuse_proof(
        self,
        reference: ResearchOSValueReference,
    ) -> str:
        return canonical_digest(
            {
                "authority_id": self.authority_id,
                "reference_digest": reference.reference_digest,
            }
        )


def _compiled():
    builder = api.ResearchProgramBuilder("paper")
    builder.node(
        "search",
        kind=api.ResearchNodeKind.CUSTOM,
        outputs=(
            api.ResearchOutputSpec(
                "best",
                api.ResearchValueKind.SELECTION,
            ),
        ),
    )
    builder.node(
        "confirm",
        kind=api.ResearchNodeKind.CUSTOM,
        outputs=(
            api.ResearchOutputSpec(
                "score",
                api.ResearchValueKind.METRIC,
            ),
        ),
    )
    builder.depends(
        "confirm",
        "search",
        bindings=(
            api.ResearchInputBinding(
                "candidate",
                "best",
                api.ResearchValueKind.SELECTION,
            ),
        ),
    )
    portfolio = api.ResearchPortfolio("suite", (builder.freeze(),))
    revision = api.ResearchGraphRevision(
        portfolio.portfolio_id,
        portfolio.portfolio_digest,
        (),
        "values",
    )
    return compile_research_portfolio_graph(revision, portfolio)


def test_typed_edge_resolves_value_through_explicit_lower_authority() -> None:
    compilation = _compiled()
    router = ResearchOSValueRouter((_Authority(),))
    validate_research_os_value_authorities(compilation, router)
    execution_cut_id = canonical_digest({"cut": "r1"})
    search = compilation.node("paper::search")
    confirm = compilation.node("paper::confirm")

    refs = publish_research_os_node_outputs(
        execution_cut_id,
        search,
        router,
        {"candidate_id": "c-1"},
    )
    assert refs[0].subject.kind is api.ResearchValueKind.SELECTION
    assert len(router.reuse_proof(refs[0])) == 64

    inputs = resolve_research_os_node_inputs(
        execution_cut_id,
        compilation,
        confirm,
        router,
    )
    assert inputs == {"candidate": {"candidate_id": "c-1"}}


def test_missing_value_authority_fails_closed_before_execution() -> None:
    compilation = _compiled()
    metric_only = _Authority(
        authority_id="metric.only",
        supported_kinds=frozenset({api.ResearchValueKind.METRIC}),
    )
    router = ResearchOSValueRouter((metric_only,))

    with pytest.raises(
        ResearchOSValueAuthorityMissing,
        match="missing=.*selection",
    ):
        validate_research_os_value_authorities(compilation, router)


def test_node_cannot_emit_undeclared_runtime_value() -> None:
    builder = api.ResearchProgramBuilder("paper")
    builder.node("node", kind=api.ResearchNodeKind.CUSTOM)
    portfolio = api.ResearchPortfolio("suite", (builder.freeze(),))
    revision = api.ResearchGraphRevision(
        portfolio.portfolio_id,
        portfolio.portfolio_digest,
        (),
        "no outputs",
    )
    node = compile_research_portfolio_graph(
        revision,
        portfolio,
    ).node("paper::node")

    with pytest.raises(ValueError, match="without declaring outputs"):
        publish_research_os_node_outputs(
            canonical_digest({"cut": "none"}),
            node,
            ResearchOSValueRouter((_Authority(),)),
            {"unexpected": True},
        )


def test_multi_output_requires_exact_declared_names() -> None:
    builder = api.ResearchProgramBuilder("paper")
    builder.node(
        "node",
        kind=api.ResearchNodeKind.CUSTOM,
        outputs=(
            api.ResearchOutputSpec("a", api.ResearchValueKind.DATA),
            api.ResearchOutputSpec("b", api.ResearchValueKind.METRIC),
        ),
    )
    portfolio = api.ResearchPortfolio("suite", (builder.freeze(),))
    revision = api.ResearchGraphRevision(
        portfolio.portfolio_id,
        portfolio.portfolio_digest,
        (),
        "multi",
    )
    node = compile_research_portfolio_graph(
        revision,
        portfolio,
    ).node("paper::node")
    router = ResearchOSValueRouter((_Authority(),))

    with pytest.raises(ValueError, match="keys do not match"):
        publish_research_os_node_outputs(
            canonical_digest({"cut": "multi"}),
            node,
            router,
            {"a": 1, "wrong": 2},
        )


def test_compiler_rejects_same_input_bound_from_multiple_edges() -> None:
    builder = api.ResearchProgramBuilder("paper")
    for node_id in ("left", "right"):
        builder.node(
            node_id,
            kind=api.ResearchNodeKind.CUSTOM,
            outputs=(
                api.ResearchOutputSpec(
                    "candidate",
                    api.ResearchValueKind.SELECTION,
                ),
            ),
        )
    builder.node("join", kind=api.ResearchNodeKind.CUSTOM)
    for upstream in ("left", "right"):
        builder.depends(
            "join",
            upstream,
            bindings=(
                api.ResearchInputBinding(
                    "candidate",
                    "candidate",
                    api.ResearchValueKind.SELECTION,
                ),
            ),
        )
    portfolio = api.ResearchPortfolio("suite", (builder.freeze(),))
    revision = api.ResearchGraphRevision(
        portfolio.portfolio_id,
        portfolio.portfolio_digest,
        (),
        "ambiguous input",
    )

    with pytest.raises(ValueError, match="globally unique"):
        compile_research_portfolio_graph(revision, portfolio)
