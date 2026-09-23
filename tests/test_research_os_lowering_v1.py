from __future__ import annotations

import pytest

from noetrium_platform.composition.research_os_lowering import (
    ResearchImplementationResolutionError,
    ResearchOSLoweringTarget,
    compile_callable_machine_definition,
    compile_callable_method_definition,
    compile_research_os_lowering,
)
from noetrium_platform.composition.research_os_graph import (
    compile_research_portfolio_graph,
)
from noetrium_platform.composition.method_runtime import bind_standard_method_runtime
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    InMemoryMachineJournal,
    MachineKind,
    MachineStatus,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodRunStatus,
    MethodRuntimeContext,
)
from noetrium_platform.research.execution.machines import ResearchProgramHost
from noetrium_platform.research.execution.workflow.runtime import UniversalMethodMachine
from noetrium_platform.product import research_os as api


def _method(payload=None):
    return payload


def _metric(payload=None):
    return payload


def _benchmark():
    return {"tasks": 3}


def _revision(portfolio: api.ResearchPortfolio) -> api.ResearchGraphRevision:
    return api.ResearchGraphRevision(
        portfolio.portfolio_id,
        portfolio.portfolio_digest,
        (),
        "lowering test",
    )


def test_lowering_partitions_paper_implementation_from_platform_requirement() -> None:
    builder = api.ResearchProgramBuilder("paper")
    builder.method("method", implementation=_method)
    builder.model("planner", config={"role": "planner"})
    builder.environment("world", config={"family": "minecraft"})
    builder.experiment(
        "main",
        definitions=("method", "planner", "world"),
    )
    portfolio = api.ResearchPortfolio("suite", (builder.freeze(),))
    compilation = compile_research_portfolio_graph(_revision(portfolio), portfolio)

    lowering = compile_research_os_lowering(compilation)
    node = lowering.node("paper::main")

    assert node.target is ResearchOSLoweringTarget.EXPERIMENTATION
    assert tuple(row.definition_id for row in node.implementations) == ("method",)
    assert node.implementations[0].implementation is _method
    assert tuple(row.definition_id for row in node.method_programs) == ("method",)
    assert node.method_programs[0].program.program_identity.implementation.method_id == (
        "method"
    )
    assert tuple(row.definition_id for row in node.platform_requirements) == (
        "planner",
        "world",
    )
    assert len(node.lowering_digest) == 64
    assert len(lowering.lowering_digest) == 64


def test_lowering_covers_executable_machine_routes_and_platform_only_workbench() -> None:
    builder = api.ResearchProgramBuilder("paper")
    builder.method("method", implementation=_method)
    builder.metric("metric", implementation=_metric)
    builder.node(
        "method-node",
        kind=api.ResearchNodeKind.METHOD,
        definitions=("method",),
    )
    builder.evaluation(
        "evaluation",
        definitions=("metric",),
        depends_on=("method-node",),
    )
    builder.node(
        "optimization",
        kind=api.ResearchNodeKind.OPTIMIZATION,
        definitions=("metric",),
        depends_on=("evaluation",),
    )
    builder.analysis("analysis", depends_on=("optimization",))
    builder.selection("selection", depends_on=("analysis",))
    builder.figure("figure", depends_on=("selection",))
    builder.table("table", depends_on=("figure",))
    portfolio = api.ResearchPortfolio("suite", (builder.freeze(),))

    lowering = compile_research_os_lowering(
        compile_research_portfolio_graph(_revision(portfolio), portfolio)
    )

    assert lowering.node("paper::method-node").target is (
        ResearchOSLoweringTarget.METHOD_MACHINE
    )
    assert tuple(
        row.definition_id
        for row in lowering.node("paper::method-node").method_programs
    ) == ("method",)
    assert lowering.node("paper::evaluation").target is (
        ResearchOSLoweringTarget.EVALUATION_MACHINE
    )
    assert lowering.node("paper::evaluation").machine_programs[0].machine_kind is (
        MachineKind.EVALUATION
    )
    assert lowering.node("paper::optimization").target is (
        ResearchOSLoweringTarget.OPTIMIZATION_MACHINE
    )
    assert lowering.node("paper::optimization").machine_programs[0].machine_kind is (
        MachineKind.OPTIMIZATION
    )
    for node_id in ("analysis", "selection", "figure", "table"):
        node = lowering.node(f"paper::{node_id}")
        assert node.target is ResearchOSLoweringTarget.WORKBENCH
        assert node.implementations == ()
        assert node.machine_programs == ()


def test_paper_callable_without_canonical_machine_target_fails_closed() -> None:
    builder = api.ResearchProgramBuilder("paper")
    builder.metric("metric", implementation=_metric)
    builder.analysis("analysis", definitions=("metric",))
    portfolio = api.ResearchPortfolio("suite", (builder.freeze(),))

    with pytest.raises(
        ResearchImplementationResolutionError,
        match="no canonical Machine lowering target",
    ):
        compile_research_os_lowering(
            compile_research_portfolio_graph(_revision(portfolio), portfolio)
        )


def test_import_resolution_fails_closed_when_frozen_source_identity_drifted() -> None:
    declared = api.ResearchImplementation(
        implementation_id="method",
        module=__name__,
        qualname="_method",
        source_digest="0" * 64,
    )
    definition = api.ResearchDefinition(
        "method",
        api.ResearchDefinitionKind.METHOD,
        declared,
    )
    node = api.ResearchNode(
        "method-node",
        api.ResearchNodeKind.METHOD,
        ("method",),
    )
    program = api.ResearchProgram("paper", (definition,), (node,), ())
    portfolio = api.ResearchPortfolio("suite", (program,))
    compilation = compile_research_portfolio_graph(_revision(portfolio), portfolio)

    with pytest.raises(
        ResearchImplementationResolutionError,
        match="source drifted",
    ):
        compile_research_os_lowering(compilation)


def test_plain_method_callable_compiles_to_machine_backed_umm_program(tmp_path) -> None:
    builder = api.ResearchProgramBuilder("paper")
    builder.method("method", implementation=_method, config={"mode": "test"})
    definition = builder.freeze().definitions[0]

    program = compile_callable_method_definition(definition)
    assert program.program_identity.implementation.method_id == "method"
    assert program.program_identity.implementation.artifact_digest == (
        definition.implementation_digest
    )
    assert program.graph.entrypoint == "invoke"
    assert program.configuration["research_definition_id"] == "method"

    runtime = bind_standard_method_runtime(
        program,
        MethodRuntimeContext(
            ExecutionContext("research-os-run", "trace", "method-node")
        ),
        state_root=tmp_path / "method-state",
        machine_id="research-os:paper:method",
    )
    result = UniversalMethodMachine(max_steps=4).run(
        program,
        runtime=runtime,
        input_value={"candidate": 7},
    )

    assert result.status is MethodRunStatus.SUCCEEDED
    assert result.value == {"candidate": 7}
    assert result.program_digest == program.program_digest
    assert (tmp_path / "method-state" / "journal").is_dir()



def test_plain_metric_callable_compiles_to_research_program_host() -> None:
    builder = api.ResearchProgramBuilder("paper")
    builder.metric("metric", implementation=_metric, config={"name": "score"})
    definition = builder.freeze().definitions[0]

    lowered = compile_callable_machine_definition(
        definition,
        machine_kind=MachineKind.EVALUATION,
    )
    assert lowered.program.kind is MachineKind.EVALUATION
    assert lowered.operation.implementation_digest == definition.implementation_digest

    host = ResearchProgramHost(
        host_id="research-os.evaluation.metric",
        program=lowered.program,
        operations=(lowered.operation,),
        journal=InMemoryMachineJournal(),
    )
    execution = host.execute(
        machine_id="evaluation:metric:1",
        instance_identity={"definition": definition.definition_digest},
        binding=None,
        initial_data={},
        payload={"score": 0.9},
    )

    assert execution.status is MachineStatus.COMPLETED
    assert execution.previous_value == {"score": 0.9}
    assert execution.cut is not None


def test_zero_argument_benchmark_callable_compiles_without_typeerror_guessing() -> None:
    builder = api.ResearchProgramBuilder("paper")
    builder.benchmark("benchmark", implementation=_benchmark)
    builder.experiment("main", definitions=("benchmark",))
    portfolio = api.ResearchPortfolio("suite", (builder.freeze(),))
    lowering = compile_research_os_lowering(
        compile_research_portfolio_graph(_revision(portfolio), portfolio)
    )
    lowered = lowering.node("paper::main").machine_programs[0]
    assert lowered.machine_kind is MachineKind.EXPERIMENT

    host = ResearchProgramHost(
        host_id="research-os.experiment.benchmark",
        program=lowered.program,
        operations=(lowered.operation,),
        journal=InMemoryMachineJournal(),
    )
    execution = host.execute(
        machine_id="experiment:benchmark:1",
        instance_identity={"definition": "benchmark"},
        binding=None,
        initial_data={},
        payload={"ignored": True},
    )
    assert execution.status is MachineStatus.COMPLETED
    assert execution.previous_value == {"tasks": 3}


def test_plain_callable_with_unsupported_arity_fails_at_lowering_not_runtime() -> None:
    def invalid(left, right):
        return left, right

    # Local functions cannot be frozen through the public builder, so use the
    # signature helper through a module-level-shaped resolver contract.
    with pytest.raises(
        ResearchImplementationResolutionError,
        match="zero or one positional payload",
    ):
        from noetrium_platform.composition.research_os_lowering import (
            _plain_callable_accepts_payload,
        )
        _plain_callable_accepts_payload(invalid)



class _FalseyResolver:
    def __bool__(self) -> bool:
        return False


def test_falsey_invalid_resolver_is_not_silently_replaced() -> None:
    builder = api.ResearchProgramBuilder("paper")
    builder.method("method", implementation=_method)
    builder.node(
        "method-node",
        kind=api.ResearchNodeKind.METHOD,
        definitions=("method",),
    )
    portfolio = api.ResearchPortfolio("suite", (builder.freeze(),))
    compilation = compile_research_portfolio_graph(_revision(portfolio), portfolio)

    with pytest.raises(TypeError, match="must satisfy ResearchImplementationResolverPort"):
        compile_research_os_lowering(
            compilation,
            resolver=_FalseyResolver(),
        )
