from __future__ import annotations

import noetrium.api as api
from noetrium_platform.product.research_os import (
    ResearchBranch,
    ResearchControlAction,
    ResearchControlReceipt,
    ResearchExecutionTarget,
    ResearchGraphRevision,
    ResearchNodeRef,
    ResearchRevisionDiff,
    ResearchTag,
    bind_research_os,
)


def _sem_step(call):
    return call.transition(value=call.input_value, next_node="return")


def _sem_return(call):
    return call.transition(value=call.previous_value)


def _configure_sem_v1(method):
    method.compute("step", "sem.step", _sem_step, ("return",))
    method.return_node("return", "sem.return", _sem_return)


def _configure_sem_v2(method):
    method.configure({"version": 2})
    method.compute("step", "sem.step.v2", _sem_step, ("return",))
    method.return_node("return", "sem.return", _sem_return)


def _minecraft_memory_benchmark():
    return ("task-1",)


def _task_success_metric(value):
    return 1.0 if value else 0.0


class _Port:
    def __init__(self) -> None:
        self.controls = []
        self.branches = {}

    def commit(self, portfolio, *, parents, message):
        return ResearchGraphRevision(
            portfolio.portfolio_id,
            portfolio.portfolio_digest,
            tuple(parent.revision_digest for parent in parents),
            message,
        )

    def diff(self, left, right):
        return ResearchRevisionDiff(
            left.portfolio_id,
            left.revision_digest,
            right.revision_digest,
            (),
        )

    def branch(self, name, revision, *, expected):
        key = (revision.portfolio_id, name)
        current = self.branches.get(key)
        if current is None:
            if expected is not None:
                raise ValueError("branch does not exist")
            result = ResearchBranch(
                revision.portfolio_id,
                name,
                revision.revision_digest,
                1,
            )
        else:
            if expected is None or current.revision_digest != expected.revision_digest:
                raise ValueError("branch expected revision mismatch")
            result = ResearchBranch(
                revision.portfolio_id,
                name,
                revision.revision_digest,
                current.generation + (current.revision_digest != revision.revision_digest),
            )
        self.branches[key] = result
        return result

    def tag(self, name, revision):
        return ResearchTag(
            revision.portfolio_id,
            name,
            revision.revision_digest,
        )

    def merge(self, portfolio, left, right, *, message):
        return ResearchGraphRevision(
            portfolio.portfolio_id,
            portfolio.portfolio_digest,
            (left.revision_digest, right.revision_digest),
            message,
        )

    def control(self, request):
        self.controls.append(request)
        return ResearchControlReceipt(
            request.action,
            request.target,
            "accepted",
            "b" * 64,
            request.payload,
        )


def _program():
    portfolio = api.ResearchPortfolioBuilder("fixture")
    builder = portfolio.program("sem")
    builder.method(
        "sem-method",
        _configure_sem_v1,
        entrypoint="step",
    )
    builder.benchmark(
        "minecraft-memory",
        implementation=_minecraft_memory_benchmark,
    )
    builder.metric("task-success", implementation=_task_success_metric)
    builder.experiment(
        "main",
        definitions=("sem-method", "minecraft-memory"),
        outputs=(("trajectories", "artifact"),),
    )
    builder.evaluation(
        "evaluate",
        definitions=("task-success",),
        outputs=(("scores", "metric"),),
    )
    builder.depends(
        "evaluate",
        "main",
        bindings=(("trajectories", "trajectories", "artifact"),),
    )
    builder.analysis(
        "analysis",
        depends_on=("evaluate",),
        outputs=(("claim-evidence", "evidence"),),
    )
    return portfolio.freeze().programs[0]


def test_noetrium_api_exposes_only_highest_level_research_roots() -> None:
    assert api.__all__ == (
        "ResearchPortfolioBuilder",
        "ResearchPortfolio",
        "ResearchOS",
        "open_project",
    )
    for retired in (
        "research_os",
        "research_authoring",
        "execution_authoring",
        "research_requirements",
        "ResearchProgramBuilder",
        "MethodProgramBuilder",
        "WorkloadTrialProvider",
        "ResearchExecutionTarget",
        "ResearchInputBinding",
        "ResearchNode",
    ):
        assert not hasattr(api, retired)


def test_method_identity_is_frozen_behind_root_dsl() -> None:
    program = _program()
    definition = next(
        row for row in program.definitions
        if row.definition_id == "sem-method"
    )
    implementation = definition.implementation
    assert implementation.module == __name__
    assert implementation.qualname == "_configure_sem_v1"
    assert len(implementation.source_digest) == 64
    assert len(implementation.implementation_digest) == 64


def test_root_builder_freezes_whole_paper_semantics() -> None:
    program = _program()
    assert program.program_id == "sem"
    assert tuple(node.node_id for node in program.nodes) == (
        "analysis",
        "evaluate",
        "main",
    )
    assert len(program.dependencies) == 2
    by_edge = {
        (edge.upstream_node_id, edge.downstream_node_id): edge
        for edge in program.dependencies
    }
    bound = by_edge[("main", "evaluate")]
    assert bound.bindings[0].input_name == "trajectories"
    assert bound.bindings[0].output_name == "trajectories"
    assert by_edge[("evaluate", "analysis")].bindings == ()


def test_program_digest_changes_when_method_semantics_change() -> None:
    first = _program()
    portfolio = api.ResearchPortfolioBuilder("fixture-v2")
    builder = portfolio.program("sem")
    builder.method(
        "sem-method",
        _configure_sem_v2,
        entrypoint="step",
    )
    builder.experiment("main", definitions=("sem-method",))
    second = portfolio.freeze().programs[0]
    assert first.program_digest != second.program_digest


def test_portfolio_builder_connects_multiple_papers_as_one_graph() -> None:
    portfolio = api.ResearchPortfolioBuilder("portfolio")
    search = portfolio.program("paper-a")
    search.selection(
        "select",
        outputs=(("best-candidate", "selection"),),
    )
    confirm = portfolio.program("paper-b")
    confirm.experiment("confirm", definitions=())
    portfolio.depends(
        upstream_program_id="paper-a",
        upstream_node_id="select",
        downstream_program_id="paper-b",
        downstream_node_id="confirm",
        bindings=(("candidate", "best-candidate", "selection"),),
    )
    frozen = portfolio.freeze()

    assert tuple(program.program_id for program in frozen.programs) == (
        "paper-a",
        "paper-b",
    )
    assert len(frozen.dependencies) == 1
    dependency = frozen.dependencies[0]
    assert dependency.upstream.program_id == "paper-a"
    assert dependency.upstream.node_id == "select"
    assert dependency.downstream.program_id == "paper-b"
    assert dependency.downstream.node_id == "confirm"
    assert dependency.bindings[0].input_name == "candidate"


def test_portfolio_rejects_cross_program_dependency_cycle() -> None:
    portfolio = api.ResearchPortfolioBuilder("cyclic")
    first = portfolio.program("paper-a")
    first.analysis("a")
    second = portfolio.program("paper-b")
    second.analysis("b")
    portfolio.depends(
        upstream_program_id="paper-a",
        upstream_node_id="a",
        downstream_program_id="paper-b",
        downstream_node_id="b",
    )
    portfolio.depends(
        upstream_program_id="paper-b",
        upstream_node_id="b",
        downstream_program_id="paper-a",
        downstream_node_id="a",
    )
    try:
        portfolio.freeze()
    except ValueError as exc:
        assert "dependency cycle" in str(exc)
    else:
        raise AssertionError("cross-program dependency cycle was accepted")


def test_internal_research_os_unifies_revision_and_live_control() -> None:
    port = _Port()
    research_os = bind_research_os(port)

    portfolio_builder = api.ResearchPortfolioBuilder("main")
    program = portfolio_builder.program("sem")
    program.experiment("main", definitions=())
    portfolio = portfolio_builder.freeze()

    revision = research_os.commit(portfolio, message="initial graph")
    branch = research_os.branch("sem-main", revision)
    tag = research_os.tag("sem-confirmatory-v1", revision)
    next_revision = research_os.commit(
        portfolio,
        parents=(revision,),
        message="second cut",
    )
    advanced = research_os.branch(
        "sem-main",
        next_revision,
        expected=revision,
    )
    diff = research_os.diff(revision, next_revision)
    merge = research_os.merge(
        portfolio,
        revision,
        next_revision,
        message="resolved merge",
    )

    target = ResearchExecutionTarget("sem.confirmatory", next_revision)
    node_target = target.for_node("sem", "main")
    paused = research_os.pause(node_target)
    resumed = research_os.resume(target)

    assert revision.portfolio_id == "main"
    assert branch.revision_digest == revision.revision_digest
    assert branch.generation == 1
    assert advanced.revision_digest == next_revision.revision_digest
    assert advanced.generation == 2
    assert tag.revision_digest == revision.revision_digest
    assert diff.portfolio_id == "main"
    assert merge.parent_revision_digests == (
        revision.revision_digest,
        next_revision.revision_digest,
    )
    assert target.portfolio_id == "main"
    assert node_target.node == ResearchNodeRef("sem", "main")
    assert node_target.target_digest != target.target_digest
    assert paused.target == node_target
    assert resumed.target == target
    assert paused.action is ResearchControlAction.PAUSE
    assert resumed.action is ResearchControlAction.RESUME
    assert tuple(row.action for row in port.controls) == (
        ResearchControlAction.PAUSE,
        ResearchControlAction.RESUME,
    )


def test_root_builder_supports_platform_resolved_requirements() -> None:
    portfolio = api.ResearchPortfolioBuilder("requirements")
    builder = portfolio.program("declarative")
    builder.model(
        "planner-model",
        config={"role": "planner", "minimum_context": 8192},
    )
    builder.environment(
        "minecraft",
        config={"family": "minecraft", "capabilities": ["act", "observe"]},
    )
    builder.dataset(
        "tasks",
        config={"benchmark": "memory-suite", "split": "test"},
    )
    builder.protocol(
        "confirmatory",
        config={"repetitions": 3, "freeze": True},
    )
    builder.resource_policy(
        "resources",
        config={"accelerator": "gpu", "placement": "adaptive"},
    )
    builder.study(
        "main",
        definitions=(
            "planner-model",
            "minecraft",
            "tasks",
            "confirmatory",
            "resources",
        ),
    )
    program = portfolio.freeze().programs[0]

    by_id = {row.definition_id: row for row in program.definitions}
    assert all(
        by_id[name].platform_resolved
        for name in (
            "planner-model",
            "minecraft",
            "tasks",
            "confirmatory",
            "resources",
        )
    )
    assert all(by_id[name].implementation_digest is None for name in by_id)
    assert program.nodes[0].kind.value == "study"
