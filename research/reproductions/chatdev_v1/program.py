from __future__ import annotations

from collections.abc import Mapping

from noetrium_platform.capabilities.participant.method.api import (
    MethodIdentity,
    MethodProgramIdentity,
)
from noetrium_platform.foundation.kernel.kernel import (
    ChildMachineLink,
    JsonObject,
    JsonValue,
    canonical_digest,
)
from noetrium_platform.research.execution.machines.api import (
    ChildFailurePolicy,
    ChildResearchMachineExecution,
    ChildResearchMachineRequest,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodEvent,
    MethodExecutionClass,
    MethodNodeRequest,
    MethodNodeResult,
    MethodProgram,
    MethodProgramBuilder,
)

from .chain import (
    CHATDEV_V1_COMPOSED_PHASES,
    CHATDEV_V1_SIMPLE_PHASES,
    CHATDEV_V1_TOP_LEVEL_CHAIN,
    ChatDevV1SimplePhaseSpec,
)
from .environment import (
    CHATDEV_V1_ENVIRONMENT_PROGRAM,
    ChatDevV1EnvironmentAction,
    ChatDevV1PhaseDisposition,
    chatdev_v1_environment_initial_data,
)
from .fidelity import CHATDEV_V1_AUDITED_COMMIT
from .runtime import (
    CHATDEV_V1_PHASE_RUNTIME_PROGRAM,
    chatdev_v1_phase_initial_data,
)

_PHASE_RUNTIME_HOST_ID = "chatdev.v1.phase-runtime"
_ENVIRONMENT_HOST_ID = "chatdev.v1.software-environment"


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value


def _mapping(value: object, field_name: str) -> dict[str, JsonValue]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be an object")
    return dict(value)


def _phase_spec_payload(phase: ChatDevV1SimplePhaseSpec) -> JsonObject:
    return {
        "name": phase.name,
        "assistant_role": phase.assistant_role,
        "user_role": phase.user_role,
        "max_turns": phase.max_turns,
        "reflect": phase.reflect,
    }


def _chain_digest() -> str:
    rows: list[JsonObject] = []
    for phase in CHATDEV_V1_TOP_LEVEL_CHAIN:
        if isinstance(phase, ChatDevV1SimplePhaseSpec):
            rows.append({
                "kind": "simple",
                "phase": _phase_spec_payload(phase),
            })
        else:
            rows.append({
                "kind": "composed",
                "name": phase.name,
                "cycle_limit": phase.cycle_limit,
                "composition": tuple(
                    _phase_spec_payload(item)
                    for item in phase.composition
                ),
                "stop_condition": phase.stop_condition,
            })
    return canonical_digest(tuple(rows))


CHATDEV_V1_CHAIN_DIGEST = _chain_digest()


def chatdev_v1_chain_initial_state(
    *,
    task_prompt: str,
    phase_prompts: Mapping[str, str],
) -> JsonObject:
    task_prompt = _text(task_prompt, "ChatDev v1 task_prompt")
    prompts = dict(phase_prompts)
    expected = set(CHATDEV_V1_SIMPLE_PHASES)
    if set(prompts) != expected:
        missing = tuple(sorted(expected - set(prompts)))
        extra = tuple(sorted(set(prompts) - expected))
        raise ValueError(
            "ChatDev v1 phase prompt set mismatch: "
            f"missing={missing} extra={extra}"
        )
    for name, value in prompts.items():
        prompts[name] = _text(
            value,
            f"ChatDev v1 phase prompt {name}",
        )

    return {
        "source_commit": CHATDEV_V1_AUDITED_COMMIT,
        "chain_digest": CHATDEV_V1_CHAIN_DIGEST,
        "phase_runtime_program_digest": (
            CHATDEV_V1_PHASE_RUNTIME_PROGRAM.program_digest
        ),
        "environment_program_digest": (
            CHATDEV_V1_ENVIRONMENT_PROGRAM.program_digest
        ),
        "task_prompt": task_prompt,
        "phase_prompts": prompts,
        "phase_results": (),
        "latest_environment_digest": None,
        "code_complete_cycle": 0,
        "code_review_cycle": 0,
        "test_cycle": 0,
    }


def _phase_prompt(request: MethodNodeRequest, phase_name: str) -> str:
    prompts = _mapping(
        request.state.get("phase_prompts"),
        "ChatDev v1 phase_prompts",
    )
    return _text(
        prompts.get(phase_name),
        f"ChatDev v1 phase prompt {phase_name}",
    )


def _phase_results(request: MethodNodeRequest) -> tuple[JsonObject, ...]:
    value = request.state.get("phase_results", ())
    if not isinstance(value, (tuple, list)):
        raise TypeError("ChatDev v1 phase_results must be a sequence")
    rows: list[JsonObject] = []
    for row in value:
        if not isinstance(row, Mapping):
            raise TypeError("ChatDev v1 phase result row must be an object")
        rows.append(dict(row))
    return tuple(rows)


def _require_nested_runtime(request: MethodNodeRequest) -> None:
    if request.child_machines is None or request.parent_machine_id is None:
        raise RuntimeError(
            "ChatDev v1 requires nested Research-Machine runtime"
        )


def _execute_environment_child(
    request: MethodNodeRequest,
    *,
    action: ChatDevV1EnvironmentAction,
    phase_name: str,
    cycle_index: int,
    conclusion: str | None = None,
    phase_result: JsonObject | None = None,
    preparation_result: JsonObject | None = None,
) -> ChildResearchMachineExecution:
    _require_nested_runtime(request)
    task_prompt = _text(
        request.state.get("task_prompt"),
        "ChatDev v1 task_prompt",
    )
    initial_data = chatdev_v1_environment_initial_data(
        action=action,
        phase_name=phase_name,
        cycle_index=cycle_index,
        task_prompt=task_prompt,
        prior_phase_results=_phase_results(request),
        conclusion=conclusion,
        phase_result=phase_result,
        preparation_result=preparation_result,
    )
    child_machine_id = (
        f"{request.parent_machine_id}:chatdev-env:"
        f"{phase_name.lower()}:{cycle_index}:{action.value}:{request.visit}"
    )
    child = request.child_machines.execute(
        ChildResearchMachineRequest(
            host_id=_ENVIRONMENT_HOST_ID,
            parent_machine_id=request.parent_machine_id,
            child_machine_id=child_machine_id,
            instance_identity={
                "source_commit": CHATDEV_V1_AUDITED_COMMIT,
                "environment_program_digest": (
                    CHATDEV_V1_ENVIRONMENT_PROGRAM.program_digest
                ),
                "action": action.value,
                "phase_name": phase_name,
                "cycle_index": cycle_index,
                "initial_data_digest": canonical_digest(initial_data),
                "child_registry_identity_digest": (
                    request.child_machines.identity_digest
                ),
            },
            initial_data=initial_data,
            failure_policy=ChildFailurePolicy.FAIL_PARENT,
            command_id_prefix=child_machine_id,
        )
    )
    if not isinstance(child, ChildResearchMachineExecution):
        raise TypeError(
            "ChatDev v1 environment child returned invalid execution"
        )
    if child.status.value != "completed":
        raise RuntimeError(
            "ChatDev v1 environment child did not complete: "
            f"{phase_name}:{action.value}:{child.status.value}"
        )
    if not isinstance(child.result, Mapping):
        raise TypeError(
            "ChatDev v1 environment child result must be an object"
        )
    return child


def _execute_phase_runtime_child(
    request: MethodNodeRequest,
    phase: ChatDevV1SimplePhaseSpec,
    *,
    cycle_index: int,
    placeholders: JsonObject,
) -> ChildResearchMachineExecution:
    _require_nested_runtime(request)
    task_prompt = _text(
        request.state.get("task_prompt"),
        "ChatDev v1 task_prompt",
    )
    phase_prompt = _phase_prompt(request, phase.name)
    initial_data = chatdev_v1_phase_initial_data(
        phase=phase,
        task_prompt=task_prompt,
        phase_prompt=phase_prompt,
        placeholders=placeholders,
    )
    phase_identity = {
        "source_commit": CHATDEV_V1_AUDITED_COMMIT,
        "chain_digest": CHATDEV_V1_CHAIN_DIGEST,
        "phase_runtime_program_digest": (
            CHATDEV_V1_PHASE_RUNTIME_PROGRAM.program_digest
        ),
        "phase": _phase_spec_payload(phase),
        "cycle_index": cycle_index,
        "phase_prompt_digest": canonical_digest(phase_prompt),
        "initial_data_digest": canonical_digest(initial_data),
        "child_registry_identity_digest": (
            request.child_machines.identity_digest
        ),
    }
    child_machine_id = (
        f"{request.parent_machine_id}:chatdev-runtime:"
        f"{phase.name.lower()}:{cycle_index}:{request.visit}"
    )
    child = request.child_machines.execute(
        ChildResearchMachineRequest(
            host_id=_PHASE_RUNTIME_HOST_ID,
            parent_machine_id=request.parent_machine_id,
            child_machine_id=child_machine_id,
            instance_identity=phase_identity,
            initial_data=initial_data,
            failure_policy=ChildFailurePolicy.FAIL_PARENT,
            command_id_prefix=child_machine_id,
        )
    )
    if not isinstance(child, ChildResearchMachineExecution):
        raise TypeError(
            "ChatDev v1 phase child returned invalid execution"
        )
    if child.status.value != "completed":
        raise RuntimeError(
            "ChatDev v1 phase child did not complete: "
            f"{phase.name}:{child.status.value}"
        )
    if not isinstance(child.result, Mapping):
        raise TypeError("ChatDev v1 phase child result must be an object")
    return child


def _child_result(child: ChildResearchMachineExecution) -> JsonObject:
    if not isinstance(child.result, Mapping):
        raise TypeError("ChatDev v1 child result must be an object")
    return dict(child.result)


def _append_phase_result(
    request: MethodNodeRequest,
    *,
    phase: ChatDevV1SimplePhaseSpec,
    cycle_index: int,
    phase_result: JsonObject,
    preparation: ChildResearchMachineExecution,
    runtime: ChildResearchMachineExecution | None,
    application: ChildResearchMachineExecution,
) -> tuple[JsonObject, ...]:
    rows = list(_phase_results(request))
    prep_result = _child_result(preparation)
    apply_result = _child_result(application)
    rows.append({
        "phase_name": phase.name,
        "cycle_index": cycle_index,
        "phase_result": phase_result,
        "environment_preparation_digest": prep_result.get(
            "preparation_digest"
        ),
        "environment_application_digest": apply_result.get(
            "application_digest"
        ),
        "environment_digest": apply_result.get("environment_digest"),
        "environment_state_projection": apply_result.get(
            "state_projection",
            {},
        ),
        "runtime_child_link_digest": (
            None if runtime is None else runtime.link.link_digest
        ),
        "prepare_child_link_digest": preparation.link.link_digest,
        "apply_child_link_digest": application.link.link_digest,
    })
    return tuple(rows)


def _prepare_phase(
    request: MethodNodeRequest,
    phase: ChatDevV1SimplePhaseSpec,
    cycle_index: int,
) -> tuple[
    ChildResearchMachineExecution,
    ChatDevV1PhaseDisposition,
    JsonObject,
]:
    child = _execute_environment_child(
        request,
        action=ChatDevV1EnvironmentAction.PREPARE_PHASE,
        phase_name=phase.name,
        cycle_index=cycle_index,
    )
    result = _child_result(child)
    disposition = ChatDevV1PhaseDisposition(
        _text(
            result.get("disposition"),
            "ChatDev v1 phase disposition",
        )
    )
    placeholders = result.get("placeholders", {})
    if not isinstance(placeholders, Mapping):
        raise TypeError(
            "ChatDev v1 environment placeholders must be an object"
        )
    return child, disposition, dict(placeholders)


def _execute_phase_pipeline(
    request: MethodNodeRequest,
    phase: ChatDevV1SimplePhaseSpec,
    *,
    cycle_index: int,
) -> tuple[
    JsonObject | None,
    tuple[JsonObject, ...],
    tuple[ChildMachineLink, ...],
    ChatDevV1PhaseDisposition,
]:
    preparation, disposition, placeholders = _prepare_phase(
        request,
        phase,
        cycle_index,
    )
    prep_result = _child_result(preparation)
    if disposition is ChatDevV1PhaseDisposition.SKIP:
        return (
            None,
            _phase_results(request),
            (preparation.link,),
            disposition,
        )

    runtime: ChildResearchMachineExecution | None = None
    if disposition is ChatDevV1PhaseDisposition.DIRECT:
        conclusion = prep_result.get("direct_conclusion")
        if type(conclusion) is not str:
            raise TypeError(
                "ChatDev v1 DIRECT preparation requires conclusion"
            )
        phase_result: JsonObject = {
            "phase_name": phase.name,
            "assistant_role": phase.assistant_role,
            "user_role": phase.user_role,
            "turn_count": 0,
            "stop_reason": prep_result.get("reason_code"),
            "reflected": False,
            "conclusion": conclusion,
            "transcript": (),
            "reflection_transcript": (),
        }
    else:
        runtime = _execute_phase_runtime_child(
            request,
            phase,
            cycle_index=cycle_index,
            placeholders=placeholders,
        )
        phase_result = _child_result(runtime)
        conclusion = _text(
            phase_result.get("conclusion"),
            f"ChatDev v1 {phase.name} conclusion",
        )

    application = _execute_environment_child(
        request,
        action=ChatDevV1EnvironmentAction.APPLY_PHASE,
        phase_name=phase.name,
        cycle_index=cycle_index,
        conclusion=conclusion,
        phase_result=phase_result,
        preparation_result=prep_result,
    )
    rows = _append_phase_result(
        request,
        phase=phase,
        cycle_index=cycle_index,
        phase_result=phase_result,
        preparation=preparation,
        runtime=runtime,
        application=application,
    )
    links = (
        (preparation.link, application.link)
        if runtime is None
        else (preparation.link, runtime.link, application.link)
    )
    return phase_result, rows, links, disposition


_LINEAR_FLOW = {
    "demand_analysis": ("DemandAnalysis", "language_choose"),
    "language_choose": ("LanguageChoose", "coding"),
    "coding": ("Coding", "code_complete"),
    "environment_doc": ("EnvironmentDoc", "manual"),
    "manual": ("Manual", "return"),
}


def _run_linear_phase(request: MethodNodeRequest) -> MethodNodeResult:
    try:
        phase_name, next_node = _LINEAR_FLOW[request.node_id]
    except KeyError as exc:
        raise KeyError(
            f"unknown ChatDev v1 linear phase node: {request.node_id}"
        ) from exc
    phase = CHATDEV_V1_SIMPLE_PHASES[phase_name]
    result, rows, links, disposition = _execute_phase_pipeline(
        request,
        phase,
        cycle_index=0,
    )
    if disposition is ChatDevV1PhaseDisposition.SKIP or result is None:
        raise RuntimeError(
            f"ChatDev v1 top-level phase cannot be skipped: {phase_name}"
        )
    latest_environment = rows[-1].get("environment_digest")
    return MethodNodeResult(
        value=result,
        state_update={
            "phase_results": rows,
            "latest_environment_digest": latest_environment,
        },
        next_node=next_node,
        child_links=links,
        events=(
            MethodEvent(
                "chatdev.phase.completed",
                {
                    "phase_name": phase_name,
                    "cycle_index": 0,
                    "disposition": disposition.value,
                },
            ),
        ),
    )


def _run_code_complete(request: MethodNodeRequest) -> MethodNodeResult:
    cycle = request.visit
    phase = CHATDEV_V1_SIMPLE_PHASES["CodeComplete"]
    result, rows, links, disposition = _execute_phase_pipeline(
        request,
        phase,
        cycle_index=cycle,
    )
    if disposition is ChatDevV1PhaseDisposition.SKIP:
        return MethodNodeResult(
            value={
                "phase_name": "CodeCompleteAll",
                "cycle_index": cycle,
                "early_stop": True,
                "reason": "unimplemented_file_is_empty",
            },
            state_update={"code_complete_cycle": cycle},
            next_node="code_review_comment",
            child_links=links,
            events=(
                MethodEvent(
                    "chatdev.composed-phase.stopped",
                    {
                        "phase_name": "CodeCompleteAll",
                        "cycle_index": cycle,
                        "condition": "unimplemented_file_is_empty",
                    },
                ),
            ),
        )
    next_cycle = cycle + 1
    next_node = (
        "code_review_comment"
        if next_cycle
        >= CHATDEV_V1_COMPOSED_PHASES["CodeCompleteAll"].cycle_limit
        else "code_complete"
    )
    return MethodNodeResult(
        value=result,
        state_update={
            "phase_results": rows,
            "code_complete_cycle": next_cycle,
            "latest_environment_digest": rows[-1].get(
                "environment_digest"
            ),
        },
        next_node=next_node,
        child_links=links,
    )


def _run_review_comment(request: MethodNodeRequest) -> MethodNodeResult:
    cycle = request.visit
    result, rows, links, disposition = _execute_phase_pipeline(
        request,
        CHATDEV_V1_SIMPLE_PHASES["CodeReviewComment"],
        cycle_index=cycle,
    )
    if disposition is ChatDevV1PhaseDisposition.SKIP or result is None:
        raise RuntimeError("ChatDev v1 review comment cannot be skipped")
    return MethodNodeResult(
        value=result,
        state_update={
            "phase_results": rows,
            "latest_environment_digest": rows[-1].get(
                "environment_digest"
            ),
        },
        next_node="code_review_modification",
        child_links=links,
    )


def _run_review_modification(
    request: MethodNodeRequest,
) -> MethodNodeResult:
    cycle = request.visit
    result, rows, links, disposition = _execute_phase_pipeline(
        request,
        CHATDEV_V1_SIMPLE_PHASES["CodeReviewModification"],
        cycle_index=cycle,
    )
    if disposition is ChatDevV1PhaseDisposition.SKIP or result is None:
        raise RuntimeError(
            "ChatDev v1 review modification cannot be skipped"
        )
    conclusion = _text(
        result.get("conclusion"),
        "ChatDev v1 review modification conclusion",
    )
    # Preserve v1.0.0 source condition exactly. Phase.chatting strips <INFO>
    # before this point, so the released default path generally cannot satisfy
    # the composed-phase marker check.
    source_stop = "<INFO> Finished".lower() in conclusion.lower()
    next_cycle = cycle + 1
    next_node = (
        "test_error_summary"
        if (
            source_stop
            or next_cycle
            >= CHATDEV_V1_COMPOSED_PHASES["CodeReview"].cycle_limit
        )
        else "code_review_comment"
    )
    return MethodNodeResult(
        value=result,
        state_update={
            "phase_results": rows,
            "code_review_cycle": next_cycle,
            "latest_environment_digest": rows[-1].get(
                "environment_digest"
            ),
        },
        next_node=next_node,
        child_links=links,
        events=(
            MethodEvent(
                "chatdev.code-review.source-stop-evaluated",
                {
                    "cycle_index": cycle,
                    "source_stop": source_stop,
                },
            ),
        ),
    )


def _run_test_error_summary(
    request: MethodNodeRequest,
) -> MethodNodeResult:
    cycle = request.visit
    result, rows, links, disposition = _execute_phase_pipeline(
        request,
        CHATDEV_V1_SIMPLE_PHASES["TestErrorSummary"],
        cycle_index=cycle,
    )
    if disposition is ChatDevV1PhaseDisposition.SKIP:
        return MethodNodeResult(
            value={
                "phase_name": "Test",
                "cycle_index": cycle,
                "early_stop": True,
                "reason": "exist_bugs_flag_is_false",
            },
            state_update={"test_cycle": cycle},
            next_node="environment_doc",
            child_links=links,
            events=(
                MethodEvent(
                    "chatdev.composed-phase.stopped",
                    {
                        "phase_name": "Test",
                        "cycle_index": cycle,
                        "condition": "exist_bugs_flag_is_false",
                    },
                ),
            ),
        )
    if result is None:
        raise RuntimeError(
            "ChatDev v1 TestErrorSummary produced no result"
        )
    return MethodNodeResult(
        value=result,
        state_update={
            "phase_results": rows,
            "latest_environment_digest": rows[-1].get(
                "environment_digest"
            ),
        },
        next_node="test_modification",
        child_links=links,
    )


def _run_test_modification(request: MethodNodeRequest) -> MethodNodeResult:
    cycle = request.visit
    result, rows, links, disposition = _execute_phase_pipeline(
        request,
        CHATDEV_V1_SIMPLE_PHASES["TestModification"],
        cycle_index=cycle,
    )
    if disposition is ChatDevV1PhaseDisposition.SKIP or result is None:
        raise RuntimeError(
            "ChatDev v1 TestModification cannot be skipped"
        )
    next_cycle = cycle + 1
    next_node = (
        "environment_doc"
        if next_cycle >= CHATDEV_V1_COMPOSED_PHASES["Test"].cycle_limit
        else "test_error_summary"
    )
    return MethodNodeResult(
        value=result,
        state_update={
            "phase_results": rows,
            "test_cycle": next_cycle,
            "latest_environment_digest": rows[-1].get(
                "environment_digest"
            ),
        },
        next_node=next_node,
        child_links=links,
    )


def _return_result(request: MethodNodeRequest) -> MethodNodeResult:
    rows = _phase_results(request)
    manual_rows = tuple(
        row
        for row in rows
        if row.get("phase_name") == "Manual"
    )
    return MethodNodeResult(
        value={
            "source_commit": CHATDEV_V1_AUDITED_COMMIT,
            "chain_digest": CHATDEV_V1_CHAIN_DIGEST,
            "phase_runtime_program_digest": (
                CHATDEV_V1_PHASE_RUNTIME_PROGRAM.program_digest
            ),
            "environment_program_digest": (
                CHATDEV_V1_ENVIRONMENT_PROGRAM.program_digest
            ),
            "executed_phase_count": len(rows),
            "code_complete_cycles": request.state.get(
                "code_complete_cycle",
                0,
            ),
            "code_review_cycles": request.state.get(
                "code_review_cycle",
                0,
            ),
            "test_cycles": request.state.get("test_cycle", 0),
            "latest_environment_digest": request.state.get(
                "latest_environment_digest"
            ),
            "manual_conclusion": (
                None
                if not manual_rows
                else manual_rows[-1]["phase_result"].get("conclusion")
            ),
            "phase_results": rows,
        }
    )


def build_chatdev_v1_method_program() -> MethodProgram:
    configuration: JsonObject = {
        "source_commit": CHATDEV_V1_AUDITED_COMMIT,
        "chain_digest": CHATDEV_V1_CHAIN_DIGEST,
        "phase_runtime_program_digest": (
            CHATDEV_V1_PHASE_RUNTIME_PROGRAM.program_digest
        ),
        "environment_program_digest": (
            CHATDEV_V1_ENVIRONMENT_PROGRAM.program_digest
        ),
        "environment_observation_mode": "nested-environment-machine",
        "code_complete_cycle_limit": (
            CHATDEV_V1_COMPOSED_PHASES["CodeCompleteAll"].cycle_limit
        ),
        "code_review_cycle_limit": (
            CHATDEV_V1_COMPOSED_PHASES["CodeReview"].cycle_limit
        ),
        "test_cycle_limit": CHATDEV_V1_COMPOSED_PHASES["Test"].cycle_limit,
    }
    identity = MethodProgramIdentity(
        MethodIdentity(
            method_id="chatdev-v1-software-company",
            implementation_version=CHATDEV_V1_AUDITED_COMMIT[:12],
            abi_version="noetrium.method-machine.v1",
            schema_version="chatdev.v1.software-company.v1",
        ),
        configuration_digest=canonical_digest(configuration),
    )
    builder = MethodProgramBuilder(
        identity,
        entrypoint="demand_analysis",
    )
    builder.compute(
        "demand_analysis",
        "chatdev.v1.phase.demand-analysis",
        _run_linear_phase,
        ("language_choose",),
    )
    builder.compute(
        "language_choose",
        "chatdev.v1.phase.language-choose",
        _run_linear_phase,
        ("coding",),
    )
    builder.compute(
        "coding",
        "chatdev.v1.phase.coding",
        _run_linear_phase,
        ("code_complete",),
    )
    builder.route(
        "code_complete",
        "chatdev.v1.composed.code-complete",
        _run_code_complete,
        ("code_complete", "code_review_comment"),
        max_visits=CHATDEV_V1_COMPOSED_PHASES[
            "CodeCompleteAll"
        ].cycle_limit,
    )
    builder.compute(
        "code_review_comment",
        "chatdev.v1.phase.code-review-comment",
        _run_review_comment,
        ("code_review_modification",),
        max_visits=CHATDEV_V1_COMPOSED_PHASES["CodeReview"].cycle_limit,
    )
    builder.route(
        "code_review_modification",
        "chatdev.v1.composed.code-review-modification",
        _run_review_modification,
        ("code_review_comment", "test_error_summary"),
        max_visits=CHATDEV_V1_COMPOSED_PHASES["CodeReview"].cycle_limit,
    )
    builder.route(
        "test_error_summary",
        "chatdev.v1.composed.test-error-summary",
        _run_test_error_summary,
        ("test_modification", "environment_doc"),
        max_visits=CHATDEV_V1_COMPOSED_PHASES["Test"].cycle_limit,
    )
    builder.route(
        "test_modification",
        "chatdev.v1.composed.test-modification",
        _run_test_modification,
        ("test_error_summary", "environment_doc"),
        max_visits=CHATDEV_V1_COMPOSED_PHASES["Test"].cycle_limit,
    )
    builder.compute(
        "environment_doc",
        "chatdev.v1.phase.environment-doc",
        _run_linear_phase,
        ("manual",),
    )
    builder.compute(
        "manual",
        "chatdev.v1.phase.manual",
        _run_linear_phase,
        ("return",),
    )
    builder.return_node(
        "return",
        "chatdev.v1.result",
        _return_result,
    )
    return builder.build(
        configuration=configuration,
        execution_class=MethodExecutionClass.EFFECT_RECORDED,
        evidence_obligations=(
            "chatdev.phase-runtime.child-cuts",
            "chatdev.environment.child-cuts",
            "chatdev.phase-transcripts",
            "chatdev.software-artifacts",
        ),
        metric_names=(
            "executed_phase_count",
            "code_complete_cycles",
            "code_review_cycles",
            "test_cycles",
        ),
        artifact_kinds=(
            "chatdev_phase_transcript",
            "chatdev_software_artifact",
        ),
    )


CHATDEV_V1_METHOD_PROGRAM = build_chatdev_v1_method_program()


__all__ = [
    "CHATDEV_V1_CHAIN_DIGEST",
    "CHATDEV_V1_METHOD_PROGRAM",
    "build_chatdev_v1_method_program",
    "chatdev_v1_chain_initial_state",
]
