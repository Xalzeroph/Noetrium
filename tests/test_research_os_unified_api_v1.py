from __future__ import annotations

import noetrium.api as api
from noetrium_platform.product.research_os import bind_research_os


def _sem_method_v1(payload=None):
    return payload


def _sem_method_v2(payload=None):
    return {"version": 2, "payload": payload}


def _minecraft_memory_benchmark():
    return ("task-1",)


def _task_success_metric(value):
    return 1.0 if value else 0.0


class _Port:
    def __init__(self) -> None:
        self.controls = []
        self.branches = {}

    def commit(self, portfolio, *, parents, message):
        return api.ResearchGraphRevision(
            portfolio.portfolio_id,
            portfolio.portfolio_digest,
            tuple(parent.revision_digest for parent in parents),
            message,
        )

    def diff(self, left, right):
        return api.ResearchRevisionDiff(
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
            result = api.ResearchBranch(
                revision.portfolio_id,
                name,
                revision.revision_digest,
                1,
            )
        else:
            if expected is None or current.revision_digest != expected.revision_digest:
                raise ValueError("branch expected revision mismatch")
            result = api.ResearchBranch(
                revision.portfolio_id,
                name,
                revision.revision_digest,
                current.generation + (current.revision_digest != revision.revision_digest),
            )
        self.branches[key] = result
        return result

    def tag(self, name, revision):
        return api.ResearchTag(
            revision.portfolio_id,
            name,
            revision.revision_digest,
        )

    def merge(self, portfolio, left, right, *, message):
        return api.ResearchGraphRevision(
            portfolio.portfolio_id,
            portfolio.portfolio_digest,
            (left.revision_digest, right.revision_digest),
            message,
        )

    def control(self, request):
        self.controls.append(request)
        return api.ResearchControlReceipt(
            request.action,
            request.target,
            "accepted",
            "b" * 64,
            request.payload,
        )


def _program() -> api.ResearchProgram:
    builder = api.ResearchProgramBuilder("sem")
    builder.method("sem-method", implementation=_sem_method_v1)
    builder.benchmark(
        "minecraft-memory",
        implementation=_minecraft_memory_benchmark,
    )
    builder.metric("task-success", implementation=_task_success_metric)
    builder.experiment(
        "main",
        definitions=("sem-method", "minecraft-memory"),
        outputs=(
            api.ResearchOutputSpec(
                "trajectories",
                api.ResearchValueKind.ARTIFACT,
            ),
        ),
    )
    builder.evaluation(
        "evaluate",
        definitions=("task-success",),
        outputs=(
            api.ResearchOutputSpec(
                "scores",
                api.ResearchValueKind.METRIC,
            ),
        ),
    )
    builder.depends(
        "evaluate",
        "main",
        bindings=(
            api.ResearchInputBinding(
                "trajectories",
                "trajectories",
                api.ResearchValueKind.ARTIFACT,
            ),
        ),
    )
    builder.analysis(
        "analysis",
        depends_on=("evaluate",),
        outputs=(
            api.ResearchOutputSpec(
                "claim-evidence",
                api.ResearchValueKind.EVIDENCE,
            ),
        ),
    )
    return builder.freeze()


def test_noetrium_api_exposes_only_research_os_product_surface() -> None:
    expected = {
        "ResearchOS",
        "ResearchPortfolio",
        "ResearchProgram",
        "ResearchProgramBuilder",
        "ResearchGraphRevision",
        "ResearchDependency",
        "ResearchNode",
        "ResearchDefinition",
        "ResearchImplementation",
        "ResearchControlAction",
        "ResearchPortfolioBuilder",
        "ResearchPortfolioDependency",
        "ResearchNodeRef",
    }
    assert expected <= set(api.__all__)

    retired = {
        "MethodProgram",
        "MethodProgramBuilder",
        "CapabilityRequest",
        "EnvironmentProviderPort",
        "ProjectModelBinding",
        "StudyExecutionPlan",
        "ResearchCampaignPlan",
        "bind_research_campaign",
        "bind_research_execution_pool",
    }
    assert retired.isdisjoint(api.__all__)
    for name in retired:
        assert not hasattr(api, name)


    assert not hasattr(api, "ResearchOSPort")


def test_research_implementation_identity_is_derived_without_manual_hashes() -> None:
    implementation = api.ResearchImplementation.from_callable(
        "sem-method",
        _sem_method_v1,
    )
    assert implementation.module == __name__
    assert implementation.qualname == "_sem_method_v1"
    assert len(implementation.source_digest) == 64
    assert len(implementation.implementation_digest) == 64

    program = _program()
    definition = next(
        row for row in program.definitions
        if row.definition_id == "sem-method"
    )
    assert definition.implementation == implementation


def test_research_program_builder_freezes_whole_paper_semantics() -> None:
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


def test_research_program_digest_changes_when_scientific_semantics_change() -> None:
    first = _program()
    builder = api.ResearchProgramBuilder("sem")
    builder.method("sem-method", implementation=_sem_method_v2)
    builder.experiment(
        "main",
        definitions=("sem-method",),
    )
    second = builder.freeze()
    assert first.program_digest != second.program_digest


def test_portfolio_builder_connects_multiple_papers_as_one_typed_graph() -> None:
    search_builder = api.ResearchProgramBuilder("paper-a")
    search_builder.selection(
        "select",
        outputs=(
            api.ResearchOutputSpec(
                "best-candidate",
                api.ResearchValueKind.SELECTION,
            ),
        ),
    )
    search = search_builder.freeze()

    confirm_builder = api.ResearchProgramBuilder("paper-b")
    confirm_builder.node(
        "confirm",
        kind=api.ResearchNodeKind.EXPERIMENT,
    )
    confirm = confirm_builder.freeze()

    portfolio = (
        api.ResearchPortfolioBuilder("portfolio")
        .program(search)
        .program(confirm)
        .depends(
            upstream_program_id="paper-a",
            upstream_node_id="select",
            downstream_program_id="paper-b",
            downstream_node_id="confirm",
            bindings=(
                api.ResearchInputBinding(
                    "candidate",
                    "best-candidate",
                    api.ResearchValueKind.SELECTION,
                ),
            ),
        )
        .freeze()
    )

    assert tuple(program.program_id for program in portfolio.programs) == (
        "paper-a",
        "paper-b",
    )
    assert len(portfolio.dependencies) == 1
    dependency = portfolio.dependencies[0]
    assert dependency.upstream == api.ResearchNodeRef("paper-a", "select")
    assert dependency.downstream == api.ResearchNodeRef("paper-b", "confirm")
    assert dependency.bindings[0].input_name == "candidate"


def test_portfolio_rejects_cross_program_dependency_cycle() -> None:
    first_builder = api.ResearchProgramBuilder("paper-a")
    first_builder.node("a", kind=api.ResearchNodeKind.ANALYSIS)
    first = first_builder.freeze()

    second_builder = api.ResearchProgramBuilder("paper-b")
    second_builder.node("b", kind=api.ResearchNodeKind.ANALYSIS)
    second = second_builder.freeze()

    builder = api.ResearchPortfolioBuilder("cyclic")
    builder.program(first).program(second)
    builder.depends(
        upstream_program_id="paper-a",
        upstream_node_id="a",
        downstream_program_id="paper-b",
        downstream_node_id="b",
    )
    builder.depends(
        upstream_program_id="paper-b",
        upstream_node_id="b",
        downstream_program_id="paper-a",
        downstream_node_id="a",
    )

    try:
        builder.freeze()
    except ValueError as exc:
        assert "dependency cycle" in str(exc)
    else:
        raise AssertionError("cross-program dependency cycle was accepted")


def test_research_os_unifies_revision_and_live_control() -> None:
    port = _Port()
    research_os = bind_research_os(port)
    assert isinstance(research_os, api.ResearchOS)
    portfolio = api.ResearchPortfolio("main", (_program(),))

    revision = research_os.commit(portfolio, message="initial SEM graph")
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

    paused = research_os.pause("sem.confirmatory")
    resumed = research_os.resume("sem.confirmatory")

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
    assert paused.action is api.ResearchControlAction.PAUSE
    assert resumed.action is api.ResearchControlAction.RESUME
    assert tuple(row.action for row in port.controls) == (
        api.ResearchControlAction.PAUSE,
        api.ResearchControlAction.RESUME,
    )
