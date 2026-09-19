from __future__ import annotations

from collections.abc import Mapping

from noetrium.platform import run_method_program
from noetrium_platform.capabilities.environment.api import (
    EnvironmentQuery,
    EnvironmentQueryResult,
    Observation,
)
from noetrium_platform.capabilities.environment.composition import (
    EnvironmentQueryCapabilityBinding,
)
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
from research.benchmarks.osworld import OSWorldTaskRecord, build_osworld_task_set
from research.reproductions.ui_tars_desktop_v001.program import (
    UI_TARS_DESKTOP_V001_METHOD_PROGRAM,
    ui_tars_desktop_v001_initial_state,
)
from research.reproductions.ui_tars_desktop_v001.study import (
    build_ui_tars_osworld_study,
)


def _context() -> ExecutionContext:
    return ExecutionContext(
        run_id="ui-tars-run",
        trace_id="trace-1",
        span_id="span-1",
        study_id="ui-tars-osworld",
        task_id="task-1",
        decision_cycle_id="cycle-1",
        participant_generations=(),
    )


class _ScreenQuery:
    def __init__(self, *, invalid: bool = False) -> None:
        self.invalid = invalid
        self.requests: list[EnvironmentQuery] = []

    def query(self, request: EnvironmentQuery) -> EnvironmentQueryResult:
        self.requests.append(request)
        index = len(self.requests)
        if self.invalid:
            return EnvironmentQueryResult(
                query_id=request.query_id,
                supported=True,
                payload={},
                observation=None,
                diagnostics={"invalid_snapshot": True},
            )
        return EnvironmentQueryResult(
            query_id=request.query_id,
            supported=True,
            payload={"width": 1000, "height": 800},
            observation=Observation(
                observation_id=f"snapshot-{index}",
                generation=f"gui-generation-{index}",
                payload={"kind": "screenshot", "width": 1000, "height": 800},
                artifact_refs=(f"artifact:screenshot-{index}",),
            ),
            diagnostics={},
        )


class _Capabilities:
    def __init__(self, screen: _ScreenQuery) -> None:
        self.query = EnvironmentQueryCapabilityBinding(screen)
        self.action_requests: list[CapabilityRequest] = []
        self._action = CapabilityDescriptor(
            "environment.act",
            "1",
            "noetrium.environment.action-capability.request.v1",
            "noetrium.environment.action-capability.result.v1",
            effect_class=EffectClass.RECONCILABLE,
        )

    def describe(self, capability_id: str) -> CapabilityDescriptor:
        if capability_id == "environment.query":
            return self.query.describe(capability_id)
        if capability_id == "environment.act":
            return self._action
        raise KeyError(capability_id)

    def invoke(self, request: CapabilityRequest) -> CapabilityResult:
        if request.capability_id == "environment.query":
            return self.query.invoke(request)
        if request.capability_id != "environment.act":
            raise KeyError(request.capability_id)
        self.action_requests.append(request)
        digest = capability_request_digest(request)
        return CapabilityResult(
            capability_id="environment.act",
            payload={
                "accepted": True,
                "observation": {
                    "observation_id": f"action-observation-{len(self.action_requests)}",
                    "generation": f"gui-generation-action-{len(self.action_requests)}",
                    "payload": {"ok": True},
                    "artifact_refs": (),
                },
            },
            effect=EffectReceipt(
                effect_id=f"gui-effect-{len(self.action_requests)}",
                request_digest=digest,
                effect_class=EffectClass.RECONCILABLE,
                certainty=EffectCertainty.EFFECT_CONFIRMED,
            ),
            request_digest=digest,
        )


class _Agent:
    def __init__(self) -> None:
        self.views: list[Mapping[str, object]] = []
        self.outputs = [
            (
                "Thought: click the target then wait\n"
                "Action: click(start_box='(500,500)')\n\nwait()"
            ),
            "Action_Summary: task complete\nAction: finished()",
        ]

    def run(self, request: MethodAgentRequest) -> MethodAgentResult:
        assert request.agent_id == "ui-tars.desktop-v001"
        self.views.append(request.view)
        if not self.outputs:
            raise AssertionError("UI-TARS output sequence exhausted")
        return MethodAgentResult(value={"prediction": self.outputs.pop(0)})


def test_ui_tars_program_queries_current_screen_executes_multi_action_prediction(tmp_path) -> None:
    screen = _ScreenQuery()
    capabilities = _Capabilities(screen)
    agent = _Agent()

    result = run_method_program(
        UI_TARS_DESKTOP_V001_METHOD_PROGRAM,
        runtime=MethodRuntimeContext(
            execution=_context(),
            capabilities=capabilities,
            agent_loop=agent,
        ),
        initial_state=ui_tars_desktop_v001_initial_state(
            task_instruction="Click the target and finish.",
        ),
        state_root=tmp_path / "machine",
    )

    assert result.status is MethodRunStatus.SUCCEEDED
    assert result.value["finished"] is True
    assert result.value["terminal_action"] == "finished"
    assert result.value["loop_count"] == 2
    assert result.value["device_action_count"] == 1
    assert result.value["model_call_count"] == 2
    assert result.value["snapshot_error_count"] == 0
    assert len(screen.requests) == 2

    # click dispatches; wait and finished are method-control semantics and do not
    # create device effects.
    assert len(capabilities.action_requests) == 1
    payload = capabilities.action_requests[0].payload
    assert isinstance(payload, Mapping)
    assert payload["action_type"] == "click"
    assert payload["payload"]["x"] == 500.0
    assert payload["payload"]["y"] == 400.0

    assert agent.views[0]["images"] == ("artifact:screenshot-1",)
    assert agent.views[1]["images"] == (
        "artifact:screenshot-1",
        "artifact:screenshot-2",
    )


def test_ui_tars_program_fails_closed_after_snapshot_failure_limit(tmp_path) -> None:
    screen = _ScreenQuery(invalid=True)
    capabilities = _Capabilities(screen)

    class _NeverAgent:
        def run(self, request: MethodAgentRequest) -> MethodAgentResult:
            raise AssertionError("model must not run without a valid screenshot")

    result = run_method_program(
        UI_TARS_DESKTOP_V001_METHOD_PROGRAM,
        runtime=MethodRuntimeContext(
            execution=_context(),
            capabilities=capabilities,
            agent_loop=_NeverAgent(),
        ),
        initial_state=ui_tars_desktop_v001_initial_state(
            task_instruction="Do not act without visual state.",
        ),
        state_root=tmp_path / "machine",
    )

    assert result.status is MethodRunStatus.SUCCEEDED
    assert result.value["finished"] is False
    assert result.value["terminal_action"] == "error_env"
    assert result.value["snapshot_error_count"] == 10
    assert len(screen.requests) == 10
    assert capabilities.action_requests == []


def test_ui_tars_osworld_study_binds_exact_cut_and_metrics() -> None:
    benchmark = build_osworld_task_set(
        (
            OSWorldTaskRecord(
                task_id="task-1",
                domain="chrome",
                split_id="test",
                config_path="evaluation_examples/examples/chrome/task-1.json",
                content_digest="c" * 64,
            ),
        ),
        harness_commit="a" * 40,
        task_manifest_revision="task-cut-1",
        source_content_sha256="b" * 64,
    )
    study = build_ui_tars_osworld_study(benchmark, split_id="test")

    assert study.benchmark.cut_digest == benchmark.cut_digest
    assert study.binding_requirements.participants[0].method_id == "ui-tars-desktop-v001"
    assert tuple(
        row.measurement_id for row in study.measurement_protocol.measurements
    ) == (
        "device_action_count",
        "loop_count",
        "model_call_count",
        "snapshot_error_count",
        "task_success",
    )
    assert study.trial_protocol_identity.protocol_id == "ui-tars.desktop-v001.osworld.v1"
