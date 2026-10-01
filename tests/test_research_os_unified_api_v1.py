from __future__ import annotations

import noetrium.api as api
import pytest
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
    return call.transition(value=call.input_value, next_node="finish")


def _sem_return(call):
    return call.transition(value=call.previous_value)


def _configure_sem_v1(method):
    method.flow.compute("step", "sem.step", _sem_step, ("finish",))
    method.flow.finish("finish", "sem.return", _sem_return)


def _configure_sem_v2(method):
    method.contract.configure({"version": 2})
    method.flow.compute("step", "sem.step.v2", _sem_step, ("finish",))
    method.flow.finish("finish", "sem.return", _sem_return)


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
                current.generation + (
                    current.revision_digest != revision.revision_digest
                ),
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


def _portfolio(configurer=_configure_sem_v1):
    portfolio = api.ResearchPortfolioBuilder("fixture")
    program = portfolio.programs.create("sem")
    program.methods.define(
        "sem-method",
        configurer,
        entrypoint="step",
    )
    program.data.benchmark(
        "minecraft-memory",
        implementation=_minecraft_memory_benchmark,
    )
    program.data.metric(
        "task-success",
        implementation=_task_success_metric,
    )
    program.experiments.define(
        "main",
        definitions=("sem-method", "minecraft-memory"),
        outputs=(("trajectories", "artifact"),),
    )
    program.experiments.evaluate(
        "evaluate",
        definitions=("task-success",),
        outputs=(("scores", "metric"),),
        after=("main",),
    )
    program.experiments.analyze(
        "analysis",
        after=("evaluate",),
        outputs=(("claim-evidence", "evidence"),),
    )
    return portfolio.freeze()


def test_noetrium_api_exposes_only_four_roots() -> None:
    assert api.__all__ == (
        "ResearchPortfolioBuilder",
        "ResearchPortfolio",
        "ResearchOS",
        "open_project",
    )
    for lower in (
        "ResearchProgramBuilder",
        "ResearchMethodBuilder",
        "ResearchInputBinding",
        "ResearchOutputSpec",
        "ResearchNode",
        "ResearchDefinition",
        "WorkloadTrialProvider",
        "ResearchExecutionTarget",
    ):
        assert not hasattr(api, lower)


def test_four_root_builder_reaches_only_systemized_program_facade() -> None:
    portfolio = api.ResearchPortfolioBuilder("surface")
    assert {
        name for name in dir(portfolio)
        if not name.startswith("_")
    } == {"programs", "handoffs", "freeze"}

    program = portfolio.programs.create("paper")
    assert {
        name for name in dir(program)
        if not name.startswith("_")
    } == {
        "methods",
        "experiments",
        "data",
        "requirements",
        "reports",
        "extensions",
    }
    assert not hasattr(program.extensions, "node")


def test_frozen_portfolio_exposes_only_immutable_program_and_handoff_views() -> None:
    frozen = _portfolio()
    assert frozen.portfolio_id == "fixture"
    assert len(frozen.portfolio_digest) == 64
    view = frozen.programs[0]
    assert view.program_id == "sem"
    assert {
        "minecraft-memory",
        "sem-method",
        "task-success",
    }.issubset(set(view.definition_ids))
    assert view.stage_ids == ("analysis", "evaluate", "main")
    assert len(view.program_digest) == 64
    assert not hasattr(view, "nodes")
    assert not hasattr(view, "definitions")
    assert not hasattr(frozen, "dependencies")
    assert frozen.handoffs == ()


def test_program_digest_changes_when_method_semantics_change() -> None:
    first = _portfolio(_configure_sem_v1).programs[0]
    second_builder = api.ResearchPortfolioBuilder("fixture-v2")
    second = second_builder.programs.create("sem")
    second.methods.define(
        "sem-method",
        _configure_sem_v2,
        entrypoint="step",
    )
    second.experiments.define("main", definitions=("sem-method",))
    second_view = second_builder.freeze().programs[0]
    assert first.program_digest != second_view.program_digest


def test_portfolio_handoff_connects_multiple_papers_without_graph_types() -> None:
    portfolio = api.ResearchPortfolioBuilder("portfolio")
    search = portfolio.programs.create("paper-a")
    search.experiments.select(
        "select",
        outputs=(("best-candidate", "selection"),),
    )
    confirm = portfolio.programs.create("paper-b")
    confirm.experiments.define("confirm")
    portfolio.handoffs.bind(
        upstream=("paper-a", "select"),
        downstream=("paper-b", "confirm"),
        inputs={
            "candidate": ("best-candidate", "selection"),
        },
    )
    frozen = portfolio.freeze()

    assert tuple(program.program_id for program in frozen.programs) == (
        "paper-a",
        "paper-b",
    )
    assert len(frozen.handoffs) == 1
    handoff = frozen.handoffs[0]
    assert handoff.upstream == ("paper-a", "select")
    assert handoff.downstream == ("paper-b", "confirm")
    assert handoff.inputs == (
        ("candidate", "best-candidate", "selection"),
    )


def test_portfolio_rejects_cross_program_handoff_cycle() -> None:
    portfolio = api.ResearchPortfolioBuilder("cyclic")
    first = portfolio.programs.create("paper-a")
    first.experiments.analyze("a")
    second = portfolio.programs.create("paper-b")
    second.experiments.analyze("b")
    portfolio.handoffs.bind(
        upstream=("paper-a", "a"),
        downstream=("paper-b", "b"),
    )
    portfolio.handoffs.bind(
        upstream=("paper-b", "b"),
        downstream=("paper-a", "a"),
    )
    with pytest.raises(ValueError, match="dependency cycle"):
        portfolio.freeze()


def test_internal_research_os_still_unifies_revision_and_live_control() -> None:
    port = _Port()
    research_os = bind_research_os(port)

    builder = api.ResearchPortfolioBuilder("main")
    program = builder.programs.create("sem")
    program.experiments.define("main")
    portfolio = builder.freeze()

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
    assert node_target.node == ResearchNodeRef("sem", "main")
    assert paused.action is ResearchControlAction.PAUSE
    assert resumed.action is ResearchControlAction.RESUME


def test_platform_resolved_requirements_are_systemized_and_runtime_owned() -> None:
    portfolio = api.ResearchPortfolioBuilder("requirements")
    program = portfolio.programs.create("paper")

    program.requirements.model(
        "planner",
        config={"required_model": "Qwen3-8B", "structured_output": True},
    )
    program.requirements.environment(
        "world",
        config={
            "category_id": "minecraft",
            "minecraft_version": "1.21.1",
        },
    )
    program.data.dataset(
        "tasks",
        config={"benchmark": "memory-suite", "split": "test"},
    )
    program.experiments.define(
        "main",
        definitions=("planner", "world", "tasks"),
    )

    frozen = portfolio.freeze()
    assert frozen.programs[0].definition_ids == (
        "planner",
        "tasks",
        "world",
    )

    bad_model = api.ResearchPortfolioBuilder("bad-model")
    model_program = bad_model.programs.create("paper")
    with pytest.raises(ValueError, match="platform-owned"):
        model_program.requirements.model(
            "planner",
            config={
                "required_model": "Qwen3-8B",
                "engine_args": ["--max-num-seqs", "8"],
            },
        )

    bad_environment = api.ResearchPortfolioBuilder("bad-env")
    env_program = bad_environment.programs.create("paper")
    with pytest.raises(ValueError, match="platform-owned"):
        env_program.requirements.environment(
            "world",
            config={
                "category_id": "minecraft",
                "server_port": 25565,
            },
        )


def test_scientific_configuration_remains_downstream_owned() -> None:
    portfolio = api.ResearchPortfolioBuilder("semantic-config")
    program = portfolio.programs.create("paper")
    program.requirements.configuration(
        "protocol",
        config={
            "repetitions": 3,
            "heldout": True,
            "environment_session_scope": "task",
        },
    )
    program.experiments.define(
        "main",
        definitions=("protocol",),
    )
    assert "protocol" in portfolio.freeze().programs[0].definition_ids


def test_experiment_surface_rejects_physical_placement_config() -> None:
    portfolio = api.ResearchPortfolioBuilder("node-boundary")
    program = portfolio.programs.create("paper")
    with pytest.raises(ValueError, match="platform-owned"):
        program.experiments.define(
            "main",
            config={"gpu_id": "0"},
        )
