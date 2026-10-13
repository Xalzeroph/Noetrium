"""Evidence is witnessed by committed Method operations, never invented by declarations."""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from noetrium_platform.capabilities.participant.api import participant_implementation_unit
from noetrium_platform.composition.method_runtime import bind_standard_method_runtime
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, OperationExecutor
from noetrium_platform.research.execution.workflow.api import (
    MethodEvidenceStatus,
    MethodNodeKind,
    MethodNodeResult,
    MethodRunStatus,
    MethodRuntimeContext,
    method_operation,
    method_flow_relation,
    method_program,
)
from noetrium_platform.research.execution.workflow.providers.method_evidence import (
    DirectoryEventMethodEvidence,
)
from noetrium_platform.research.execution.workflow.runtime import (
    KernelOperationDispatcher,
    execute_bound_method_program,
)
from noetrium_platform.research.execution.workflow.runtime.method_machine import (
    _evidence_status,
)


def _complete(_request):
    return MethodNodeResult(value={"completed": True})


def _program():
    return method_program(
        participant_implementation_unit("method", "evidence.test", "1", "1", "1"),
        entrypoint="complete",
        operations=(
            method_operation(
                "complete", "evidence.complete",
                kind=MethodNodeKind.RETURN,
                handler=_complete,
                evidence_obligations=("evidence.test.commit",),
            ),
        ),
        evidence_obligations=("evidence.test.commit",),
    )


def test_committed_node_supplies_declared_evidence_without_faking_effect(tmp_path):
    program = _program()
    evidence = DirectoryEventMethodEvidence(tmp_path / "evidence")
    runtime = bind_standard_method_runtime(
        program,
        MethodRuntimeContext(
            ExecutionContext("evidence-run", "trace", "span"),
            dispatcher=KernelOperationDispatcher(OperationExecutor()),
            evidence=evidence,
        ),
        state_root=tmp_path / "machine",
    )
    result = execute_bound_method_program(program, runtime=runtime, input_value={})
    assert result.status is MethodRunStatus.SUCCEEDED
    assert result.evidence_status is MethodEvidenceStatus.COMPLETE
    proof = tuple(event for event in result.events if event.kind == "evidence.test.commit")
    assert len(proof) == 1
    assert proof[0].payload["node_id"] == "complete"
    assert proof[0].payload["source"] == "method.execution.commit"
    assert proof[0].payload["effect_receipt_ids"] == ()
    # The validator must fail closed if the persisted witness disappears.
    without_witness = replace(
        result, events=tuple(e for e in result.events if e.kind != "evidence.test.commit"),
    )
    assert _evidence_status(program, SimpleNamespace(evidence=evidence), without_witness) is MethodEvidenceStatus.INCOMPLETE


def test_evidence_is_not_required_when_program_has_no_obligations(tmp_path):
    program = method_program(
        participant_implementation_unit("method", "evidence.optional", "1", "1", "1"),
        entrypoint="complete",
        operations=(method_operation(
            "complete", "optional.complete", kind=MethodNodeKind.RETURN, handler=_complete,
        ),),
    )
    runtime = bind_standard_method_runtime(
        program, MethodRuntimeContext(
            ExecutionContext("optional-run", "trace", "span"),
            dispatcher=KernelOperationDispatcher(OperationExecutor()),
            evidence=DirectoryEventMethodEvidence(tmp_path / "evidence"),
        ), state_root=tmp_path / "machine",
    )
    result = execute_bound_method_program(program, runtime=runtime, input_value={})
    assert result.evidence_status is MethodEvidenceStatus.NOT_REQUIRED


def _skip_optional(_request):
    return MethodNodeResult(value={"progress": True}, next_node="complete")


def test_optional_branch_evidence_is_not_required_when_branch_is_unvisited(tmp_path):
    program = method_program(
        participant_implementation_unit("method", "evidence.branch", "1", "1", "1"),
        entrypoint="start",
        operations=(
            method_operation(
                "start", "branch.start", kind=MethodNodeKind.COMPUTE,
                handler=_skip_optional, evidence_obligations=("branch.start",),
            ),
            method_operation(
                "optional", "branch.optional", kind=MethodNodeKind.COMPUTE,
                handler=_complete, evidence_obligations=("branch.optional",),
            ),
            method_operation(
                "complete", "branch.complete", kind=MethodNodeKind.RETURN,
                handler=_complete, evidence_obligations=("branch.complete",),
            ),
        ),
        relations=(
            method_flow_relation("start", "optional"),
            method_flow_relation("start", "complete"),
            method_flow_relation("optional", "complete"),
        ),
        evidence_obligations=("branch.start", "branch.optional", "branch.complete"),
    )
    evidence = DirectoryEventMethodEvidence(tmp_path / "evidence")
    runtime = bind_standard_method_runtime(
        program, MethodRuntimeContext(
            ExecutionContext("branch-run", "trace", "span"),
            dispatcher=KernelOperationDispatcher(OperationExecutor()),
            evidence=evidence,
        ), state_root=tmp_path / "machine",
    )
    result = execute_bound_method_program(program, runtime=runtime, input_value={})
    assert result.status is MethodRunStatus.SUCCEEDED
    assert result.evidence_status is MethodEvidenceStatus.COMPLETE
    assert "branch.start" in {e.kind for e in result.events}
    assert "branch.complete" in {e.kind for e in result.events}
    assert "branch.optional" not in {e.kind for e in result.events}
