from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    InMemoryMachineJournal,
    canonical_digest,
)
from noetrium_platform.research.execution.machines.api import (
    ChildResearchHostRegistry,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodRunStatus,
    MethodRuntimeContext,
)
from noetrium_platform.research.execution.workflow.composition import (
    bind_machine_method_runtime,
)
from noetrium_platform.research.execution.workflow.runtime import (
    UniversalMethodMachine,
)
from research.reproductions.chatdev_v1.chain import CHATDEV_V1_SIMPLE_PHASES
from research.reproductions.chatdev_v1.environment import (
    CHATDEV_V1_ENVIRONMENT_PROGRAM,
    ChatDevV1EnvironmentApplication,
    ChatDevV1EnvironmentBinding,
    ChatDevV1EnvironmentPreparation,
    ChatDevV1PhaseDisposition,
    chatdev_v1_environment_host,
)
from research.reproductions.chatdev_v1.program import (
    CHATDEV_V1_METHOD_PROGRAM,
    chatdev_v1_chain_initial_state,
)
from research.reproductions.chatdev_v1.runtime import (
    CHATDEV_V1_PHASE_RUNTIME_PROGRAM,
    ChatDevV1PhaseRuntimeBinding,
    ChatDevV1RolePlayExchange,
    chatdev_v1_phase_runtime_host,
)


class _RolePlay:
    def __init__(self):
        self.requests = []

    @property
    def identity_digest(self):
        return canonical_digest({
            "provider": "chatdev-v1-test-roleplay",
            "implementation_revision": 1,
        })

    def exchange(self, request):
        self.requests.append(request)
        if request.phase_name in {
            "DemandAnalysis",
            "LanguageChoose",
            "EnvironmentDoc",
        }:
            return ChatDevV1RolePlayExchange(
                assistant_message=f"<INFO> {request.phase_name}-answer",
                user_message="ack",
                assistant_info=True,
            )
        if request.phase_name == "CodeReviewModification":
            # The original non-reflection Phase.chatting strips <INFO> before
            # ComposedPhase.break_cycle checks for "<INFO> Finished".
            return ChatDevV1RolePlayExchange(
                assistant_message="<INFO> Finished",
                user_message="ack",
            )
        return ChatDevV1RolePlayExchange(
            assistant_message=f"{request.phase_name}-answer",
            user_message="ack",
        )


class _SoftwareEnvironment:
    def __init__(self):
        self.prepare_requests = []
        self.apply_requests = []

    @property
    def identity_digest(self):
        return canonical_digest({
            "provider": "chatdev-v1-test-workspace",
            "implementation_revision": 1,
        })

    def prepare(self, request):
        self.prepare_requests.append(request)
        environment_digest = canonical_digest({
            "phase": request.phase_name,
            "cycle": request.cycle_index,
            "stage": "prepare",
        })
        if request.phase_name == "CodeComplete":
            return ChatDevV1EnvironmentPreparation(
                phase_name=request.phase_name,
                cycle_index=request.cycle_index,
                placeholders={},
                disposition=ChatDevV1PhaseDisposition.SKIP,
                reason_code="unimplemented_file_is_empty",
                environment_digest=environment_digest,
            )
        if request.phase_name == "TestErrorSummary":
            return ChatDevV1EnvironmentPreparation(
                phase_name=request.phase_name,
                cycle_index=request.cycle_index,
                placeholders={},
                disposition=ChatDevV1PhaseDisposition.SKIP,
                reason_code="exist_bugs_flag_is_false",
                environment_digest=environment_digest,
            )
        return ChatDevV1EnvironmentPreparation(
            phase_name=request.phase_name,
            cycle_index=request.cycle_index,
            placeholders={
                "phase": request.phase_name,
                "cycle": request.cycle_index,
            },
            environment_digest=environment_digest,
        )

    def apply(self, request):
        self.apply_requests.append(request)
        environment_digest = canonical_digest({
            "phase": request.phase_name,
            "cycle": request.cycle_index,
            "conclusion": request.conclusion,
            "stage": "apply",
        })
        return ChatDevV1EnvironmentApplication(
            phase_name=request.phase_name,
            cycle_index=request.cycle_index,
            environment_digest=environment_digest,
            state_projection={
                "last_phase": request.phase_name,
                "last_conclusion": request.conclusion,
            },
        )


def _role_prompts():
    return {
        "Chief Product Officer": "product",
        "Chief Executive Officer": "ceo",
        "Chief Technology Officer": "cto",
        "Programmer": "programmer",
        "Code Reviewer": "reviewer",
        "Software Test Engineer": "tester",
        "Counselor": "counselor",
    }


def _phase_prompts():
    return {
        phase_name: f"official prompt placeholder for {phase_name}"
        for phase_name in CHATDEV_V1_SIMPLE_PHASES
    }


def test_chatdev_method_program_commits_runtime_and_environment_child_cuts() -> None:
    role_play = _RolePlay()
    software = _SoftwareEnvironment()
    phase_binding = ChatDevV1PhaseRuntimeBinding(
        role_play=role_play,
        role_prompts=_role_prompts(),
    )
    environment_binding = ChatDevV1EnvironmentBinding(software)

    child_journal = InMemoryMachineJournal()
    phase_host = chatdev_v1_phase_runtime_host(journal=child_journal)
    environment_host = chatdev_v1_environment_host(journal=child_journal)
    registry = ChildResearchHostRegistry()
    registry.register_static(phase_host, phase_binding)
    registry.register_static(environment_host, environment_binding)
    children = registry.executor()

    runtime = MethodRuntimeContext(
        ExecutionContext(
            "chatdev-v1-run",
            "trace",
            "span",
            task_id="software:demo",
        ),
        child_machines=children,
    )
    runtime = bind_machine_method_runtime(
        CHATDEV_V1_METHOD_PROGRAM,
        runtime,
        machine_id="method:chatdev-v1:test",
    )
    initial_state = chatdev_v1_chain_initial_state(
        task_prompt="Build a small calculator.",
        phase_prompts=_phase_prompts(),
    )

    result = UniversalMethodMachine(max_steps=128).run(
        CHATDEV_V1_METHOD_PROGRAM,
        runtime=runtime,
        initial_state=initial_state,
    )

    assert result.status is MethodRunStatus.SUCCEEDED
    assert result.value["executed_phase_count"] == 11
    assert result.value["code_complete_cycles"] == 0
    assert result.value["code_review_cycles"] == 3
    assert result.value["test_cycles"] == 0
    assert result.value["manual_conclusion"] == "Manual-answer"
    assert len(result.value["latest_environment_digest"]) == 64

    phase_names = tuple(
        row["phase_name"]
        for row in result.value["phase_results"]
    )
    assert phase_names == (
        "DemandAnalysis",
        "LanguageChoose",
        "Coding",
        "CodeReviewComment",
        "CodeReviewModification",
        "CodeReviewComment",
        "CodeReviewModification",
        "CodeReviewComment",
        "CodeReviewModification",
        "EnvironmentDoc",
        "Manual",
    )

    # Review modification emits "<INFO> Finished", but the v1 non-reflection
    # phase strips the marker before the composed break condition sees it.
    review_answers = tuple(
        row["phase_result"]["conclusion"]
        for row in result.value["phase_results"]
        if row["phase_name"] == "CodeReviewModification"
    )
    assert review_answers == (" Finished", " Finished", " Finished")

    assert runtime.transitions is not None
    parent_machine = runtime.transitions.machine
    parent_commits = parent_machine.journal.commits(
        parent_machine.machine_id
    )
    child_links = tuple(
        link
        for commit in parent_commits
        for link in commit.child_links
    )

    # 11 executed phases each produce prepare + runtime + apply child cuts.
    # CodeComplete and Test each stop on one additional prepare cut.
    assert len(child_links) == 35
    assert all(
        link.parent_machine_id == "method:chatdev-v1:test"
        for link in child_links
    )
    runtime_links = tuple(
        link
        for link in child_links
        if link.child_program_digest
        == CHATDEV_V1_PHASE_RUNTIME_PROGRAM.program_digest
    )
    environment_links = tuple(
        link
        for link in child_links
        if link.child_program_digest
        == CHATDEV_V1_ENVIRONMENT_PROGRAM.program_digest
    )
    assert len(runtime_links) == 11
    assert len(environment_links) == 24
    assert len({link.child_machine_id for link in child_links}) == 35

    # Every child here is a three-commit ResearchProgram:
    # start + (exchange/finalize for runtime is actually 3 total), or
    # start + dispatch + prepare/apply for environment.
    assert sum(
        len(child_journal.commits(link.child_machine_id))
        for link in child_links
    ) == 105
    assert len(role_play.requests) == 11
    assert len(software.prepare_requests) == 13
    assert len(software.apply_requests) == 11
