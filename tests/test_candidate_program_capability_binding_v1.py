from __future__ import annotations

from hashlib import sha256

from noetrium_platform.capabilities.participant.capability.api import CapabilityRequest
from noetrium_platform.evidence.artifact.api import ArtifactContentIdentity
from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.research.experimentation.workbench.api import (
    CandidateProgramExecutionReceipt,
    CandidateProgramExecutionStatus,
    CandidateProgramMeasurementProjection,
)
from noetrium_platform.research.experimentation.workbench.runtime import (
    CandidateProgramCapabilityBinding,
    candidate_program_capability_payload,
)


class _Publisher:
    def __init__(self) -> None:
        self.calls = 0

    def publish_source(self, *, candidate_id, generation, language, source_text):
        self.calls += 1
        digest = sha256(source_text.encode("utf-8")).hexdigest()
        return ArtifactContentIdentity(
            f"candidate-source:{candidate_id}:{generation}:{language}",
            digest,
        )


class _Executor:
    def __init__(self) -> None:
        self.calls = 0
        self.requests = []

    def execute(self, request):
        self.calls += 1
        self.requests.append(request)
        return CandidateProgramExecutionReceipt(
            request_digest=request.request_digest,
            status=CandidateProgramExecutionStatus.SUCCEEDED,
            measurement_record_digests=("7" * 64,),
            evidence_digests=("8" * 64,),
            isolation_evidence_digests=("9" * 64,),
        )


class _Projection:
    def __init__(self) -> None:
        self.calls = 0

    def project(self, receipt, *, measurement_ids):
        self.calls += 1
        assert measurement_ids == ("fitness",)
        assert receipt.measurement_record_digests == ("7" * 64,)
        return (
            CandidateProgramMeasurementProjection(
                "fitness",
                "7" * 64,
                0.625,
            ),
        )


def test_candidate_program_binding_freezes_evaluation_cut_outside_method_payload() -> None:
    publisher = _Publisher()
    executor = _Executor()
    projection = _Projection()
    binding = CandidateProgramCapabilityBinding(
        source_publisher=publisher,
        executor=executor,
        measurement_projection=projection,
        benchmark_cut_digest="a" * 64,
        evaluator_digest="b" * 64,
        isolation_requirement_id="sandbox.untrusted-python",
        measurement_ids=("fitness",),
        resource_requirement_digest="c" * 64,
    )
    context = ExecutionContext("run", "trace", "span", task_id="meta-search")
    payload = candidate_program_capability_payload(
        candidate_id="candidate:1",
        generation=1,
        source_text="def forward(self, taskInfo):\n    return '1'\n",
        language="python",
        entrypoint="forward",
        interface_schema_id="agent.forward.task-info.v1",
    )
    request = CapabilityRequest(
        "workbench.candidate-program.execute",
        payload,
        context,
        "candidate:1:generation:1",
    )

    result = binding.invoke(request)
    assert result.payload["status"] == "succeeded"
    assert result.payload["measurements"] == (
        {
            "measurement_id": "fitness",
            "record_digest": "7" * 64,
            "scalar": 0.625,
        },
    )
    execution = executor.requests[0]
    assert execution.benchmark_cut_digest == "a" * 64
    assert execution.evaluator_digest == "b" * 64
    assert execution.isolation_requirement_id == "sandbox.untrusted-python"
    assert execution.resource_requirement_digest == "c" * 64

    # Same semantic request must not republish/reexecute within one bound runtime.
    retry = binding.invoke(request)
    assert retry.digest() == result.digest()
    assert publisher.calls == 1
    assert executor.calls == 1
    assert projection.calls == 1


def test_candidate_program_binding_binds_parent_candidate_lineage() -> None:
    publisher = _Publisher()
    executor = _Executor()
    projection = _Projection()
    binding = CandidateProgramCapabilityBinding(
        source_publisher=publisher,
        executor=executor,
        measurement_projection=projection,
        benchmark_cut_digest="d" * 64,
        evaluator_digest="e" * 64,
        isolation_requirement_id="sandbox.untrusted-python",
        measurement_ids=("fitness",),
    )
    parent = "f" * 64
    request = CapabilityRequest(
        "workbench.candidate-program.execute",
        candidate_program_capability_payload(
            candidate_id="candidate:child",
            generation=2,
            source_text="def forward(self, taskInfo):\n    return '2'\n",
            language="python",
            entrypoint="forward",
            interface_schema_id="agent.forward.task-info.v1",
            parent_candidate_digests=(parent,),
        ),
        ExecutionContext("run", "trace", "span", task_id="meta-search"),
        "candidate:child:generation:2",
    )
    binding.invoke(request)
    assert executor.requests[0].candidate.parent_candidate_digests == (parent,)
