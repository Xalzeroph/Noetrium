from __future__ import annotations

import pytest

from noetrium_platform.composition.research_os_experiment import (
    ResearchOSExperimentClosureMissing,
)
from noetrium_platform.composition.research_os_lowering import (
    ResearchImplementationResolutionError,
    ResearchOSLoweringTarget,
    compile_callable_machine_definition,
    compile_research_os_lowering,
)
from noetrium_platform.composition.research_os_graph import (
    compile_research_portfolio_graph,
)
from noetrium_platform.composition.method_runtime import bind_standard_method_runtime
from noetrium_platform.foundation.kernel.kernel import (
    OperationExecutor,
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
from noetrium_platform.research.execution.workflow.runtime import (
    KernelOperationDispatcher,
    execute_bound_method_program,
)
from noetrium_platform.product import research_os as api


def _method(payload=None):
    return payload


def _method_return(call):
    return {"value": call.input_value}


def _configure_method(method):
    method.configure({"research_definition_id": "method"})
    method.return_node("invoke", "test.method.invoke", _method_return)
    return method


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
    builder.method("method", _configure_method, entrypoint="invoke")
    builder.model("planner", config={"role": "planner"})
    builder.environment("world", config={"family": "minecraft"})
    builder.node(
        "main",
        kind=api.ResearchNodeKind.METHOD,
        definitions=("method", "planner", "world"),
    )
    portfolio = api.ResearchPortfolio("suite", (builder.freeze(),))
    compilation = compile_research_portfolio_graph(_revision(portfolio), portfolio)

    lowering = compile_research_os_lowering(compilation)
    node = lowering.node("paper::main")

    assert node.target is ResearchOSLoweringTarget.METHOD_MACHINE
    assert tuple(row.definition_id for row in node.implementations) == ("method",)
    assert node.implementations[0].method.program.program_digest == node.method_programs[0].program.program_digest
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
    builder.method("method", _configure_method, entrypoint="invoke")
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
        assert node.target is ResearchOSLoweringTarget.ANALYSIS_MACHINE
        assert node.implementations == ()
        assert node.machine_programs == ()


def test_analysis_callable_lowers_to_generic_analysis_machine() -> None:
    builder = api.ResearchProgramBuilder("paper")
    builder.metric("metric", implementation=_metric)
    builder.analysis("analysis", definitions=("metric",))
    portfolio = api.ResearchPortfolio("suite", (builder.freeze(),))

    lowering = compile_research_os_lowering(
        compile_research_portfolio_graph(_revision(portfolio), portfolio)
    )
    node = lowering.node("paper::analysis")
    assert node.target is ResearchOSLoweringTarget.ANALYSIS_MACHINE
    assert node.machine_programs[0].machine_kind is MachineKind.ANALYSIS


def test_import_resolution_fails_closed_when_frozen_source_identity_drifted() -> None:
    declared = api.ResearchImplementation(
        implementation_id="method",
        module=__name__,
        qualname="_method",
        source_digest="0" * 64,
    )
    definition = api.ResearchDefinition(
        "metric",
        api.ResearchDefinitionKind.METRIC,
        declared,
    )
    node = api.ResearchNode(
        "analysis-node",
        api.ResearchNodeKind.ANALYSIS,
        ("metric",),
    )
    program = api.ResearchProgram("paper", (definition,), (node,), ())
    portfolio = api.ResearchPortfolio("suite", (program,))
    compilation = compile_research_portfolio_graph(_revision(portfolio), portfolio)

    with pytest.raises(
        ResearchImplementationResolutionError,
        match="source drifted",
    ):
        compile_research_os_lowering(compilation)


def test_research_method_configurer_lowers_to_machine_backed_method_program(tmp_path) -> None:
    builder = api.ResearchProgramBuilder("paper")
    builder.method(
        "method",
        _configure_method,
        entrypoint="invoke",
        config={"mode": "test"},
    )
    builder.node(
        "method-node",
        kind=api.ResearchNodeKind.METHOD,
        definitions=("method",),
    )
    portfolio = api.ResearchPortfolio("suite", (builder.freeze(),))
    definition = portfolio.programs[0].definitions[0]

    lowering = compile_research_os_lowering(
        compile_research_portfolio_graph(_revision(portfolio), portfolio)
    )
    lowered = lowering.node("paper::method-node").method_programs[0]
    program = lowered.program

    assert program.program_identity.implementation.method_id == "method"
    assert lowered.definition_id == definition.definition_id
    assert lowering.node("paper::method-node").implementations[0].declared.method_digest == (
        definition.implementation.method_digest
    )
    assert program.graph.entrypoint == "invoke"
    assert program.configuration["research_definition_id"] == "method"

    runtime = bind_standard_method_runtime(
        program,
        MethodRuntimeContext(
            ExecutionContext("research-os-run", "trace", "method-node"),
            dispatcher=KernelOperationDispatcher(OperationExecutor()),
        ),
        state_root=tmp_path / "method-state",
        machine_id="research-os:paper:method",
    )
    result = execute_bound_method_program(
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
    builder.evaluation("evaluation", definitions=("metric",))
    definition = builder.freeze().definitions[0]

    lowered = compile_callable_machine_definition(
        definition,
        machine_kind=MachineKind.EVALUATION,
    )
    assert lowered.program.kind is MachineKind.EVALUATION
    assert lowered.operations[0].implementation_digest == definition.implementation_digest

    host = ResearchProgramHost(
        host_id="research-os.evaluation.metric",
        program=lowered.program,
        operations=lowered.operations,
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


def test_experiment_callable_is_not_misrepresented_as_one_node_experiment_machine() -> None:
    builder = api.ResearchProgramBuilder("paper")
    builder.benchmark("benchmark", implementation=_benchmark)
    builder.experiment("main", definitions=("benchmark",))
    portfolio = api.ResearchPortfolio("suite", (builder.freeze(),))

    with pytest.raises(
        ResearchOSExperimentClosureMissing,
        match="explicit canonical experiment closure provider",
    ):
        compile_research_os_lowering(
            compile_research_portfolio_graph(_revision(portfolio), portfolio)
        )


def test_zero_argument_callable_signature_is_compiled_without_typeerror_guessing() -> None:
    builder = api.ResearchProgramBuilder("paper")
    builder.metric("metric", implementation=_benchmark)
    builder.evaluation("evaluation", definitions=("metric",))
    definition = builder.freeze().definitions[0]
    lowered = compile_callable_machine_definition(
        definition,
        machine_kind=MachineKind.EVALUATION,
    )
    host = ResearchProgramHost(
        host_id="research-os.evaluation.zero-arg",
        program=lowered.program,
        operations=lowered.operations,
        journal=InMemoryMachineJournal(),
    )
    execution = host.execute(
        machine_id="evaluation:zero-arg:1",
        instance_identity={"definition": "metric"},
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
    builder.method("method", _configure_method, entrypoint="invoke")
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


def test_analysis_publication_and_custom_nodes_lower_to_universal_machine() -> None:
    builder = api.ResearchProgramBuilder("paper")
    builder.metric("analysis-impl", implementation=_metric)
    builder.metric("publication-impl", implementation=_metric)
    builder.metric("custom-impl", implementation=_metric)
    builder.analysis("analysis", definitions=("analysis-impl",))
    builder.publication("publication", definitions=("publication-impl",))
    builder.node(
        "custom",
        kind=api.ResearchNodeKind.CUSTOM,
        definitions=("custom-impl",),
    )
    portfolio = api.ResearchPortfolio("suite", (builder.freeze(),))
    plan = compile_research_os_lowering(
        compile_research_portfolio_graph(_revision(portfolio), portfolio)
    )
    by_id = {node.source.node.node_id: node for node in plan.nodes}
    assert by_id["analysis"].target is ResearchOSLoweringTarget.ANALYSIS_MACHINE
    assert by_id["analysis"].machine_programs[0].program.kind is MachineKind.ANALYSIS
    assert by_id["publication"].target is ResearchOSLoweringTarget.PUBLICATION_MACHINE
    assert by_id["publication"].machine_programs[0].program.kind is MachineKind.PUBLICATION
    assert by_id["custom"].target is ResearchOSLoweringTarget.CUSTOM_MACHINE
    assert by_id["custom"].machine_programs[0].program.kind is MachineKind.RUNTIME
