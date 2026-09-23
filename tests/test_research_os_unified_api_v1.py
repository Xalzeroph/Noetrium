from __future__ import annotations

import noetrium.api as api


class _Port:
    def __init__(self) -> None:
        self.controls = []

    def commit(self, portfolio, *, parents, message):
        return api.ResearchGraphRevision(
            portfolio.portfolio_digest,
            parents,
            message,
        )

    def diff(self, left_revision_digest, right_revision_digest):
        return api.ResearchRevisionDiff(
            left_revision_digest,
            right_revision_digest,
            (),
        )

    def branch(self, name, revision_digest):
        return api.ResearchBranch(name, revision_digest)

    def tag(self, name, revision_digest):
        return api.ResearchTag(name, revision_digest)

    def merge(self, left_revision_digest, right_revision_digest, *, message):
        return api.ResearchGraphRevision(
            "a" * 64,
            (left_revision_digest, right_revision_digest),
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
    builder.method(
        "sem-method",
        implementation_id="sem-method-v1",
        implementation_digest="1" * 64,
    )
    builder.benchmark(
        "minecraft-memory",
        implementation_id="minecraft-memory-v1",
        implementation_digest="2" * 64,
    )
    builder.metric(
        "task-success",
        implementation_id="task-success-v1",
        implementation_digest="3" * 64,
    )
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
        "ResearchOSPort",
        "ResearchPortfolio",
        "ResearchProgram",
        "ResearchProgramBuilder",
        "ResearchGraphRevision",
        "ResearchDependency",
        "ResearchNode",
        "ResearchDefinition",
        "ResearchControlAction",
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
    builder.method(
        "sem-method",
        implementation_id="sem-method-v2",
        implementation_digest="4" * 64,
    )
    builder.experiment(
        "main",
        definitions=("sem-method",),
    )
    second = builder.freeze()
    assert first.program_digest != second.program_digest


def test_research_os_unifies_revision_and_live_control() -> None:
    port = _Port()
    research_os = api.ResearchOS(port)
    portfolio = api.ResearchPortfolio("main", (_program(),))

    revision = research_os.commit(portfolio, message="initial SEM graph")
    branch = research_os.branch("sem-main", revision.revision_digest)
    tag = research_os.tag("sem-confirmatory-v1", revision.revision_digest)

    paused = research_os.pause("sem.confirmatory")
    resumed = research_os.resume("sem.confirmatory")

    assert branch.revision_digest == revision.revision_digest
    assert tag.revision_digest == revision.revision_digest
    assert paused.action is api.ResearchControlAction.PAUSE
    assert resumed.action is api.ResearchControlAction.RESUME
    assert tuple(row.action for row in port.controls) == (
        api.ResearchControlAction.PAUSE,
        api.ResearchControlAction.RESUME,
    )
