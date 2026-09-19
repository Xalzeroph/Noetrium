from __future__ import annotations

from collections.abc import Mapping

from noetrium.platform import run_method_program
from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor,
    CapabilityRequest,
    CapabilityResult,
    capability_request_digest,
)
from noetrium_platform.foundation.kernel.kernel import (
    EffectCertainty,
    EffectClass,
    EffectReceipt,
    ExecutionContext,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodAgentRequest,
    MethodAgentResult,
    MethodRunStatus,
    MethodRuntimeContext,
)
from research.benchmarks.swe_bench import SWEBenchTaskRecord, build_swe_bench_task_set
from research.reproductions.swe_agent_swebench.program import (
    SWE_AGENT_PAPER_ERA_METHOD_PROGRAM,
    swe_agent_paper_era_initial_state,
)
from research.reproductions.swe_agent_swebench.study import (
    build_swe_agent_swebench_study,
)


def _context() -> ExecutionContext:
    return ExecutionContext(
        run_id="swe-agent-run",
        trace_id="trace-1",
        span_id="span-1",
        study_id="swe-agent-study",
        task_id="django__django-1",
        decision_cycle_id="cycle-1",
        participant_generations=(),
    )


class _SequenceAgent:
    def __init__(self) -> None:
        self.views: list[Mapping[str, object]] = []
        self.outputs = [
            {
                "discussion": "Inspect the repository before editing.",
                "command": "ls",
            },
            {
                "discussion": "The change is complete; submit the patch.",
                "command": "submit",
            },
        ]

    def run(self, request: MethodAgentRequest) -> MethodAgentResult:
        assert request.agent_id == "swe-agent.paper-era"
        self.views.append(request.view)
        if not self.outputs:
            raise AssertionError("SWE-agent output sequence exhausted")
        return MethodAgentResult(value=self.outputs.pop(0))


class _SoftwareCommandCapability:
    def __init__(self) -> None:
        self.requests: list[CapabilityRequest] = []
        self._descriptor = CapabilityDescriptor(
            "software.command",
            "1",
            "swe-agent.command.v1",
            "swe-agent.observation.v1",
            effect_class=EffectClass.RECONCILABLE,
        )

    def describe(self, capability_id: str) -> CapabilityDescriptor:
        assert capability_id == "software.command"
        return self._descriptor

    def invoke(self, request: CapabilityRequest) -> CapabilityResult:
        self.requests.append(request)
        assert isinstance(request.payload, Mapping)
        command = request.payload.get("command")
        assert isinstance(command, str)
        digest = capability_request_digest(request)
        submitted = command == "submit"
        return CapabilityResult(
            capability_id="software.command",
            payload={
                "stdout": "README.md\nsrc" if command == "ls" else "submitted",
                "done": submitted,
                "patch_reference": "artifact:prediction.patch" if submitted else None,
            },
            generation=f"software-generation-{len(self.requests)}",
            effect=EffectReceipt(
                effect_id=f"software-effect-{len(self.requests)}",
                request_digest=digest,
                effect_class=EffectClass.RECONCILABLE,
                certainty=EffectCertainty.EFFECT_CONFIRMED,
            ),
            request_digest=digest,
        )


def test_swe_agent_method_program_runs_command_observation_submit_loop(tmp_path) -> None:
    agent = _SequenceAgent()
    software = _SoftwareCommandCapability()

    result = run_method_program(
        SWE_AGENT_PAPER_ERA_METHOD_PROGRAM,
        runtime=MethodRuntimeContext(
            execution=_context(),
            agent_loop=agent,
            capabilities=software,
        ),
        initial_state=swe_agent_paper_era_initial_state(
            task_instruction="Fix the issue and submit the patch.",
            initial_observation="Repository is ready.",
        ),
        state_root=tmp_path / "machine",
    )

    assert result.status is MethodRunStatus.SUCCEEDED
    assert result.value["submitted"] is True
    assert result.value["environment_done"] is True
    assert result.value["turn_count"] == 2
    assert result.value["command_count"] == 2
    assert result.value["submission_artifact"] == "artifact:prediction.patch"

    # Critical UMM dataflow invariant: the capability sees the immediately
    # preceding prepare-node value, never the study's original task input.
    assert [request.payload for request in software.requests] == [
        {"command": "ls"},
        {"command": "submit"},
    ]

    assert len(agent.views) == 2
    assert agent.views[0]["task_instruction"] == "Fix the issue and submit the patch."
    second_history = agent.views[1]["history"]
    assert isinstance(second_history, tuple)
    assert any(
        isinstance(row, Mapping)
        and row.get("message_type") == "observation"
        and row.get("content") == "README.md\nsrc"
        for row in second_history
    )


def test_swe_agent_study_binds_exact_swe_bench_cut_and_measurements() -> None:
    benchmark = build_swe_bench_task_set(
        (
            SWEBenchTaskRecord(
                instance_id="django__django-1",
                repo="django/django",
                base_commit="0123456789abcdef0123456789abcdef01234567",
                split_id="test",
                content_digest="c" * 64,
            ),
        ),
        subset="verified",
        harness_commit="a" * 40,
        dataset_revision="dataset-cut-1",
        dataset_content_sha256="b" * 64,
    )

    study = build_swe_agent_swebench_study(benchmark, split_id="test")

    assert study.benchmark.cut_digest == benchmark.cut_digest
    assert study.benchmark_split_id == "test"
    assert study.binding_requirements.participants[0].method_id == "swe-agent-paper-era"
    assert tuple(
        row.measurement_id for row in study.measurement_protocol.measurements
    ) == ("command_count", "task_resolved", "turn_count")
    assert study.trial_protocol_identity.protocol_id == "swe-agent.paper-era.swe-bench.v1"
